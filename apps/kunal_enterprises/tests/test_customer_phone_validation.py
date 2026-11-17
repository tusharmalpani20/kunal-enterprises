"""Independent phone ownership checks; only the database boundary is substituted."""

import unittest
from contextlib import ExitStack
from unittest.mock import patch

import frappe
from frappe.model.document import Document

from kunal_enterprises.integrations import customer_contacts
from kunal_enterprises.kunal_enterprises.doctype.customer.customer import Customer
from kunal_enterprises.kunal_enterprises.doctype.customer_contact.customer_contact import CustomerContact


class PhoneDatabase:
	def __init__(self, main=(), contacts=()):
		self.main = [frappe._dict(row) for row in main]
		self.contacts = [frappe._dict(row) for row in contacts]
		self.calls = []

	def get_single_value(self, *args):
		return "91"

	def get_value(self, *args, **kwargs):
		self.calls.append(("lock", args, kwargs))
		return "Customer"

	def escape(self, value):
		return "'" + str(value).replace("'", "''") + "'"

	def multisql(self, queries, values, **kwargs):
		self.calls.append(("query", queries, values, kwargs))
		rows = self.contacts if "JOIN" in queries["mariadb"] else self.main
		return [row.copy() for row in rows if row.name != values[1]]


class CustomerPhoneValidationTests(unittest.TestCase):
	def setUp(self):
		self.stack = ExitStack()
		self.addCleanup(self.stack.close)
		self.db = PhoneDatabase()
		self.stack.enter_context(patch.object(frappe, "db", self.db))
		self.stack.enter_context(patch.object(frappe, "throw", side_effect=self._throw))

	@staticmethod
	def _throw(message, exc=frappe.ValidationError, **kwargs):
		raise exc(message)

	def doc(self, main="", contacts=(), name="CUSTOMER-A"):
		return frappe._dict(name=name, mobile_number=main, contacts=[frappe._dict(
			contact_name=person, mobile_number=number, designation=designation
		) for person, number, designation in contacts])

	def test_local_and_international_format_variants_have_one_identity(self):
		for value in ("9876543210", "+91 98765 43210", "91(98765)-43210", "0091 98765.43210"):
			with self.subTest(value=value):
				self.assertEqual(customer_contacts.normalize_phone(value, "91"), "919876543210")
		self.assertEqual(customer_contacts.normalize_phone("+44 7700 900123", "91"), "447700900123")

	def test_empty_and_invalid_numbers_are_not_silently_coerced(self):
		self.assertEqual(customer_contacts.normalize_phone("", "91"), "")
		for value in ("not-a-number", "98765/43210", "123", "9" * 16, "９８７６５４３２１０"):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				customer_contacts.normalize_phone(value, "91")

	def test_primary_number_cannot_be_repeated_in_its_own_contact_table(self):
		doc = self.doc("9876543210", [("Ramesh", "+91 98765 43210", "Purchase")])
		with self.assertRaisesRegex(frappe.ValidationError, "main Mobile Number"):
			customer_contacts.validate_customer_numbers(doc)

	def test_contacts_cannot_repeat_a_number_in_different_formats(self):
		doc = self.doc(contacts=[("Ramesh", "9876543210", "Purchase"),
			("Suresh", "+91(98765)43210", "Accounts")])
		with self.assertRaisesRegex(frappe.ValidationError, "row 1"):
			customer_contacts.validate_customer_numbers(doc)

	def test_other_customer_primary_number_blocks_both_new_locations(self):
		self.db.main = [frappe._dict(name="CUSTOMER-B", label="Other Business", status="Active")]
		for doc in (self.doc("9876543210"), self.doc(contacts=[("Ramesh", "9876543210", "")])):
			with self.subTest(main=bool(doc.mobile_number)), self.assertRaisesRegex(
				frappe.ValidationError, "CUSTOMER-B.*Other Business"
			):
				customer_contacts.validate_customer_numbers(doc)

	def test_other_customer_contact_number_blocks_both_new_locations(self):
		self.db.contacts = [frappe._dict(name="CUSTOMER-B", label="Other Business", status="Active",
			contact_name="Suresh", designation="Accounts")]
		for doc in (self.doc("9876543210"), self.doc(contacts=[("Ramesh", "9876543210", "")])):
			with self.subTest(main=bool(doc.mobile_number)), self.assertRaisesRegex(
				frappe.ValidationError, "CUSTOMER-B"
			):
				customer_contacts.validate_customer_numbers(doc)

	def test_valid_contact_edit_preserves_primary_login_number(self):
		doc = self.doc("+91 87654 32109", [(" Ramesh ", "98765 43210", " Purchase Manager ")])
		customer_contacts.validate_customer_numbers(doc)
		self.assertEqual(doc.mobile_number, "+91 87654 32109")
		self.assertEqual(doc.contacts[0].mobile_number, "+919876543210")
		self.assertEqual(doc.contacts[0].contact_name, "Ramesh")
		self.assertEqual(doc.contacts[0].designation, "Purchase Manager")

	def test_contact_person_and_phone_are_required_but_designation_is_optional(self):
		for person, number in (("", "9876543210"), ("Ramesh", "")):
			with self.subTest(person=person, number=number), self.assertRaises(frappe.ValidationError):
				customer_contacts.validate_customer_numbers(self.doc(contacts=[(person, number, "")]))
		customer_contacts.validate_customer_numbers(self.doc(contacts=[("Ramesh", "9876543210", "")]))

	def test_duplicate_queries_take_current_locks_and_exclude_the_saved_customer(self):
		self.db.main = [frappe._dict(name="CUSTOMER-A", label="Own business", status="Active")]
		customer_contacts.validate_customer_numbers(self.doc("9876543210"))
		locks = [call for call in self.db.calls if call[0] == "lock"]
		self.assertTrue(locks)
		self.assertTrue(locks[0][2]["for_update"])
		queries = [call for call in self.db.calls if call[0] == "query"]
		self.assertEqual(len(queries), 2)
		for _, query, values, _ in queries:
			self.assertTrue(query["mariadb"].endswith(" FOR UPDATE"))
			self.assertTrue(query["postgres"].endswith(" FOR UPDATE"))
			self.assertEqual(values, ("919876543210", "CUSTOMER-A"))

	def test_sender_lookup_deduplicates_parent_and_keeps_contact_details(self):
		self.db.contacts = [frappe._dict(name="CUSTOMER-A", label="Own business", status="Active",
			contact_name="Ramesh", designation="Purchase Manager")]
		matches = customer_contacts.find_customer_matches("+91 98765 43210")
		self.assertEqual(len(matches), 1)
		self.assertEqual(matches[0]["contact_name"], "Ramesh")
		self.db.main = [frappe._dict(name="CUSTOMER-A", label="Own business", status="Active")]
		self.assertEqual(len(customer_contacts.find_customer_matches("9876543210")), 1)
		self.assertEqual(customer_contacts.find_customer_matches("opaque-whatsapp-id"), [])

	def test_customer_gate_precedes_parent_insert_and_save_locks(self):
		for method in ("insert", "_save"):
			events = []
			with self.subTest(method=method), patch.object(
				customer_contacts, "lock_customer_numbers", side_effect=lambda: events.append("gate")
			), patch.object(Document, method, autospec=True,
				side_effect=lambda *a, **kw: events.append("parent")):
				getattr(object.__new__(Customer), method)()
				self.assertEqual(events, ["gate", "parent"])

	def test_standalone_child_writes_cannot_skip_parent_phone_validation(self):
		child = object.__new__(CustomerContact)
		for method in ("validate", "on_trash"):
			with self.subTest(method=method), self.assertRaises(frappe.PermissionError):
				getattr(child, method)()


if __name__ == "__main__":
	unittest.main()
