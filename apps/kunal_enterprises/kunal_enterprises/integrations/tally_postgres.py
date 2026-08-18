from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import hashlib

import frappe
import psycopg2
import psycopg2.extras
from psycopg2 import sql
from frappe.utils import convert_utc_to_system_timezone, now_datetime, nowdate

from kunal_enterprises.cron.reconciliation import run_reconciliation
from kunal_enterprises.cron.tally_sync import sync_stock_snapshots, sync_tally_masters, sync_tally_vouchers


DEFAULT_SCHEMA = "public"
STOCK_SNAPSHOT_TABLE = "stock_godown_summary"
STOCK_SNAPSHOT_STATE_TABLE = "stock_godown_summary_state"
SCHEDULED_IMPORT_JOB_ID = "kunal_enterprises:tally_postgres_import_all"
SCHEDULED_IMPORT_LOCK = "kunal_enterprises:tally_postgres_import_all"
STOCK_SNAPSHOT_V2_COLUMNS = frozenset(
	{
		"item",
		"item_guid",
		"godown",
		"godown_guid",
		"closing_qty",
		"row_type",
		"as_on_date",
		"source_company",
		"source_snapshot_id",
		"imported_at",
	}
)


def enqueue_import_all():
	"""Queue one sequential Tally import on the long worker without overlapping runs."""
	job = frappe.enqueue(
		"kunal_enterprises.integrations.tally_postgres.import_all",
		queue="long",
		timeout=1500,
		job_id=SCHEDULED_IMPORT_JOB_ID,
		deduplicate=True,
	)
	if not job:
		return {"status": "Skipped", "reason": "The Tally import pipeline is already queued or running"}
	return {"status": "Queued", "job_id": job.id}


def import_all(voucher_limit=None, run_reconciliation_after=True):
	"""Import Tally mirror data sequentially so stock never races ahead of its masters."""
	if not _acquire_import_lock():
		return {"status": "Skipped", "reason": "A Tally PostgreSQL import pipeline is already running"}
	try:
		results = {
			"masters": import_masters(),
			"stock": import_stock_snapshots(),
			"vouchers": import_vouchers(limit=voucher_limit),
		}
		if run_reconciliation_after:
			results["reconciliation"] = _serialize_run(run_reconciliation())
		return results
	finally:
		_release_import_lock()


def _acquire_import_lock():
	return bool(frappe.db.sql("SELECT GET_LOCK(%s, 0)", SCHEDULED_IMPORT_LOCK)[0][0])


def _release_import_lock():
	frappe.db.sql("SELECT RELEASE_LOCK(%s)", SCHEDULED_IMPORT_LOCK)


def import_masters():
	with _connect() as connection:
		connection.set_session(readonly=True, isolation_level="REPEATABLE READ")
		records = {
			"units": _fetch_units(connection),
			"godowns": _fetch_godowns(connection),
			"stock_categories": _fetch_stock_categories(connection),
			"stock_groups": _fetch_stock_groups(connection),
			"items": _fetch_items(connection),
			"customer_ledgers": _fetch_customer_ledgers(connection),
		}
	run = sync_tally_masters(records)
	return _serialize_run(run)


def import_stock_snapshots():
	with _connect() as connection:
		connection.set_session(readonly=True, isolation_level="REPEATABLE READ")
		if not _table_exists(connection, STOCK_SNAPSHOT_TABLE):
			return {
				"status": "Skipped",
				"reason": f"{STOCK_SNAPSHOT_TABLE} table not found in Tally PostgreSQL mirror",
			}
		snapshot_state = _fetch_stock_snapshot_state(connection)
		if snapshot_state.get("contract_version") == 2 and not snapshot_state.get("snapshot_complete"):
			return {
				"status": "Skipped",
				"reason": "Tally PostgreSQL stock snapshot is not marked complete",
			}
		integrity = None
		if snapshot_state.get("contract_version") == 2:
			missing_columns = sorted(STOCK_SNAPSHOT_V2_COLUMNS - _table_columns(connection, STOCK_SNAPSHOT_TABLE))
			if missing_columns:
				frappe.throw(f"Tally stock snapshot v2 table is missing columns: {', '.join(missing_columns)}")
			if snapshot_state.get("snapshot_complete"):
				integrity = _fetch_stock_snapshot_integrity(connection, snapshot_state)
		records = _fetch_stock_snapshots(connection, contract_version=snapshot_state.get("contract_version"))
		_validate_stock_snapshot_contract(records, snapshot_state, integrity)
	run = sync_stock_snapshots(
		records,
		snapshot_metadata=snapshot_state,
		reconcile_missing=bool(snapshot_state.get("snapshot_complete")),
	)
	return _serialize_run(run)


