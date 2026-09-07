"""Read existing loader tables only. Missing rows are observations, never deletions."""

from uuid import uuid4

from psycopg2 import sql

from kunal_enterprises.integrations.voucher_contract import validate_sync_metadata


def read_mirror(connection, company):
	from frappe.utils import now_datetime

	from kunal_enterprises.integrations.tally_postgres import _fetch_all, _table

	# Order observations by read start, so a slow older read cannot overwrite a newer one.
	observed_at = now_datetime()
	connection.set_session(readonly=True, isolation_level="REPEATABLE READ")
	from kunal_enterprises.integrations.tally_postgres import _table_columns
	if not {"order_details", "order_number"} <= _table_columns(connection, "trn_voucher"):
		raise ValueError("Apply the loader PostgreSQL voucher order-details migration before importing")
	config = {
		r["name"]: r["value"]
		for r in _fetch_all(connection, sql.SQL("select name,value from {}").format(_table("config")))
	}
	latest = _fetch_all(
		connection,
		sql.SQL("select id,status from {} where operation='sync' order by id desc limit 1").format(
			_table("sync_run_ping")
		),
	)
	completed = _fetch_all(
		connection,
		sql.SQL("""select id,finished_at from {} where operation='sync'
		and status='success' and message like 'Import completed successfully.%%'
		order by id desc limit 1""").format(_table("sync_run_ping")),
	)
	failures = _fetch_all(
		connection,
		sql.SQL("select max(id) as id from {} where operation='sync' and status='failure'").format(
			_table("sync_run_ping")
		),
	)
	marker = validate_sync_metadata(
		config,
		latest[0] if latest else None,
		completed[0] if completed else None,
		failures[0]["id"] if failures else None,
		company,
	)
	# Keep every header, including those with no inventory or no order number.
	headers = _fetch_all(
		connection,
		sql.SQL("""select v.guid,v.alterid,v._voucher_type as type_guid,
		v.voucher_type,v.voucher_number,v.order_number,v.order_details,v._party_name as party_guid,
		v.party_name,v.date as voucher_date,l.alias as party_client_code
		from {} v left join {} l on l.guid=v._party_name order by v.guid""").format(
			_table("trn_voucher"), _table("mst_ledger")
		),
	)
	inventory = _fetch_all(
		connection,
		sql.SQL("""select guid,_item as item_guid,_godown as godown_guid,
		quantity,tracking_number from {} order by guid,_item,_godown,tracking_number,quantity""").format(
			_table("trn_inventory")
		),
	)
	lines = {}
	for row in inventory:
		lines.setdefault(row["guid"], []).append({k: v for k, v in row.items() if k != "guid"})
	for row in headers:
		if row["alterid"] is None or row["alterid"] > marker:
			raise ValueError("Voucher headers are newer than the completed inventory checkpoint")
		row.update(source_company=company, lines=lines.get(row["guid"], []))
	return dict(
		source_kind="postgres_mirror",
		read_complete=True,
		source_company=company,
		snapshot_id=uuid4().hex,
		completed_at=observed_at,
		voucher_count=len(headers),
		loader_run_id=completed[0]["id"],
		loader_finished_at=str(completed[0]["finished_at"]),
		period_from=config["Period From"],
		period_to=config["Period To"],
	), headers
