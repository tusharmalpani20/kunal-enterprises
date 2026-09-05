"""Read-only importer tests using original loader tables in an isolated PostgreSQL schema."""

import os
import unittest
from uuid import uuid4

import frappe
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from kunal_enterprises.integrations.voucher_mirror import read_mirror
from kunal_enterprises.integrations.voucher_snapshot import import_snapshot


@unittest.skipUnless(os.environ.get("KUNAL_TEST_PG_DSN"), "Requires a disposable PostgreSQL database")
class TestVoucherMirror(unittest.TestCase):
	def setUp(self):
		self.schema = "mirror_test_" + uuid4().hex
		self.writer = psycopg2.connect(os.environ["KUNAL_TEST_PG_DSN"])
		self.writer.autocommit = True
		self.reader = psycopg2.connect(os.environ["KUNAL_TEST_PG_DSN"], cursor_factory=RealDictCursor)
		self.saved = {
			key: frappe.conf.get(key)
			for key in (
				"tally_postgres_host",
				"tally_postgres_dbname",
				"tally_postgres_user",
				"tally_postgres_password",
				"tally_postgres_schema",
			)
		}
		frappe.conf.update(
			tally_postgres_host="test",
			tally_postgres_dbname="test",
			tally_postgres_user="test",
			tally_postgres_password="test",
			tally_postgres_schema=self.schema,
		)
		self.execute(sql.SQL("create schema {}").format(sql.Identifier(self.schema)))
		self.execute(sql.SQL("set search_path to {}").format(sql.Identifier(self.schema)))
		self.execute("""create table config(name text,value text);
		 create table sync_run_ping(id integer,operation text,status text,finished_at timestamptz,message text);
		 create table mst_ledger(guid text,alias text);
		 create table trn_voucher(guid text,alterid integer,_voucher_type text,voucher_type text,voucher_number text,
		 reference_number text,_party_name text,party_name text,date date);
		 create table trn_inventory(guid text,_item text,_godown text,quantity numeric,tracking_number text);
		 insert into config values ('Company Name','Test Company'),('Period From','2024-04-01'),('Period To','2027-03-31'),
		 ('Last AlterID Transaction','10'),('Last Voucher Inventory AlterID','10');
		 insert into sync_run_ping values(1,'sync','success',now(),'Import completed successfully. trn_inventory=1.');
		 insert into mst_ledger values('party','ALIAS');
		 insert into trn_voucher values('voucher',10,'dispatch-type','Delivery Challan','DC1','KE-X','party','Old name','2026-09-05');
		 insert into trn_inventory values('voucher','item','godown',-4,'track');""")

	def execute(self, query, args=None):
		with self.writer.cursor() as cursor:
			cursor.execute(query, args)

	def tearDown(self):
		self.reader.close()
		self.execute(sql.SQL("drop schema {} cascade").format(sql.Identifier(self.schema)))
		self.writer.close()
		frappe.conf.update(self.saved)

	def read(self):
		self.reader.rollback()
		return read_mirror(self.reader, "Test Company")

	def test_existing_schema_reads_identity_signed_quantity_and_ledger_guid(self):
		state, rows = self.read()
		self.assertTrue(state["read_complete"])
		self.assertEqual(rows[0]["party_client_code"], "ALIAS")
		self.assertEqual(rows[0]["party_guid"], "party")
		self.assertEqual(rows[0]["lines"][0]["quantity"], -4)
		self.assertEqual(self.reader.readonly, True)

	def test_header_survives_missing_inventory_and_reference(self):
		self.execute("delete from trn_inventory; update trn_voucher set reference_number='' ")
		state, rows = self.read()
		self.assertEqual(state["voucher_count"], 1)
		self.assertEqual(rows[0]["lines"], [])
		self.assertEqual(rows[0]["reference_number"], "")

	def test_no_change_after_failed_sync_is_rejected_and_failure_logged(self):
		self.execute(
			"insert into sync_run_ping values(2,'sync','failure',now(),'Import failed.'),(3,'sync','success',now(),'No change in Tally data found.')"
		)
		with self.assertRaises(ValueError):
			import_snapshot(self.reader)
		self.assertTrue(
			frappe.db.exists(
				"Tally Sync Run", {"sync_type": "Vouchers", "status": "Failed", "source_table": "trn_voucher"}
			)
		)
		self.execute(
			"insert into sync_run_ping values(4,'sync','success',now(),'Import completed successfully. trn_inventory=1.')"
		)
		self.assertEqual(self.read()[0]["loader_run_id"], 4)

	def test_newer_headers_or_inventory_lag_reject(self):
		self.execute("update trn_voucher set alterid=11")
		with self.assertRaises(ValueError):
			self.read()
		self.execute(
			"update trn_voucher set alterid=10; update config set value='9' where name='Last Voucher Inventory AlterID'"
		)
		with self.assertRaises(ValueError):
			self.read()

	def test_reader_does_not_see_mid_read_commits(self):
		from unittest.mock import patch

		from kunal_enterprises.integrations.tally_postgres import _fetch_all

		def fetch(connection, query, params=None):
			rows = _fetch_all(connection, query, params)
			if "from" in query.as_string(connection) and "trn_voucher" in query.as_string(connection):
				self.execute("update trn_inventory set quantity=-8")
			return rows

		with patch("kunal_enterprises.integrations.tally_postgres._fetch_all", side_effect=fetch):
			self.assertEqual(self.read()[1][0]["lines"][0]["quantity"], -4)
		self.assertEqual(self.read()[1][0]["lines"][0]["quantity"], -8)

	def test_existing_tables_import_updates_same_record_and_holds_missing_header(self):
		key = uuid4().hex
		frappe.set_user("Administrator")
		group = frappe.get_doc(
			dict(doctype="Tally Stock Group", group_name=key, is_root=1, is_active=1)
		).insert(ignore_permissions=True)
		frappe.get_doc(
			dict(
				doctype="Tally Item",
				item_name=key,
				tally_guid="item-" + key,
				root_stock_group=group.name,
				is_active=1,
			)
		).insert(ignore_permissions=True)
		frappe.get_doc(
			dict(doctype="Tally Godown", godown_name=key, tally_guid="godown-" + key, is_active=1)
		).insert(ignore_permissions=True)
		self.execute("update trn_voucher set guid=%s", [key])
		self.execute(
			"update trn_inventory set guid=%s,_item=%s,_godown=%s", [key, "item-" + key, "godown-" + key]
		)
		result = import_snapshot(self.reader)
		voucher = frappe.get_doc("Tally Voucher", {"tally_guid": key})
		self.assertEqual(voucher.source_status, "Active")
		self.assertEqual(voucher.lines[0].quantity, -4)
		self.assertFalse(frappe.get_doc("Tally Sync Run", result["run"]).snapshot_complete)
		self.reader.rollback()
		self.execute("update trn_inventory set quantity=-6")
		import_snapshot(self.reader)
		voucher.reload()
		self.assertEqual(voucher.lines[0].quantity, -6)
		self.reader.rollback()
		self.execute("delete from trn_voucher")
		import_snapshot(self.reader)
		voucher.reload()
		self.assertEqual(voucher.source_status, "Unverified")
		self.assertEqual(voucher.lines[0].quantity, -6)

	def test_observation_time_is_taken_before_database_snapshot(self):
		from unittest.mock import patch

		from frappe.utils import now_datetime

		from kunal_enterprises.integrations.tally_postgres import _fetch_all

		events = []

		def clock():
			events.append("clock")
			return now_datetime()

		def fetch(*args, **kwargs):
			events.append("read")
			return _fetch_all(*args, **kwargs)

		with (
			patch("frappe.utils.now_datetime", side_effect=clock),
			patch("kunal_enterprises.integrations.tally_postgres._fetch_all", side_effect=fetch),
		):
			self.read()
		self.assertEqual(events[0], "clock")