def ensure_stock_snapshot_table():
	"""Create the Tally loader stock snapshot table in the configured PostgreSQL mirror."""
	with _connect() as connection:
		with connection.cursor() as cursor:
			cursor.execute(
				sql.SQL(
					"""
					create table if not exists {} (
						item text,
						item_guid text,
						godown text,
						godown_guid text,
						closing_qty numeric,
						uom text,
						closing_rate numeric,
						closing_value numeric,
						stock_group text,
						batch_name text,
						row_type text not null default 'GODOWN',
						as_on_date date,
						source_company text,
						source_snapshot_id text,
						imported_at timestamp with time zone default now()
					)
					"""
				).format(_table(STOCK_SNAPSHOT_TABLE))
			)
			for column_name, definition in (
				("item_guid", "text"),
				("godown_guid", "text"),
				("stock_group", "text"),
				("batch_name", "text"),
				("row_type", "text not null default 'GODOWN'"),
				("as_on_date", "date"),
				("source_company", "text"),
				("source_snapshot_id", "text"),
			):
				cursor.execute(
					sql.SQL("alter table {} add column if not exists {} {}").format(
						_table(STOCK_SNAPSHOT_TABLE), sql.Identifier(column_name), sql.SQL(definition)
					)
				)
		connection.commit()
		return {
			"status": "Ready",
			"table": STOCK_SNAPSHOT_TABLE,
			"rows": _table_count(connection, STOCK_SNAPSHOT_TABLE),
		}


def seed_dev_stock_snapshots(
	confirm_dev_seed=False,
	clear_existing=False,
	limit=5000,
	max_godowns_per_item=3,
	zero_stock_ratio=0.2,
):
	"""Seed deterministic fake stock-by-godown rows for local product testing only."""
	if not confirm_dev_seed:
		frappe.throw("Pass confirm_dev_seed=True to seed fake dev stock snapshots")

	table_status = ensure_stock_snapshot_table()
	items = frappe.get_all(
		"Tally Item",
		filters={"is_active": 1},
		fields=["name", "uom", "tally_guid"],
		order_by="name asc",
		limit_page_length=int(limit or 5000),
	)
	godowns = frappe.get_all(
		"Tally Godown",
		filters={"is_active": 1},
		fields=["name", "tally_guid"],
		order_by="name asc",
	)
	rows = _build_dev_stock_snapshot_rows(
		items=items,
		godowns=godowns,
		max_godowns_per_item=max_godowns_per_item,
		zero_stock_ratio=zero_stock_ratio,
		as_on_date=nowdate(),
	)
	if not rows:
		return {
			"status": "Skipped",
			"reason": "No active Tally Item and Tally Godown records found",
			"table": table_status["table"],
			"rows_seeded": 0,
		}

	with _connect() as connection:
		with connection.cursor() as cursor:
			if clear_existing:
				cursor.execute(sql.SQL("delete from {}").format(_table(STOCK_SNAPSHOT_TABLE)))
			else:
				item_names = list({row["item"] for row in rows})
				for batch in _chunks(item_names, 500):
					cursor.execute(
						sql.SQL("delete from {} where item = any(%s)").format(_table(STOCK_SNAPSHOT_TABLE)),
						(batch,),
					)
			item_guids = {item["name"]: item.get("tally_guid") for item in items}
			godown_guids = {godown["name"]: godown.get("tally_guid") for godown in godowns}
			inserted_at = now_datetime()
			insert_query = sql.SQL(
				"""
				insert into {} (
					item, item_guid, godown, godown_guid, closing_qty, uom,
					closing_rate, closing_value, as_on_date, imported_at
				)
				values %s
				"""
			).format(_table(STOCK_SNAPSHOT_TABLE)).as_string(connection)
			for batch in _chunks(rows, 1000):
				psycopg2.extras.execute_values(
					cursor,
					insert_query,
					[
						(
							row["item"],
							item_guids.get(row["item"]),
							row["godown"],
							godown_guids.get(row["godown"]),
							row["quantity"],
							row["uom"],
							0,
							0,
							row["as_on_date"],
							inserted_at,
						)
						for row in batch
					],
				)
		connection.commit()
		return {
			"status": "Seeded",
			"table": STOCK_SNAPSHOT_TABLE,
			"rows_seeded": len(rows),
			"items_seen": len(items),
			"godowns_seen": len(godowns),
			"clear_existing": bool(clear_existing),
			"note": "Fake dev stock only. Run import_stock_snapshots next to sync into Frappe.",
		}


