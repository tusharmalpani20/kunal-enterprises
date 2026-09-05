"""End-to-end document tests against an isolated Frappe site."""

import json
import unittest
from uuid import uuid4

import frappe
from frappe.utils import now_datetime

from kunal_enterprises.cron.reconciliation import run_reconciliation
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
			reference_number=self.order.portal_reference_number,
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
		self.payload["reference_number"] = other.portal_reference_number
		self.payload["alterid"] = 2
		self.publish()
		other.reload()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 0)
		self.assertEqual(other.items[0].fulfilled_quantity, 4)

	def test_cancelled_order_stays_cancelled(self):
		self.publish()
		self.order.status = "Cancelled"
		self.order.save(ignore_permissions=True)
		self.payload["lines"][0]["quantity"] = -6
		self.payload["alterid"] = 2
		self.publish()
		self.assertEqual(self.order.status, "Cancelled")

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
		self.payload["reference_number"] = ""
		voucher = self.publish()
		self.assertEqual(voucher.reconciliation_state, "Unmatched")
		self.payload["reference_number"] = self.order.portal_reference_number
		self.payload["alterid"] = 2
		self.publish()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)
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
		self.payload["reference_number"] = other.portal_reference_number
		self.publish()
		other.reload()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)
		self.assertEqual(other.items[0].fulfilled_quantity, 0)
		self.assertEqual(other.status, "Manual Review")
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

	def test_legacy_adoption_with_missing_inventory_preserves_fulfillment(self):
		legacy = self._audit_legacy()
		original_lines = self.payload["lines"]
		self.payload["lines"] = []
		self.publish()
		self.assertEqual(self.order.items[0].fulfilled_quantity, 4)
		self.assertEqual(self.order.status, "Manual Review")
		self.payload["lines"] = original_lines
		voucher = self.publish()
		self.assertEqual(voucher.name, legacy.name)
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
		self.payload["reference_number"] = other.portal_reference_number
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
			self.payload["reference_number"] = other.portal_reference_number
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
		self.payload["reference_number"] = other.portal_reference_number
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
