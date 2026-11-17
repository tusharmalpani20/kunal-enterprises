"""Intake metadata lives on the existing incoming WhatsApp Message."""
from uuid import uuid4
import frappe
from frappe.tests.utils import FrappeTestCase
from kunal_enterprises.api import order_intake_capture as api
from kunal_enterprises.integrations import order_intake_capture as capture
from kunal_enterprises.tests import test_foundation as foundation
from kunal_enterprises.patches.simplify_order_intake_capture import _migrate_message


class TestOrderIntakeCapture(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.account = frappe.get_doc({"doctype": "WhatsApp Account", "account_name": "Intake " + uuid4().hex,
			"status": "Active", "phone_id": uuid4().hex}).insert(ignore_permissions=True)
		self.sender = "919998887776"
		frappe.db.set_single_value("Order Intake Settings", "default_country_calling_code", "+91")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def source(self, **values):
		data = {"doctype": "WhatsApp Message", "type": "Incoming", "from": self.sender,
			"message": "Two sheets", "message_id": uuid4().hex, "content_type": "text", "whatsapp_account": self.account.name}
		data.update(values)
		return frappe.get_doc(data).insert(ignore_permissions=True)

	def test_incoming_record_itself_is_prepared_without_creating_request(self):
		before = frappe.db.count("Order Intake Request")
		doc = self.source()
		self.assertEqual(doc.intake_status, "New")
		self.assertEqual(doc.intake_sender_key, self.sender)
		self.assertTrue(doc.intake_received_at)
		self.assertEqual(api.coverage_status(self.account.name)["missing_count"], 0)
		self.assertEqual(frappe.db.count("Order Intake Request"), before)

	def test_country_default_matches_national_customer_without_changing_number(self):
		customer = foundation.TestOrderSubmission._create_active_customer(self, "9998887776", "Intake " + uuid4().hex)
		frappe.db.set_single_value("Order Intake Settings", "default_country_calling_code", "")
		doc = self.source()
		self.assertEqual(doc.intake_customer, customer.name)
		self.assertEqual(frappe.db.get_value("Customer", customer.name, "mobile_number"), "9998887776")

	def test_salesperson_not_substituted_as_customer(self):
		employee = frappe.get_doc({"doctype": "Sales Employee", "sales_employee_name": "Intake Sales",
			"employee_code": uuid4().hex, "mobile_number": "9998887776", "status": "Active"}).insert()
		doc = self.source()
		self.assertEqual(doc.intake_sales_employee, employee.name)
		self.assertFalse(doc.intake_customer)

	def test_customer_contact_sender_matches_parent_without_replacing_primary_mobile(self):
		primary = '8' + str(uuid4().int)[:9]
		customer = foundation.TestOrderSubmission._create_active_customer(self, primary, 'Contact '+uuid4().hex)
		customer.append('contacts', dict(contact_name='Ramesh', mobile_number='+91 (999) 888-7776', designation='Purchase Manager'))
		customer.save()
		doc = self.source()
		self.assertEqual(doc.intake_identity_type, 'Customer')
		self.assertEqual(doc.intake_customer, customer.name)
		self.assertFalse(doc.intake_sales_employee)
		self.assertEqual(frappe.db.get_value('Customer', customer.name, 'mobile_number'), primary)
		candidate = frappe.parse_json(doc.intake_identity_candidates)[0]
		self.assertEqual(candidate['name'], customer.name)
		self.assertEqual(candidate['contact_name'], 'Ramesh')

	def test_unknown_and_ambiguous_senders_are_preserved(self):
		doc = self.source()
		self.assertEqual(doc.intake_identity_type, "Unknown")
		foundation.TestOrderSubmission._create_active_customer(self, self.sender, "Intake " + uuid4().hex)
		frappe.get_doc({"doctype": "Sales Employee", "sales_employee_name": "Intake Sales", "employee_code": uuid4().hex,
			"mobile_number": "+91 (999) 888-7776", "status": "Active"}).insert()
		api.refresh_sender(doc.name)
		doc.reload()
		self.assertEqual(doc.intake_identity_type, "Ambiguous")
		self.assertFalse(doc.intake_customer)

	def test_same_sender_different_accounts_and_no_ids_remain_individual(self):
		a, b = self.source(message_id=""), self.source(message_id="")
		self.assertNotEqual(a.name, b.name)
		self.assertFalse(a.intake_event_key)
		self.assertFalse(b.intake_event_key)

	def test_duplicate_existing_source_is_flagged_without_second_canonical_key(self):
		a = self.source()
		b = self.source(message_id=a.message_id)
		self.assertEqual(b.intake_status, "Duplicate")
		self.assertFalse(b.intake_event_key)

	def test_outgoing_excluded_without_sending(self):
		doc = frappe.get_doc({"doctype": "WhatsApp Message", "name": "outgoing-" + uuid4().hex,
			"type": "Outgoing", "whatsapp_account": self.account.name})
		doc.db_insert()
		with self.assertRaises(frappe.ValidationError):
			api.capture_existing(messages=[doc.name])
		self.assertEqual(api.coverage_status(self.account.name)["incoming_count"], 0)

	def test_historical_preparation_is_explicit_and_bounded(self):
		doc = self.source()
		frappe.db.set_value("WhatsApp Message", doc.name, "intake_received_at", None)
		with self.assertRaises(frappe.ValidationError):
			api.capture_existing()
		self.assertEqual(api.coverage_status(self.account.name)["missing_count"], 1)
		result = api.capture_existing(messages=[doc.name])
		self.assertEqual(result["captured"], [doc.name])
		self.assertEqual(api.coverage_status(self.account.name)["missing_count"], 0)

	def test_guest_cannot_use_reviewer_actions(self):
		doc = self.source()
		frappe.set_user("Guest")
		for action, args in ((api.coverage_status, {}), (api.capture_existing, {"messages": [doc.name]}),
			(api.refresh_sender, {"message": doc.name})):
			with self.assertRaises(frappe.PermissionError):
				action(**args)

	def test_legacy_linked_and_raw_only_evidence_survives_idempotent_migration(self):
		doc = self.source()
		row = dict(name="legacy-" + uuid4().hex, source_message=doc.name, sender=self.sender,
			text="original earlier snapshot", raw_message='{"type":"text"}', processing_status="Needs Attention")
		self.assertEqual(_migrate_message(row, {}), doc.name)
		self.assertEqual(_migrate_message(row, {}), doc.name)
		doc.reload()
		self.assertEqual(doc.message, "Two sheets")
		self.assertEqual(len(frappe.parse_json(doc.intake_legacy_evidence)), 1)
		self.assertEqual(doc.intake_status, "Needs Attention")
		row.update(name="legacy-" + uuid4().hex, source_message=None, whatsapp_account=self.account.name, content_type="contacts")
		name = _migrate_message(row, {})
		self.assertEqual(_migrate_message(row, {}), name)
		self.assertEqual(frappe.db.get_value("WhatsApp Message", name, "type"), "Incoming")
		self.assertIn("original earlier snapshot", frappe.db.get_value("WhatsApp Message", name, "intake_legacy_evidence"))