def import_vouchers(limit=None):
	with _connect() as connection:
		run = sync_tally_vouchers(_fetch_vouchers(connection, limit=limit))
	return _serialize_run(run)


def diagnose():
	"""Return non-secret Tally PostgreSQL connectivity, table, and filter counts."""
	config = _tally_postgres_config()
	with _connect() as connection:
		tables = [
			"mst_uom",
			"mst_godown",
			"mst_stock_category",
			"mst_stock_group",
			"mst_stock_item",
			"mst_ledger",
			"trn_voucher",
			"trn_inventory",
			STOCK_SNAPSHOT_TABLE,
			STOCK_SNAPSHOT_STATE_TABLE,
		]
		table_status = {}
		for table in tables:
			exists = _table_exists(connection, table)
			table_status[table] = {
				"exists": exists,
				"rows": _table_count(connection, table) if exists else None,
			}
		return {
			"host": config["host"],
			"port": config["port"],
			"dbname": config["dbname"],
			"schema": config["schema"],
			"tables": table_status,
			"voucher_rows_matching_import_filter": _voucher_filter_count(connection)
			if table_status["trn_voucher"]["exists"] and table_status["trn_inventory"]["exists"]
			else None,
		}


def diagnose_vouchers(limit=5):
	with _connect() as connection:
		sample = _fetch_vouchers(connection, limit=limit)
		return {
			"raw_rows_matching_import_filter": _voucher_filter_count(connection),
			"sample_grouped_vouchers": len(sample),
			"sample_vouchers": sample[: int(limit)],
			"imported_tally_vouchers": frappe.db.count("Tally Voucher"),
		}


@contextmanager
def _connect():
	config = _tally_postgres_config()
	connection = psycopg2.connect(
		host=config["host"],
		port=config["port"],
		dbname=config["dbname"],
		user=config["user"],
		password=config["password"],
		cursor_factory=psycopg2.extras.RealDictCursor,
	)
	try:
		yield connection
	finally:
		connection.close()


def _tally_postgres_config():
	config = {
		"host": frappe.conf.get("tally_postgres_host"),
		"port": frappe.conf.get("tally_postgres_port") or 5432,
		"dbname": frappe.conf.get("tally_postgres_dbname"),
		"user": frappe.conf.get("tally_postgres_user"),
		"password": frappe.conf.get("tally_postgres_password"),
		"schema": frappe.conf.get("tally_postgres_schema") or DEFAULT_SCHEMA,
	}
	missing = [key for key in ("host", "dbname", "user", "password") if not config.get(key)]
	if missing:
		frappe.throw(f"Missing Tally PostgreSQL config keys: {', '.join(missing)}")
	return config


def _schema():
	return _tally_postgres_config()["schema"]


def _fetch_all(connection, query, params=None):
	with connection.cursor() as cursor:
		cursor.execute(query, params or [])
		return list(cursor.fetchall())


def _table(name):
	return sql.Identifier(_schema(), name)


def _table_exists(connection, table_name):
	query = """
		select exists (
			select 1
			from information_schema.tables
			where table_schema = %s and table_name = %s
		) as exists
	"""
	return bool(_fetch_all(connection, query, [_schema(), table_name])[0]["exists"])


def _table_count(connection, table_name):
	rows = _fetch_all(connection, sql.SQL("select count(*) as count from {}").format(_table(table_name)))
	return rows[0]["count"]


def _table_columns(connection, table_name):
	rows = _fetch_all(
		connection,
		"""
		select column_name
		from information_schema.columns
		where table_schema = %s and table_name = %s
		""",
		[_schema(), table_name],
	)
	return {row["column_name"] for row in rows}


