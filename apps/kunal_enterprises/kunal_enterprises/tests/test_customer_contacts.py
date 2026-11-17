"""Real save lifecycle for Customer contact linking; no provider/network calls."""

import json
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.api.customer_contacts import link_sender
from kunal_enterprises.api.order_intake_conversation import messages
from kunal_enterprises.api.whatsapp_inbox import conversations
from kunal_enterprises.integrations.customer_contacts import configured_country_code, phone_sql


class TestCustomerContacts(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.code = configured_country_code()
		self.local_sender = "9" + str(uuid4().int)[:9]
		self.sender = self.code + self.local_sender
		self.primary = "8" + str(uuid4().int)[:9]
		self.customer = frappe.get_doc(dict(doctype="Customer",
			customer_name="Contact linking " + uuid4().hex,
			business_legal_name="Synthetic contact-link test", mobile_number=self.primary)).insert()
		self.account = frappe.get_doc(dict(doctype="WhatsApp Account",
			account_name="Contact linking " + uuid4().hex, phone_id=uuid4().hex,
			status="Active", allow_auto_read_receipt=0)).insert(ignore_permissions=True)
		self.source = self.incoming("Synthetic order from an unknown customer employee")
		self.request = frappe.get_doc(dict(doctype="Order Intake Request", source="WhatsApp",
			status="Pending Review", request_type="Order", whatsapp_account=self.account.name,
			sender_number=self.sender, sender_name="Unmatched profile",
			source_messages=[dict(message=self.source.name)])).insert()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def incoming(self, text):
		return frappe.get_doc(dict(doctype="WhatsApp Message", type="Incoming",
			whatsapp_account=self.account.name, message=text, message_id=uuid4().hex,
			content_type="text", profile_name="Unmatched profile",
			**{"from": self.sender})).insert(ignore_permissions=True)

	def link(self):
		return link_sender(self.request.name, self.customer.name, "Ramesh", "Purchase Manager",
			expected_modified=str(self.request.modified))

	def test_real_controller_records_customer_protection_and_preserves_mobile_login(self):
		self.assertFalse(self.source.intake_customer)
		self.link()
		self.customer.reload()
		self.request.reload()
		self.source.reload()
		self.assertEqual(self.customer.mobile_number, self.primary)
		self.assertEqual(len(self.customer.contacts), 1)
		self.assertEqual(self.customer.contacts[0].mobile_number, "+" + self.sender)
		self.assertEqual(self.customer.contacts[0].contact_name, "Ramesh")
		self.assertEqual(self.customer.contacts[0].designation, "Purchase Manager")
		self.assertFalse(self.customer.mobile_verified)
		self.assertFalse(self.customer.customer_app_access)
		self.assertEqual(self.request.customer, self.customer.name)
		self.assertIn("customer", json.loads(self.request.manual_match_fields))
		self.assertFalse(self.request.delivery_contact_name)
		self.assertFalse(self.request.delivery_contact_number)
		self.assertEqual(self.source.intake_customer, self.customer.name)
		self.assertEqual(self.source.intake_identity_type, "Customer")
		# A repeated explicit linking action is idempotent after a real reload.
		self.link()
		self.customer.reload()
		self.assertEqual(len(self.customer.contacts), 1)

	def test_followup_capture_inbox_and_request_evidence_use_the_new_contact(self):
		self.link()
		followup = self.incoming("Synthetic follow-up after customer contact registration")
		self.assertEqual(followup.intake_customer, self.customer.name)
		self.assertEqual(followup.intake_identity_type, "Customer")
		clients = conversations(self.account.name, sender_type="Clients")["conversations"]
		self.assertEqual(len(clients), 1)
		self.assertEqual(clients[0]["identity"]["matches"][0]["name"], self.customer.name)
		self.request.reload()
		identity = messages(self.request.name)["sender_identity"]
		self.assertEqual(identity["status"], "Matched")
		self.assertEqual(identity["matches"][0]["name"], self.customer.name)
		self.assertEqual(identity["matches"][0]["contact_name"], "Ramesh")
		self.assertEqual(identity["matches"][0]["designation"], "Purchase Manager")

	def test_foreign_contact_round_trip_and_cross_customer_uniqueness(self):
		foreign = "382" + str(uuid4().int)[:7]
		self.customer.append("contacts", dict(contact_name="Foreign contact", mobile_number="+" + foreign))
		self.customer.save()
		self.customer.reload()
		self.assertEqual(self.customer.contacts[0].mobile_number, "+" + foreign)
		self.customer.save()
		self.customer.reload()
		self.assertEqual(self.customer.contacts[0].mobile_number, "+" + foreign)
		# An explicit country code must not collide with a national number
		# containing the same digits under the configured default country.
		national = frappe.get_doc(dict(doctype="Customer", customer_name="National " + uuid4().hex,
			business_legal_name="Synthetic distinct national number", mobile_number=foreign)).insert()
		self.assertEqual(national.mobile_number, foreign)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(dict(doctype="Customer", customer_name="Foreign duplicate " + uuid4().hex,
				business_legal_name="Synthetic duplicate", mobile_number="00" + foreign)).insert()
		national.append("contacts", dict(contact_name="Duplicate foreign contact", mobile_number="+" + foreign))
		with self.assertRaises(frappe.ValidationError):
			national.save()

	def test_country_inclusive_ten_digit_sender_links_once_and_matches_followups(self):
		self.sender = "382" + str(uuid4().int)[:7]
		source = self.incoming("Synthetic foreign sender before registration")
		self.assertFalse(source.intake_customer)
		self.request.sender_number = self.sender
		self.request.set("source_messages", [dict(message=source.name)])
		self.request.save()
		self.link()
		self.request.reload()
		self.customer.reload()
		self.assertEqual(self.customer.contacts[0].mobile_number, "+" + self.sender)
		self.link()
		self.customer.reload()
		self.assertEqual(len(self.customer.contacts), 1)
		self.assertEqual(self.customer.mobile_number, self.primary)
		source.reload()
		self.assertEqual(source.intake_customer, self.customer.name)
		followup = self.incoming("Synthetic foreign sender after registration")
		self.assertEqual(followup.intake_customer, self.customer.name)
		clients = conversations(self.account.name, sender_type="Clients")["conversations"]
		self.assertEqual(len(clients), 1)
		self.assertEqual(clients[0]["sender"], self.sender)
		self.assertEqual(clients[0]["identity"]["matches"][0]["name"], self.customer.name)

	def test_sql_normalization_preserves_explicit_country_and_provider_ids(self):
		for value, international, expected in (
			("+382 60 12345", False, "3826012345"),
			("003826012345", False, "3826012345"),
			("9876543210", False, self.code + "9876543210"),
			("3826012345", True, "3826012345"),
			("+91\u202f98765\u00a043210", False, "919876543210"),
		):
			with self.subTest(value=value, international=international):
				expression = phone_sql(frappe.db.escape(value), international=international)
				self.assertEqual(frappe.db.sql("SELECT " + expression)[0][0], expected)
