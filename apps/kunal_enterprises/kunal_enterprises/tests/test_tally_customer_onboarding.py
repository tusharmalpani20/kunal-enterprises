from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.api.orders import submit_order
from kunal_enterprises.api.sales_employees import allowed_customers
from kunal_enterprises.cron.tally_sync import (
	get_tally_customer_onboarding_preview,
	sync_tally_masters,
)
from kunal_enterprises.integrations.tally_postgres import _build_ledger_group_paths
from kunal_enterprises.kunal_enterprises.doctype.customer.customer import (
	get_active_tally_client_codes,
	get_customer_access_checklist,
	has_sales_employee_order_access,
)


class TestTallyCustomerOnboarding(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_tally_group_path_builder_resolves_nested_groups_and_rejects_bad_graphs(self):
		paths, errors = _build_ledger_group_paths(
			[
				{"name": "Current Asset", "parent": None},
				{"name": "Sundary Debtors", "parent": "Current Asset"},
				{"name": "SHIVA NEW", "parent": "Sundary Debtors"},
				{"name": "Shiva Interior", "parent": "SHIVA NEW"},
			]
		)
		self.assertEqual(paths["shiva interior"], ["Current Asset", "Sundary Debtors", "SHIVA NEW", "Shiva Interior"])
		self.assertFalse(errors)

		_, cycle_errors = _build_ledger_group_paths(
			[{"name": "Cycle A", "parent": "Cycle B"}, {"name": "Cycle B", "parent": "Cycle A"}]
		)
		self.assertTrue(cycle_errors)

		_, missing_errors = _build_ledger_group_paths([{"name": "Missing Child", "parent": "Missing Parent"}])
		self.assertTrue(missing_errors)

	def test_auto_onboarding_is_disabled_without_explicit_flag(self):
		code = "TALLY-AUTO-OFF-001"
		run = sync_tally_masters(
			{"customer_ledgers": [self._ledger(code, "TALLY-AUTO-OFF-GUID")]}
		)

		self.assertFalse(run.customer_onboarding_enabled)
		self.assertFalse(frappe.db.exists("Customer", {"client_code": code}))

	def test_tally_customer_is_created_without_mobile_and_sync_is_idempotent(self):
		code = "TALLY-AUTO-ON-001"
		records = {
			"customer_ledgers": [self._ledger(code, "TALLY-AUTO-ON-GUID", "Tally Auto Onboarded")],
			"customer_ledgers_complete": True,
		}

		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundry Debtors"]}):
			first_run = sync_tally_masters(records, auto_onboard_customers=True)
		customer_name = frappe.db.get_value("Customer", {"client_code": code}, "name")
		customer = frappe.get_doc("Customer", customer_name)
		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundry Debtors"]}):
			second_run = sync_tally_masters(records, auto_onboard_customers=True)

		self.assertEqual(first_run.customer_records_created, 1)
		self.assertEqual(second_run.customer_records_created, 0)
		self.assertEqual(frappe.db.count("Customer", {"client_code": code}), 1)
		self.assertEqual(customer.onboarding_source, "Tally")
		self.assertEqual(customer.tally_guid, "TALLY-AUTO-ON-GUID")
		self.assertFalse(customer.mobile_number)
		self.assertEqual(customer.status, "Active")
		self.assertTrue(customer.admin_approved)
		self.assertFalse(customer.mobile_verified)
		self.assertFalse(customer.customer_app_access)
		self.assertTrue(customer.sales_employee_order_access)
		self.assertFalse(get_customer_access_checklist(customer)["mobile_verified"])
		self.assertFalse(
			frappe.db.exists(
				"Mobile Auth Token",
				{"identity_type": "Customer", "identity": customer.name},
			)
		)
		self.assertFalse(frappe.db.exists("Mobile OTP", {"mobile_number": (customer.mobile_number or "")}))

	def test_tally_customer_names_follow_a_renamed_tally_ledger(self):
		code = "TALLY-RENAME-001"
		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundry Debtors"]}):
			sync_tally_masters(
				{"customer_ledgers": [self._ledger(code, "TALLY-RENAME-GUID", "Original Tally Name")]},
				auto_onboard_customers=True,
			)
		customer_name = frappe.db.get_value("Customer", {"client_code": code}, "name")

		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundry Debtors"]}):
			sync_tally_masters(
				{"customer_ledgers": [self._ledger(code, "TALLY-RENAME-GUID", "Renamed Tally Name")]},
				auto_onboard_customers=True,
			)

		customer = frappe.get_doc("Customer", customer_name)
		self.assertEqual(customer.customer_name, "Renamed Tally Name")
		self.assertEqual(customer.business_legal_name, "Renamed Tally Name")

	def test_nested_tally_ledger_matches_configured_ancestor_group(self):
		code = "TALLY-NESTED-001"
		ledger = self._ledger(code, "TALLY-NESTED-GUID", "Nested Tally Customer")
		ledger.update(
			{
				"tally_parent": "Shiva Interior",
				"tally_parent_path": "Current Asset > Sundary Debtors > SHIVA NEW > Shiva Interior",
			}
		)

		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundary Debtors"]}):
			preview = get_tally_customer_onboarding_preview({"customer_ledgers": [ledger]})
		self.assertEqual(preview["counts"]["new_customers"], 1)

		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundary Debtors"]}):
			run = sync_tally_masters(
				{"customer_ledgers": [ledger]},
				auto_onboard_customers=True,
			)

		self.assertEqual(run.customer_records_created, 1)
		self.assertTrue(frappe.db.exists("Customer", {"client_code": code}))

	def test_nested_tally_ledger_from_other_ancestor_is_not_matched(self):
		ledger = self._ledger("TALLY-OTHER-ANCESTOR-001", "TALLY-OTHER-ANCESTOR-GUID")
		ledger.update(
			{
				"tally_parent": "Sundry Creditors",
				"tally_parent_path": "Current Liabilities > Sundry Creditors",
			}
		)

		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundary Debtors"]}):
			preview = get_tally_customer_onboarding_preview({"customer_ledgers": [ledger]})

		self.assertEqual(preview["counts"]["unclassified_ledgers"], 1)
		self.assertEqual(preview["counts"]["new_customers"], 0)

	def test_imported_ledger_with_unresolved_parent_path_is_not_onboarded(self):
		code = "TALLY-UNRESOLVED-PATH-001"
		ledger = self._ledger(code, "TALLY-UNRESOLVED-PATH-GUID")
		ledger.update(
			{
				"tally_parent_path": None,
				"source_tally_parent_path_error": "Tally ledger group is missing from source: Missing Group",
			}
		)

		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundary Debtors"]}):
			run = sync_tally_masters(
				{"customer_ledgers": [ledger]},
				auto_onboard_customers=True,
			)

		self.assertEqual(run.customer_records_created, 0)
		self.assertEqual(run.customer_onboarding_errors, 1)
		self.assertFalse(frappe.db.exists("Customer", {"client_code": code}))
		self.assertFalse(frappe.db.get_value("Tally Customer Ledger", code, "is_active"))

	def test_forced_auto_onboarding_without_parent_allowlist_creates_nothing(self):
		code = "TALLY-AUTO-NO-CONFIG-001"
		with patch.dict(frappe.conf, {"tally_customer_parent_groups": []}):
			run = sync_tally_masters(
				{"customer_ledgers": [self._ledger(code, "TALLY-AUTO-NO-CONFIG-GUID")]},
				auto_onboard_customers=True,
			)

		self.assertEqual(run.customer_records_created, 0)
		self.assertEqual(run.customer_onboarding_errors, 1)
		self.assertFalse(frappe.db.exists("Customer", {"client_code": code}))

	def test_complete_tally_snapshot_reconciles_missing_ledger_without_onboarding(self):
		code = "TALLY-RECONCILE-WITHOUT-ONBOARDING-001"
		ledger = self._ledger(code, "TALLY-RECONCILE-WITHOUT-ONBOARDING-GUID")
		sync_tally_masters({"customer_ledgers": [ledger]}, auto_onboard_customers=False)

		run = sync_tally_masters(
			{"customer_ledgers": [], "customer_ledgers_complete": True},
			auto_onboard_customers=False,
		)

		self.assertEqual(run.customer_records_created, 0)
		self.assertFalse(frappe.db.get_value("Tally Customer Ledger", code, "is_active"))

	def test_non_tally_customer_still_requires_mobile_number(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": "Manual Customer Without Mobile",
					"business_legal_name": "Manual Customer Without Mobile",
					"status": "Pending OTP",
				}
			).insert()

	def test_active_tally_sync_does_not_reenable_manually_disabled_customer(self):
		code = "TALLY-MANUAL-DISABLE-001"
		ledger = self._ledger(code, "TALLY-MANUAL-DISABLE-GUID")
		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundry Debtors"]}):
			sync_tally_masters({"customer_ledgers": [ledger]}, auto_onboard_customers=True)
		customer_name = frappe.db.get_value("Customer", {"client_code": code}, "name")
		frappe.db.set_value(
			"Customer",
			customer_name,
			{"status": "Disabled", "sales_employee_order_access": 0},
		)

		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundry Debtors"]}):
			sync_tally_masters({"customer_ledgers": [ledger]}, auto_onboard_customers=True)

		customer = frappe.get_doc("Customer", customer_name)
		self.assertEqual(customer.status, "Disabled")
		self.assertFalse(customer.sales_employee_order_access)

	def test_tally_customer_loses_sales_employee_access_when_moved_outside_allowed_ancestor(self):
		code = "TALLY-MOVED-OUT-001"
		ledger = self._ledger(code, "TALLY-MOVED-OUT-GUID")
		ledger["tally_parent_path"] = "Current Asset > Sundary Debtors"
		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundary Debtors"]}):
			sync_tally_masters(
				{"customer_ledgers": [ledger], "customer_ledgers_complete": True},
				auto_onboard_customers=True,
			)
		customer_name = frappe.db.get_value("Customer", {"client_code": code}, "name")
		customer = frappe.get_doc("Customer", customer_name)
		self.assertTrue(has_sales_employee_order_access(customer))

		ledger["tally_parent"] = "Sundry Creditors"
		ledger["tally_parent_path"] = "Current Liabilities > Sundry Creditors"
		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundary Debtors"]}):
			sync_tally_masters(
				{"customer_ledgers": [ledger], "customer_ledgers_complete": True},
				auto_onboard_customers=False,
			)

		customer.reload()
		self.assertTrue(customer.sales_employee_order_access)
		self.assertFalse(has_sales_employee_order_access(customer))

	def test_closed_tally_ledger_is_not_onboarded(self):
		ledger = self._ledger("TALLY-CLOSED-001", "TALLY-CLOSED-GUID", "Closed Tally Customer")
		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundry Debtors"]}):
			preview = get_tally_customer_onboarding_preview({"customer_ledgers": [ledger]})

		self.assertEqual(preview["counts"]["inactive_ledgers"], 1)
		self.assertEqual(preview["counts"]["new_customers"], 0)
		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundry Debtors"]}):
			run = sync_tally_masters(
				{"customer_ledgers": [ledger]},
				auto_onboard_customers=True,
			)

		self.assertEqual(run.customer_records_created, 0)
		self.assertFalse(frappe.db.exists("Customer", {"client_code": "TALLY-CLOSED-001"}))

	def test_malformed_or_inactive_tally_ledger_is_not_onboarded(self):
		for suffix, is_active in (("INACTIVE", 0), ("MALFORMED", "unknown")):
			code = f"TALLY-{suffix}-001"
			ledger = self._ledger(code, f"TALLY-{suffix}-GUID")
			ledger["is_active"] = is_active
			with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundry Debtors"]}):
				run = sync_tally_masters(
					{"customer_ledgers": [ledger]},
					auto_onboard_customers=True,
				)

			self.assertEqual(run.customer_records_created, 0)
			self.assertFalse(frappe.db.exists("Customer", {"client_code": code}))

	def test_closed_tally_ledger_is_not_an_active_customer_access_source(self):
		ledger = frappe.get_doc(
			{
				"doctype": "Tally Customer Ledger",
				"client_code": "TALLY-CLOSED-ACCESS-001",
				"ledger_name": "Customer Ledger",
				"is_active": 1,
			}
		).insert()
		self.assertIn("TALLY-CLOSED-ACCESS-001", get_active_tally_client_codes([ledger.client_code]))
		frappe.db.set_value("Tally Customer Ledger", ledger.name, "ledger_name", "Customer Ledger - CLOSED")

		self.assertNotIn("TALLY-CLOSED-ACCESS-001", get_active_tally_client_codes([ledger.client_code]))
		self.assertFalse(
			get_customer_access_checklist(
				frappe._dict(
					{
						"mobile_verified": 1,
						"admin_approved": 1,
						"client_code": ledger.client_code,
						"status": "Active",
					}
				)
			)["client_code_found_in_tally"]
		)

	def test_closed_tally_ledger_with_unusual_bracket_is_not_active(self):
		ledger = frappe.get_doc(
			{
				"doctype": "Tally Customer Ledger",
				"client_code": "TALLY-CLOSED-BRACKET-001",
				"ledger_name": "CMB SPACE [CLOSED[",
				"is_active": 1,
			}
		).insert()

		self.assertNotIn("TALLY-CLOSED-BRACKET-001", get_active_tally_client_codes([ledger.client_code]))

	def test_preview_is_read_only_and_blocks_unclassified_ledger(self):
		code = "TALLY-PREVIEW-001"
		with patch.dict(frappe.conf, {"tally_customer_parent_groups": []}):
			preview = get_tally_customer_onboarding_preview(
				{"customer_ledgers": [self._ledger(code, "TALLY-PREVIEW-GUID")]}
			)

		self.assertEqual(preview["counts"]["unclassified_ledgers"], 1)
		self.assertEqual(preview["counts"]["new_customers"], 0)
		self.assertEqual(preview["unclassified_parent_group_counts"], {"Sundry Debtors": 1})
		self.assertTrue(preview["configuration_missing"])
		self.assertFalse(frappe.db.exists("Customer", {"client_code": code}))

	def test_sales_employee_can_search_tally_customer_by_code_without_mobile(self):
		code = "TALLY-SEARCH-001"
		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundry Debtors"]}):
			sync_tally_masters(
				{"customer_ledgers": [self._ledger(code, "TALLY-SEARCH-GUID", "Searchable Tally Business")]},
				auto_onboard_customers=True,
			)
		customer_name = frappe.db.get_value("Customer", {"client_code": code}, "name")
		sales_employee = frappe.get_doc(
			{
				"doctype": "Sales Employee",
				"sales_employee_name": "Tally Search Employee",
				"mobile_number": "9000000901",
				"status": "Active",
			}
		).insert()

		response = allowed_customers(sales_employee.name, search=code)

		self.assertTrue(response["success"])
		self.assertEqual([row["customer"] for row in response["data"]["customers"]], [customer_name])

	def test_no_phone_sales_employee_order_generates_pdf_and_skips_whatsapp(self):
		group = frappe.get_doc(
			{
				"doctype": "Tally Stock Group",
				"group_name": "Tally Order Group",
				"is_root": 1,
				"is_active": 1,
			}
		).insert()
		item = frappe.get_doc(
			{
				"doctype": "Tally Item",
				"item_name": "Tally Order Item",
				"root_stock_group": group.name,
				"immediate_stock_group": group.name,
				"uom": "PCS",
				"is_active": 1,
			}
		).insert()
		godown = frappe.get_doc(
			{
				"doctype": "Tally Godown",
				"godown_name": "Tally Order Godown",
				"is_active": 1,
			}
		).insert()
		code = "TALLY-ORDER-001"
		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundry Debtors"]}):
			sync_tally_masters(
				{"customer_ledgers": [self._ledger(code, "TALLY-ORDER-GUID")]},
				auto_onboard_customers=True,
			)
		customer_name = frappe.db.get_value("Customer", {"client_code": code}, "name")
		sales_employee = frappe.get_doc(
			{
				"doctype": "Sales Employee",
				"sales_employee_name": "Tally Order Employee",
				"mobile_number": "9000000902",
				"status": "Active",
				"assigned_customers": [{"customer": customer_name}],
			}
		).insert()

		order = submit_order(
			customer_name,
			[{"item": item.name, "godown": godown.name, "quantity": 2}],
			sales_employee=sales_employee.name,
		)

		pdf = frappe.get_doc("Order PDF", {"order": order.name})
		notification = frappe.get_doc("Order WhatsApp Notification", {"order": order.name})
		self.assertTrue(pdf.file_url)
		self.assertEqual(notification.status, "Skipped")
		self.assertEqual(notification.skip_reason, "Customer has no mobile number")
		self.assertFalse(notification.mobile_number)

	def test_missing_complete_ledger_snapshot_disables_tally_order_access(self):
		code = "TALLY-MISSING-001"
		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundry Debtors"]}):
			sync_tally_masters(
				{
					"customer_ledgers": [self._ledger(code, "TALLY-MISSING-GUID")],
					"customer_ledgers_complete": True,
				},
				auto_onboard_customers=True,
			)
		customer_name = frappe.db.get_value("Customer", {"client_code": code}, "name")

		with patch.dict(frappe.conf, {"tally_customer_parent_groups": ["Sundry Debtors"]}):
			run = sync_tally_masters(
				{"customer_ledgers": [], "customer_ledgers_complete": True},
				auto_onboard_customers=True,
			)

		self.assertEqual(run.customer_order_access_disabled, 1)
		self.assertFalse(frappe.db.get_value("Customer", customer_name, "sales_employee_order_access"))

	def _ledger(self, client_code, tally_guid, ledger_name=None):
		return {
			"client_code": client_code,
			"ledger_name": ledger_name or f"Ledger {client_code}",
			"tally_guid": tally_guid,
			"tally_parent": "Sundry Debtors",
			"is_active": 1,
		}