def _voucher_filter_count(connection):
	rows = _fetch_all(
		connection,
		sql.SQL(
			"""
			select count(*) as count
			from {} v
			join {} i on i.guid = v.guid
			where coalesce(v.voucher_number, '') != ''
				and coalesce(i.item, '') != ''
				and coalesce(i.godown, '') != ''
				and (
					v.voucher_type ilike 'Sales%%'
					or v.voucher_type ilike 'Delivery Challan%%'
				)
			"""
		).format(_table("trn_voucher"), _table("trn_inventory")),
	)
	return rows[0]["count"]


def _fetch_units(connection):
	rows = _fetch_all(
		connection,
		sql.SQL("select guid, name from {} where coalesce(name, '') != '' order by name").format(_table("mst_uom")),
	)
	return [
		{"unit_name": row["name"], "tally_guid": row.get("guid"), "symbol": row["name"], "is_active": 1}
		for row in rows
	]


def _fetch_godowns(connection):
	rows = _fetch_all(
		connection,
		sql.SQL("select guid, name from {} where coalesce(name, '') != '' order by name").format(_table("mst_godown")),
	)
	return [{"godown_name": row["name"], "tally_guid": row.get("guid"), "is_active": 1} for row in rows]


def _fetch_stock_categories(connection):
	rows = _fetch_all(
		connection,
		sql.SQL("select guid, name from {} where coalesce(name, '') != '' order by name").format(
			_table("mst_stock_category")
		),
	)
	return [{"category_name": row["name"], "tally_guid": row.get("guid"), "is_active": 1} for row in rows]


def _fetch_stock_groups(connection):
	rows = _fetch_all(
		connection,
		sql.SQL(
			"""
			select guid, name, parent
			from {}
			where coalesce(name, '') != ''
			order by name
			"""
		).format(_table("mst_stock_group")),
	)
	by_name = {row["name"]: row for row in rows}
	records = []
	for row in rows:
		path = _stock_group_path(row["name"], by_name)
		root = path[0] if path else row["name"]
		parent = row.get("parent") if row.get("parent") in by_name else None
		records.append(
			{
				"group_name": row["name"],
				"tally_guid": row.get("guid"),
				"source_parent_group": row.get("parent") or None,
				"parent_stock_group": parent,
				"root_stock_group": None if row["name"] == root else root,
				"is_root": 1 if row["name"] == root else 0,
				"depth": max(len(path) - 1, 0),
				"full_path": " > ".join(path or [row["name"]]),
				"is_active": 1,
				"last_synced_at": now_datetime(),
			}
		)
	return sorted(records, key=lambda record: record["depth"])


def _stock_group_path(name, by_name):
	path = []
	seen = set()
	current = name
	while current and current not in seen and current in by_name:
		seen.add(current)
		path.append(current)
		parent = by_name[current].get("parent")
		current = parent if parent in by_name else None
	return list(reversed(path))


def _fetch_items(connection):
	rows = _fetch_all(
		connection,
		sql.SQL(
			"""
			select guid, name, parent, category, uom, closing_balance
			from {}
			where coalesce(name, '') != ''
				and coalesce(parent, '') != ''
			order by name
			"""
		).format(_table("mst_stock_item")),
	)
	group_roots = _stock_group_roots(connection)
	return [
		{
			"item_name": row["name"],
			"tally_guid": row.get("guid"),
			"immediate_stock_group": row.get("parent"),
			"root_stock_group": group_roots.get(row.get("parent")) or row.get("parent"),
			"stock_category": row.get("category"),
			"uom": row.get("uom"),
			"total_closing_balance": _number(row.get("closing_balance")),
			"is_active": 1,
			"last_synced_at": now_datetime(),
		}
		for row in rows
	]


def _stock_group_roots(connection):
	rows = _fetch_all(
		connection,
		sql.SQL("select name, parent from {} where coalesce(name, '') != ''").format(_table("mst_stock_group")),
	)
	by_name = {row["name"]: row for row in rows}
	return {name: (_stock_group_path(name, by_name) or [name])[0] for name in by_name}


def _fetch_customer_ledgers(connection):
	rows = _fetch_all(
		connection,
		sql.SQL(
			"""
			select guid, name, alias
			from {}
			where coalesce(alias, '') != ''
			order by alias
			"""
		).format(_table("mst_ledger")),
	)
	return [
		{
			"client_code": row["alias"],
			"ledger_name": row["name"],
			"tally_guid": row.get("guid"),
			"is_active": 1,
			"last_synced_at": now_datetime(),
		}
		for row in rows
	]


