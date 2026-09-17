"""End-to-end document tests against an isolated Frappe site."""

import json
import unittest
from uuid import uuid4

import frappe
from frappe.utils import now_datetime

from kunal_enterprises.cron.reconciliation import run_reconciliation
from kunal_enterprises.integrations.reconciliation_queue import (
	acknowledge_work,
	claim_work,
	enqueue_reference,
)
from kunal_enterprises.integrations.voucher_snapshot import apply_snapshot


class TestVoucherCorrections(unittest.TestCase):
	def setUp(self):
		self.prefix = uuid4().hex[:10]
		frappe.set_user("Administrator")
		frappe.conf.tally_source_company = "Test Company"
		frappe.conf.tally_fulfillment_voucher_type_guids = ["dispatch-type"]

		def create(doctype, **kwargs):
			return frappe.get_doc(dict(doctype=doctype, **kwargs)).insert(ignore_permissions=True)

		group = create("Tally Stock Group", group_name=self.prefix, is_root=1, is_active=1)
		self.item = create(
			"Tally Item",
			item_name=self.prefix,
			tally_guid="item-" + self.prefix,
			root_stock_group=group.name,
			is_active=1,
		)
		self.godown = create(
			"Tally Godown", godown_name=self.prefix, tally_guid="godown-" + self.prefix, is_active=1
		)
		ledger = create(
			"Tally Customer Ledger",
			client_code=self.prefix,
			ledger_name=self.prefix,
			tally_guid="party-" + self.prefix,
			is_active=1,
		)
		self.customer = create(
			"Customer",
			customer_name=self.prefix,
			business_legal_name=self.prefix,
			onboarding_source="Tally",
			status="Active",
			admin_approved=1,
			client_code=ledger.client_code,
		)
		self.order = create(
			"Order",
			portal_reference_number="KE-" + self.prefix,
			order_source="Customer",
			customer=self.customer.name,
			status="Placed",
			confirmation_datetime=now_datetime(),
			items=[
				dict(
					item=self.item.name,
					item_name_at_order=self.item.name,
					requested_quantity=10,
					pending_quantity=10,
					status="Placed",
				)
			],
		)
		self.payload = dict(
			guid="voucher-" + self.prefix,
			alterid=1,
			source_company="Test Company",
			type_guid="dispatch-type",
			voucher_type="Delivery Challan",
			voucher_number="DC-" + self.prefix,
			order_number=self.order.portal_reference_number,
			order_details=[dict(order_number=self.order.portal_reference_number, order_date=None)],
			party_guid=ledger.tally_guid,
			voucher_date="20260905",
			lines=[
				dict(
					item_guid=self.item.tally_guid,
					godown_guid=self.godown.tally_guid,
					quantity=-4,
					tracking_number=self.prefix,
				)
			],
		)
		frappe.db.commit()

	def set_source_order(self, number):
		self.payload["order_number"] = number
		self.payload["order_details"] = [dict(order_number=number, order_date=None)] if number else []

	def test_unknown_order_extraction_preserves_accepted_quantity(self):
		self.publish()
		self.payload.update(order_number=None, order_details=None)
		self.payload["lines"][0]["quantity"] = -8
		self.publish()
		self.assertEqual(self.order.status, "Manual Review")
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)

	def test_reference_number_is_not_a_fallback(self):
		self.set_source_order(None)
		self.payload["reference_number"] = self.order.portal_reference_number
		self.publish()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 0)

	def test_multiple_orders_hold_every_candidate(self):
		self.publish()
		other = frappe.copy_doc(self.order)
		other.portal_reference_number = "MULTI-" + self.prefix
		other.items[0].fulfilled_quantity = 0
		other.status = "Placed"
		other.insert(ignore_permissions=True)
		self.payload.update(order_number=None, order_details=[
			dict(order_number=self.order.portal_reference_number, order_date=None),
			dict(order_number=other.portal_reference_number, order_date=None),
		])
		self.publish()
		other.reload()
		self.assertEqual(self.order.status, "Manual Review")
		self.assertEqual(other.status, "Manual Review")
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)
		self.assertEqual(other.items[0].fulfilled_quantity, 0)

	def publish(self, rows=None):
		# Include other tests' source rows so each observation includes the other test vouchers.
		rows = [self.payload] if rows is None else rows
		existing = frappe.get_all(
			"Tally Voucher",
			filters={"source_company": "Test Company"},
			fields=["tally_guid", "raw_source_payload"],
		)
		other = [
			json.loads(v.raw_source_payload)
			for v in existing
			if not v.tally_guid.endswith(self.prefix) and v.raw_source_payload
		]
		rows = other + rows
		apply_snapshot(
			dict(
				read_complete=True,
				source_kind="postgres_mirror",
				source_company="Test Company",
				snapshot_id=uuid4().hex,
				completed_at=now_datetime(),
				voucher_count=len(rows),
			),
			rows,
		)
		self.order.reload()
		return frappe.get_doc("Tally Voucher", {"tally_guid": self.payload["guid"]})

	def test_correction_renumbering_and_missing_header(self):
		voucher = self.publish()
		original_name = voucher.name
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)
		self.payload["lines"][0]["quantity"] = -10
		self.payload["alterid"] = 2
		self.payload["voucher_number"] = "NEW-" + self.prefix
		self.assertEqual(self.publish().name, original_name)
		self.assertEqual(self.order.status, "Completed")
		self.publish()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 10)
		self.payload["lines"][0]["quantity"] = -5
		self.payload["alterid"] = 3
		self.publish()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 5)
		self.publish([])
		self.assertEqual(self.order.items[0].fulfilled_quantity, 5)
		self.assertEqual(self.order.status, "Manual Review")
		self.assertEqual(frappe.get_doc("Tally Voucher", original_name).source_status, "Unverified")

	def test_wrong_customer_and_overquantity_recover_automatically(self):
		self.payload["party_guid"] = "wrong"
		self.publish()
		self.assertEqual(self.order.status, "Manual Review")
		self.payload["party_guid"] = "party-" + self.prefix
		self.payload["alterid"] = 2
		self.publish()
		self.assertEqual(self.order.status, "Partially Processed")
		self.payload["lines"][0]["quantity"] = -12
		self.payload["alterid"] = 3
		self.publish()
		self.assertEqual(self.order.status, "Manual Review")
		self.payload["lines"][0]["quantity"] = -10
		self.payload["alterid"] = 4
		self.publish()
		self.assertEqual(self.order.status, "Completed")

	def test_missing_inventory_preserves_order(self):
		self.publish()
		self.payload["lines"] = []
		self.publish()
		self.assertEqual(self.order.status, "Manual Review")
		self.order.reload()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)

	def test_reference_change_updates_both_orders(self):
		self.publish()
		other = frappe.copy_doc(self.order)
		other.portal_reference_number = "OTHER-" + self.prefix
		other.items[0].fulfilled_quantity = 0
		other.status = "Placed"
		other.insert(ignore_permissions=True)
		self.set_source_order(other.portal_reference_number)
		self.payload["alterid"] = 2
		self.publish()
		other.reload()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 0)
		self.assertEqual(other.items[0].fulfilled_quantity, 4)

	def test_cancelled_order_stays_cancelled(self):
		self.publish()
		self.order.status = "Cancelled"
		self.order.cancellation_reason = "Duplicate order cancelled by Owner"
		self.order.save(ignore_permissions=True)
		self.payload["lines"][0]["quantity"] = -6
		self.payload["alterid"] = 2
		self.publish()
		self.order.reload()
		self.assertEqual(self.order.status, "Cancelled")
		self.assertEqual(self.order.cancellation_reason, "Duplicate order cancelled by Owner")

	def test_new_entry_accumulates_and_invoice_is_ignored(self):
		from copy import deepcopy

		self.publish()
		second = deepcopy(self.payload)
		second["guid"] = "second-" + self.prefix
		second["voucher_number"] = "DC2-" + self.prefix
		second["lines"][0]["quantity"] = -6
		second["lines"][0]["tracking_number"] = "second-" + self.prefix
		self.publish([self.payload, second])
		self.assertEqual(self.order.status, "Completed")
		invoice = deepcopy(second)
		invoice["guid"] = "invoice-" + self.prefix
		invoice["type_guid"] = "invoice-type"
		self.publish([self.payload, second, invoice])
		self.assertEqual(self.order.items[0].fulfilled_quantity, 10)

	def test_extra_item_correction_and_missing_header(self):
		self.payload["lines"][0]["item_guid"] = "unknown-item"
		self.publish()
		self.assertEqual(self.order.status, "Manual Review")
		self.payload["lines"][0]["item_guid"] = self.item.tally_guid
		self.payload["alterid"] = 2
		self.publish()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)
		self.publish([])
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)

	def test_same_number_different_guids_do_not_overwrite(self):
		from copy import deepcopy

		second = deepcopy(self.payload)
		second["guid"] = "other-" + self.prefix
		second["lines"][0]["tracking_number"] = "other-" + self.prefix
		self.publish([self.payload, second])
		self.assertEqual(
			frappe.db.count("Tally Voucher", {"voucher_number": self.payload["voucher_number"]}), 2
		)
		self.assertEqual(self.order.items[0].fulfilled_quantity, 8)

	def test_source_revision_change_is_kept_in_history(self):
		voucher = self.publish()
		self.payload["lines"][0]["quantity"] = -5
		self.payload["alterid"] = 2
		previous = frappe.flags.in_test
		try:
			frappe.flags.in_test = False  # Frappe disables Version records during tests.
			self.publish()
		finally:
			frappe.flags.in_test = previous
		self.assertGreater(
			frappe.db.count("Version", {"ref_doctype": "Tally Voucher", "docname": voucher.name}), 0
		)

	def test_missing_reference_recovers_and_missing_voucher_can_return(self):
		self.set_source_order(None)
		voucher = self.publish()
		self.assertEqual(voucher.reconciliation_state, "Unmatched")
		self.set_source_order(self.order.portal_reference_number)
		self.payload["alterid"] = 2
		self.publish()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)

	def test_repeated_null_order_outcome_does_not_duplicate_audit_log(self):
		self.set_source_order(None)
		voucher = self.publish()
		before = len(
			[
				row
				for row in frappe.get_all(
					"Order Reconciliation Log", filters={"voucher": voucher.name}, fields=["order"]
				)
				if not row.order
			]
		)
		self.assertEqual(before, 1)

		self.publish()

		after = len(
			[
				row
				for row in frappe.get_all(
					"Order Reconciliation Log", filters={"voucher": voucher.name}, fields=["order"]
				)
				if not row.order
			]
		)
		self.assertEqual(after, before)
		self.publish([])
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)
		self.publish()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)

	def test_partial_closure_survives_missing_source(self):
		self.publish()
		self.order.status = "Partially Closed"
		self.order.save(ignore_permissions=True)
		self.publish([])
		self.assertEqual(self.order.status, "Partially Closed")
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)

	def test_reconciliation_failure_rolls_back_source_changes(self):
		from unittest.mock import patch

		voucher = self.publish()
		self.payload["alterid"] = 2
		self.payload["lines"][0]["quantity"] = -10
		with patch(
			"kunal_enterprises.cron.reconciliation._run_reconciliation",
			side_effect=RuntimeError("test failure"),
		):
			with self.assertRaises(RuntimeError):
				self.publish()
		voucher.reload()
		self.order.reload()
		self.assertEqual(voucher.source_alterid, 1)
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)

	def test_unmapped_legacy_contribution_is_not_silently_erased(self):
		self.publish()
		frappe.get_doc(
			dict(
				doctype="Tally Voucher",
				voucher_number="legacy-" + self.prefix,
				voucher_type="Sales Invoice",
				reference_number=self.order.portal_reference_number,
				reconciled=1,
			)
		).insert(ignore_permissions=True)
		self.publish([])
		self.assertEqual(self.order.status, "Manual Review")
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)

	def test_missing_inventory_reference_change_holds_both_orders_until_recovery(self):
		self.publish()
		other = frappe.copy_doc(self.order)
		other.portal_reference_number = "SECOND-" + self.prefix
		other.items[0].fulfilled_quantity = 0
		other.status = "Placed"
		other.insert(ignore_permissions=True)
		lines = self.payload["lines"]
		self.payload["lines"] = []
		self.set_source_order(other.portal_reference_number)
		self.publish()
		other.reload()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)
		self.assertEqual(other.items[0].fulfilled_quantity, 0)
		self.assertEqual(other.status, "Manual Review")
		voucher_name = frappe.db.get_value("Tally Voucher", {"tally_guid": self.payload["guid"]}, "name")
		logged_orders = set(
			frappe.get_all(
				"Order Reconciliation Log",
				filters={"voucher": voucher_name},
				pluck="order",
			)
		)
		self.assertTrue({self.order.name, other.name} <= logged_orders)
		self.payload["lines"] = lines
		self.publish()
		other.reload()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 0)
		self.assertEqual(other.items[0].fulfilled_quantity, 4)

	def test_completed_order_missing_header_preserves_total_and_recovers(self):
		self.payload["lines"][0]["quantity"] = -10
		self.publish()
		self.assertEqual(self.order.status, "Completed")
		self.publish([])
		self.assertEqual(self.order.status, "Manual Review")
		self.assertEqual(self.order.items[0].fulfilled_quantity, 10)
		self.payload["lines"][0]["quantity"] = -7
		self.publish()
		self.assertEqual(self.order.status, "Partially Processed")
		self.assertEqual(self.order.items[0].fulfilled_quantity, 7)

	def test_same_revision_inventory_correction_is_applied(self):
		self.publish()
		self.payload["lines"][0]["quantity"] = -6
		self.publish()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 6)

	def test_missing_quantity_preserves_previous_contribution(self):
		self.publish()
		self.payload["lines"][0]["quantity"] = None
		self.publish()
		self.assertEqual(self.order.status, "Manual Review")
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)
		self.payload["lines"][0]["quantity"] = -6
		self.publish()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 6)

	def _audit_legacy(self):
		legacy = frappe.get_doc(
			dict(
				doctype="Tally Voucher",
				voucher_number=self.payload["voucher_number"],
				voucher_type="Delivery Challan",
				reference_number=self.order.portal_reference_number,
				party_client_code=self.prefix,
				reconciled=1,
				lines=[dict(item=self.item.name, godown=self.godown.name, quantity=4)],
			)
		).insert(ignore_permissions=True)
		self.order.items[0].fulfilled_quantity = 4
		self.order.status = "Partially Processed"
		self.order.save(ignore_permissions=True)
		return legacy

	def test_legacy_is_not_adopted_and_preserves_fulfillment(self):
		legacy = self._audit_legacy()
		original_lines = self.payload["lines"]
		self.payload["lines"] = []
		self.publish()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)
		self.assertEqual(self.order.status, "Manual Review")
		self.payload["lines"] = original_lines
		voucher = self.publish()
		self.assertNotEqual(voucher.name, legacy.name)
		legacy.reload()
		self.assertFalse(legacy.tally_guid)
		self.assertEqual(self.order.status, "Manual Review")
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)

	def test_ambiguous_source_guids_do_not_adopt_one_legacy_voucher(self):
		from copy import deepcopy

		legacy = self._audit_legacy()
		second = deepcopy(self.payload)
		second["guid"] = "second-" + self.prefix
		second["lines"][0]["tracking_number"] = "second-" + self.prefix
		self.publish([self.payload, second])
		legacy.reload()
		self.assertFalse(legacy.tally_guid)
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)
		self.assertEqual(self.order.status, "Manual Review")

	def test_reference_move_cannot_duplicate_frozen_fulfillment(self):
		from copy import deepcopy

		second = deepcopy(self.payload)
		second["guid"] = "second-" + self.prefix
		second["lines"][0]["tracking_number"] = "second-" + self.prefix
		self.publish([self.payload, second])
		other = frappe.copy_doc(self.order)
		other.portal_reference_number = "OTHER-" + self.prefix
		other.items[0].fulfilled_quantity = 0
		other.status = "Placed"
		other.insert(ignore_permissions=True)
		second_lines = second["lines"]
		second["lines"] = []
		self.set_source_order(other.portal_reference_number)
		for _ in range(2):
			self.publish([self.payload, second])
			other.reload()
			self.assertEqual(self.order.items[0].fulfilled_quantity, 8)
			self.assertEqual(other.items[0].fulfilled_quantity, 0)
			self.assertEqual(other.status, "Manual Review")
		second["lines"] = second_lines
		self.publish([self.payload, second])
		other.reload()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)
		self.assertEqual(other.items[0].fulfilled_quantity, 4)

	def test_unchanged_payload_refreshes_derived_ledger_mapping(self):
		self.payload["party_guid"] = "new-party-" + self.prefix
		voucher = self.publish()
		self.assertFalse(voucher.party_client_code)
		frappe.get_doc(
			dict(
				doctype="Tally Customer Ledger",
				client_code="new-" + self.prefix,
				ledger_name="New " + self.prefix,
				tally_guid=self.payload["party_guid"],
				is_active=1,
			)
		).insert(ignore_permissions=True)
		voucher = self.publish()
		self.assertEqual(voucher.party_client_code, "new-" + self.prefix)

	def test_multi_hop_reference_transfer_releases_all_orders_on_recovery(self):
		from copy import deepcopy

		second = deepcopy(self.payload)
		second["guid"] = "second-" + self.prefix
		second["lines"][0]["tracking_number"] = "second-" + self.prefix
		self.publish([self.payload, second])
		others = []
		for index in range(2):
			other = frappe.copy_doc(self.order)
			other.portal_reference_number = f"HOP-{index}-{self.prefix}"
			other.items[0].fulfilled_quantity = 0
			other.status = "Placed"
			other.insert(ignore_permissions=True)
			others.append(other)
		accepted = second["lines"]
		second["lines"] = []
		for other in others:
			self.set_source_order(other.portal_reference_number)
			self.publish([self.payload, second])
			for pending in others:
				pending.reload()
				self.assertEqual(pending.items[0].fulfilled_quantity, 0)
			self.assertEqual(self.order.items[0].fulfilled_quantity, 8)
		second["lines"] = accepted
		voucher = self.publish([self.payload, second])
		for other in others:
			other.reload()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)
		self.assertEqual(others[0].items[0].fulfilled_quantity, 0)
		self.assertEqual(others[1].items[0].fulfilled_quantity, 4)
		self.assertEqual(voucher.source_pending_references, "[]")

	def test_incremental_engine_runs_full_once_then_processes_only_changes(self):
		previous = frappe.conf.get("tally_incremental_reconciliation_enabled")
		try:
			frappe.conf.tally_incremental_reconciliation_enabled = True
			latest_run = frappe.db.get_value(
				"Tally Sync Run",
				{"sync_type": "Reconciliation"},
				"name",
				order_by="creation desc, name desc",
			)
			if latest_run:
				frappe.db.set_value("Tally Sync Run", latest_run, "source_metadata", "{}")
			self.publish()
			first = json.loads(
				frappe.db.get_value(
					"Tally Sync Run",
					{"sync_type": "Reconciliation"},
					"source_metadata",
					order_by="creation desc, name desc",
				)
			)
			self.assertEqual(first["mode"], "full")

			self.publish()
			unchanged = json.loads(
				frappe.db.get_value(
					"Tally Sync Run",
					{"sync_type": "Reconciliation"},
					"source_metadata",
					order_by="creation desc, name desc",
				)
			)
			self.assertEqual(unchanged["mode"], "incremental")
			self.assertEqual(unchanged["scoped_vouchers"], 0)

			self.payload["lines"][0]["quantity"] = -6
			self.publish()
			changed = json.loads(
				frappe.db.get_value(
					"Tally Sync Run",
					{"sync_type": "Reconciliation"},
					"source_metadata",
					order_by="creation desc, name desc",
				)
			)
			self.assertEqual(changed["mode"], "incremental")
			self.assertGreaterEqual(changed["scoped_vouchers"], 1)
			self.assertEqual(self.order.items[0].fulfilled_quantity, 6)

			safety = run_reconciliation(mode="full")
			safety_metadata = json.loads(safety.source_metadata)
			self.assertEqual(safety_metadata["mode"], "full")
			self.assertEqual(safety_metadata["full_safety_changes_detected"], 0)
		finally:
			frappe.conf.tally_incremental_reconciliation_enabled = previous

	def test_newer_work_generation_cannot_be_acknowledged_by_an_older_claim(self):
		previous = frappe.conf.get("tally_incremental_reconciliation_enabled")
		key = None
		try:
			frappe.conf.tally_incremental_reconciliation_enabled = True
			key = enqueue_reference(self.order.portal_reference_number, "first")
			enqueue_reference(self.order.portal_reference_number, "second")
			claimed, problem = claim_work("Test Company")
			claimed = [row for row in claimed if row.name == key]
			self.assertIsNone(problem)
			self.assertEqual(claimed[0].generation, 2)

			enqueue_reference(self.order.portal_reference_number, "newer")
			acknowledge_work(claimed)
			self.assertEqual(
				frappe.db.get_value("Tally Reconciliation Work Item", key, "generation"),
				3,
			)
		finally:
			if key:
				frappe.db.delete("Tally Reconciliation Work Item", {"name": key})
			frappe.conf.tally_incremental_reconciliation_enabled = previous

	def test_reference_transfer_respects_unmapped_legacy_hold(self):
		legacy = self._audit_legacy()
		# Prevent adoption while retaining an existing fulfilled contribution.
		legacy.voucher_number = "unmapped-" + self.prefix
		legacy.save(ignore_permissions=True)
		self.publish()
		other = frappe.copy_doc(self.order)
		other.portal_reference_number = "OTHER-" + self.prefix
		other.items[0].fulfilled_quantity = 0
		other.status = "Placed"
		other.insert(ignore_permissions=True)
		self.set_source_order(other.portal_reference_number)
		self.publish()
		other.reload()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)
		self.assertEqual(other.items[0].fulfilled_quantity, 0)
		self.assertEqual(other.status, "Manual Review")

	def test_stale_transaction_cannot_overwrite_newer_reconciliation(self):
		self.publish()
		# Pin a repeatable-read view before a second worker commits a newer run.
		latest = frappe.db.get_value(
			"Tally Sync Run",
			{"source_table": "trn_voucher", "sync_type": "Reconciliation"},
			"name",
			order_by="creation desc, name desc",
		)
		connection = frappe.db._get_connection()
		try:
			with connection.cursor() as cursor:
				cursor.execute(
					"""INSERT INTO `tabTally Sync Run`
				(name, creation, modified, sync_type, status, source_table)
				VALUES (%s, %s, %s, 'Reconciliation', 'Completed', 'trn_voucher')""",
					("concurrent-" + self.prefix, now_datetime(), now_datetime()),
				)
			connection.commit()
		finally:
			connection.close()
		self.assertEqual(
			frappe.db.get_value(
				"Tally Sync Run",
				{"source_table": "trn_voucher", "sync_type": "Reconciliation"},
				"name",
				order_by="creation desc, name desc",
			),
			latest,
		)
		self.order.db_set("sales_employee_note", "uncommitted audit marker", commit=False)
		with self.assertRaisesRegex(frappe.ValidationError, "fresh transaction"):
			run_reconciliation(commit=False)
		with self.assertRaisesRegex(frappe.ValidationError, "fresh transaction"):
			self.publish()
		# Rejection must preserve, without committing, the caller's pending work.
		self.assertEqual(
			frappe.db.get_value("Order", self.order.name, "sales_employee_note"), "uncommitted audit marker"
		)
		frappe.db.rollback()
		self.assertNotEqual(
			frappe.db.get_value("Order", self.order.name, "sales_employee_note"), "uncommitted audit marker"
		)
		run_reconciliation()
		self.order.reload()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)


class TestIncrementalVoucherCorrections(TestVoucherCorrections):
	"""Run the complete correction suite through the feature-flagged bulk engine."""

	def setUp(self):
		super().setUp()
		self._previous_incremental_setting = frappe.conf.get("tally_incremental_reconciliation_enabled")
		frappe.conf.tally_incremental_reconciliation_enabled = True

	def tearDown(self):
		frappe.conf.tally_incremental_reconciliation_enabled = self._previous_incremental_setting