def _fetch_stock_snapshots(connection, contract_version=None):
	columns = _table_columns(connection, STOCK_SNAPSHOT_TABLE)
	has_v2_identity = (
		contract_version == 2
		if contract_version is not None
		else STOCK_SNAPSHOT_V2_COLUMNS.issubset(columns)
	)
	if has_v2_identity:
		rows = _fetch_all(
			connection,
			sql.SQL(
				"""
				select
					max(snapshot.item) as item,
					max(snapshot.item_guid) as item_guid,
					max(snapshot.godown) as godown,
					max(snapshot.godown_guid) as godown_guid,
					sum(coalesce(snapshot.closing_qty, 0)) as quantity,
					max(snapshot.uom) as uom,
					max(snapshot.as_on_date) as as_on_date,
					max(snapshot.source_company) as source_company,
					max(snapshot.source_snapshot_id) as source_snapshot_id,
					max(snapshot.imported_at) as source_refreshed_at,
					max(master.name) as source_item_name,
					max(master.parent) as source_item_parent
				from {} snapshot
				left join {} master on master.guid = snapshot.item_guid
				where coalesce(snapshot.item, '') != ''
					and coalesce(snapshot.godown, '') != ''
				group by
					coalesce(nullif(btrim(snapshot.item_guid), ''), concat('name:', snapshot.item)),
					coalesce(nullif(btrim(snapshot.godown_guid), ''), concat('name:', snapshot.godown))
				"""
			).format(_table(STOCK_SNAPSHOT_TABLE), _table("mst_stock_item")),
		)
	else:
		rows = _fetch_all(
			connection,
			sql.SQL(
				"""
				select
					snapshot.item,
					snapshot.godown,
					snapshot.quantity,
					snapshot.uom,
					snapshot.as_on_date,
					snapshot.source_refreshed_at,
					master.name as source_item_name,
					master.parent as source_item_parent
				from (
					select
						item,
						godown,
						sum(coalesce(closing_qty, 0)) as quantity,
						max(uom) as uom,
						max(imported_at)::date as as_on_date,
						max(imported_at) as source_refreshed_at
					from {}
					where coalesce(item, '') != '' and coalesce(godown, '') != ''
					group by item, godown
				) snapshot
				left join {} master on master.name = snapshot.item
				"""
			).format(_table(STOCK_SNAPSHOT_TABLE), _table("mst_stock_item")),
		)

	return [
		{
			"item": row["item"],
			"item_guid": row.get("item_guid"),
			"godown": row["godown"],
			"godown_guid": row.get("godown_guid"),
			"quantity": _number(row.get("quantity")),
			"uom": row.get("uom"),
			"as_on_date": row.get("as_on_date"),
			"source_company": row.get("source_company"),
			"source_snapshot_id": row.get("source_snapshot_id"),
			"source_refreshed_at": row.get("source_refreshed_at"),
			"source_item_exists": bool(row.get("source_item_name")),
			"source_item_parent": row.get("source_item_parent"),
			"synced_at": now_datetime(),
		}
		for row in rows
	]


def _fetch_stock_snapshot_state(connection):
	if not _table_exists(connection, STOCK_SNAPSHOT_STATE_TABLE):
		return {"snapshot_complete": False, "contract_version": 1}
	rows = _fetch_all(
		connection,
		sql.SQL(
			"""
			select
				snapshot_id,
				source_company,
				as_on_date,
				refreshed_at as source_refreshed_at,
				raw_rows,
				accepted_rows,
				positive_rows,
				negative_rows,
				zero_rows,
				rejected_rows,
				snapshot_complete
			from {}
			where singleton = true
			limit 1
			"""
		).format(_table(STOCK_SNAPSHOT_STATE_TABLE)),
	)
	if not rows:
		return {"snapshot_complete": False, "contract_version": 2}
	state = dict(rows[0])
	state["source_refreshed_at"] = _frappe_datetime(state.get("source_refreshed_at"))
	state["contract_version"] = 2
	return state


def _frappe_datetime(value):
	if value is not None and getattr(value, "tzinfo", None) is not None:
		return convert_utc_to_system_timezone(value).replace(tzinfo=None)
	return value


def _fetch_stock_snapshot_integrity(connection, state):
	rows = _fetch_all(
		connection,
		sql.SQL(
			"""
			select
				count(*)::integer as stored_rows,
				count(*) filter (where closing_qty > 0)::integer as positive_rows,
				count(*) filter (where closing_qty < 0)::integer as negative_rows,
				count(*) filter (where closing_qty = 0)::integer as zero_rows,
				count(*) filter (
					where closing_qty is null
						or closing_qty::text in ('NaN', 'Infinity', '-Infinity')
				)::integer as invalid_quantity_rows,
				count(*) filter (
					where coalesce(btrim(item), '') = ''
						or coalesce(btrim(godown), '') = ''
						or row_type is distinct from 'GODOWN'
				)::integer as invalid_identity_rows,
				count(*) filter (
					where coalesce(btrim(item_guid), '') = ''
						or coalesce(btrim(godown_guid), '') = ''
				)::integer as missing_guid_rows,
				count(*) filter (
					where source_snapshot_id is distinct from %s
						or source_company is distinct from %s
						or as_on_date is distinct from %s
				)::integer as mismatched_metadata_rows
			from {}
			"""
		).format(_table(STOCK_SNAPSHOT_TABLE)),
		[state.get("snapshot_id"), state.get("source_company"), state.get("as_on_date")],
	)
	return dict(rows[0])


def _validate_stock_snapshot_contract(records, state, integrity=None):
	if not state.get("snapshot_complete"):
		return

	required_fields = ("snapshot_id", "source_company", "as_on_date", "source_refreshed_at")
	missing_fields = [
		fieldname
		for fieldname in required_fields
		if state.get(fieldname) is None
		or (isinstance(state.get(fieldname), str) and not state.get(fieldname).strip())
	]
	if missing_fields:
		frappe.throw(f"Complete Tally stock snapshot is missing metadata: {', '.join(missing_fields)}")
	if int(state.get("rejected_rows") or 0):
		frappe.throw("Complete Tally stock snapshot cannot contain rejected rows")
	if int(state.get("raw_rows") or 0) != int(state.get("accepted_rows") or 0) + int(
		state.get("rejected_rows") or 0
	):
		frappe.throw("Complete Tally stock snapshot row metrics are inconsistent")
	if int(state.get("accepted_rows") or 0) <= 0:
		frappe.throw("Complete Tally stock snapshot cannot be empty")

	if state.get("contract_version") == 2:
		if not integrity:
			frappe.throw("Complete Tally stock snapshot is missing its integrity summary")
		if int(integrity.get("stored_rows") or 0) != int(state.get("accepted_rows") or 0):
			frappe.throw("Tally stock snapshot stored row count does not match accepted_rows")
		for fieldname in ("positive_rows", "negative_rows", "zero_rows"):
			if int(integrity.get(fieldname) or 0) != int(state.get(fieldname) or 0):
				frappe.throw(f"Tally stock snapshot {fieldname} does not match stored rows")
		if int(integrity.get("invalid_quantity_rows") or 0):
			frappe.throw("Tally stock snapshot contains null quantities")
		if int(integrity.get("invalid_identity_rows") or 0):
			frappe.throw("Tally stock snapshot contains invalid item or godown names or row types")
		if int(integrity.get("mismatched_metadata_rows") or 0):
			frappe.throw("Tally stock snapshot rows do not match the published snapshot metadata")

	for record in records:
		missing_identity = [
			fieldname
			for fieldname in ("item", "godown")
			if record.get(fieldname) is None
			or (isinstance(record.get(fieldname), str) and not record.get(fieldname).strip())
		]
		if missing_identity:
			frappe.throw(f"Complete Tally stock row is missing identity fields: {', '.join(missing_identity)}")
		for record_field, state_field in (
			("source_snapshot_id", "snapshot_id"),
			("source_company", "source_company"),
			("as_on_date", "as_on_date"),
		):
			if str(record.get(record_field) or "") != str(state.get(state_field) or ""):
				frappe.throw(
					f"Tally stock row metadata does not match the complete snapshot state ({record_field})"
				)


def _build_dev_stock_snapshot_rows(
	items,
	godowns,
	max_godowns_per_item=3,
	zero_stock_ratio=0.2,
	as_on_date=None,
):
	if not items or not godowns:
		return []
	godown_names = [godown if isinstance(godown, str) else godown.get("name") for godown in godowns]
	godown_names = [godown for godown in godown_names if godown]
	if not godown_names:
		return []

	max_count = max(1, min(int(max_godowns_per_item or 1), len(godown_names)))
	zero_mod = _zero_stock_modulus(zero_stock_ratio)
	rows = []
	for item in items:
		item_name = item.get("name") if hasattr(item, "get") else item["name"]
		uom = (item.get("uom") if hasattr(item, "get") else item.get("uom")) or "PCS"
		seed = _stable_int(item_name)
		godown_count = (seed % max_count) + 1
		start = seed % len(godown_names)
		for offset in range(godown_count):
			godown = godown_names[(start + offset) % len(godown_names)]
			pair_seed = _stable_int(f"{item_name}:{godown}")
			quantity = 0 if zero_mod and pair_seed % zero_mod == 0 else (pair_seed % 250) + 1
			rows.append(
				{
					"item": item_name,
					"godown": godown,
					"quantity": quantity,
					"uom": uom,
					"as_on_date": as_on_date or nowdate(),
				}
			)
	return rows


def _stable_int(value):
	return int(hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12], 16)


def _zero_stock_modulus(ratio):
	try:
		ratio = float(ratio)
	except (TypeError, ValueError):
		return None
	if ratio <= 0:
		return None
	if ratio >= 1:
		return 1
	return max(2, round(1 / ratio))


def _chunks(values, size):
	for index in range(0, len(values), size):
		yield values[index : index + size]


def _fetch_vouchers(connection, limit=None):
	params = []
	limit_clause = sql.SQL("")
	if limit:
		params.append(int(limit))
		limit_clause = sql.SQL("limit %s")

	rows = _fetch_all(
		connection,
		sql.SQL(
			"""
			select
				v.guid,
				v.voucher_type,
				v.voucher_number,
				v.reference_number,
				v.party_name,
				v.date as voucher_date,
				l.alias as party_client_code,
				i.item,
				i._item as item_guid,
				i.godown,
				i._godown as godown_guid,
				i.quantity,
				i.tracking_number
			from {} v
			join {} i on i.guid = v.guid
			left join {} l on l.name = v.party_name
			where coalesce(v.voucher_number, '') != ''
				and coalesce(i.item, '') != ''
				and coalesce(i.godown, '') != ''
				and (
					v.voucher_type ilike 'Sales%%'
					or v.voucher_type ilike 'Delivery Challan%%'
				)
			order by v.date asc, v.voucher_number asc
			{}
			"""
		).format(_table("trn_voucher"), _table("trn_inventory"), _table("mst_ledger"), limit_clause),
		params,
	)
	vouchers = {}
	for row in rows:
		voucher_number = row["voucher_number"]
		voucher = vouchers.setdefault(
			voucher_number,
			{
				"voucher_type": _voucher_type(row["voucher_type"]),
				"voucher_number": voucher_number,
				"reference_number": row["reference_number"],
				"party_client_code": row.get("party_client_code") or row.get("party_name"),
				"tracking_number": row.get("tracking_number"),
				"voucher_date": row.get("voucher_date"),
				"lines": [],
			},
		)
		if row.get("tracking_number") and not voucher.get("tracking_number"):
			voucher["tracking_number"] = row.get("tracking_number")
		voucher["lines"].append(
			{
				"item": row["item"],
				"item_guid": row.get("item_guid"),
				"godown": row["godown"],
				"godown_guid": row.get("godown_guid"),
				"quantity": abs(_number(row.get("quantity"))),
				"tracking_number": row.get("tracking_number"),
			}
		)
	return list(vouchers.values())


def _voucher_type(raw_type):
	raw_type = raw_type or ""
	if raw_type.lower().startswith("delivery challan"):
		return "Delivery Challan"
	return "Sales Invoice"


def _number(value):
	if value in (None, ""):
		return 0
	if isinstance(value, Decimal):
		return float(value)
	try:
		return float(str(value).split()[0])
	except (InvalidOperation, TypeError, ValueError):
		return 0


def _serialize_run(run):
	result = {
		"run": run.name,
		"sync_type": run.sync_type,
		"status": run.status,
		"records_seen": run.records_seen,
		"records_processed": run.records_processed,
		"errors_count": run.errors_count,
	}
	for fieldname in (
		"negative_records",
		"zero_records",
		"records_zeroed",
		"source_refreshed_at",
		"source_as_on_date",
		"source_snapshot_id",
		"snapshot_complete",
	):
		if run.meta.has_field(fieldname):
			result[fieldname] = run.get(fieldname)
	return result
