"""Independent checks for the narrow WhatsApp sender-link action."""

import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe

from kunal_enterprises.api import customer_contacts
from kunal_enterprises.integrations import customer_contacts as phone_ownership
from kunal_enterprises.kunal_enterprises.doctype.order_intake_request import order_intake_request


class CustomerContactLinkingTests(unittest.TestCase):
	def setUp(self):
		self.stack = ExitStack()
		self.addCleanup(self.stack.close)
		self.stack.enter_context(patch.object(frappe.local, "flags", frappe._dict(in_test=True), create=True))
		self.events = []
		self.doc = frappe._dict(name="REQUEST-A", source="WhatsApp", status="Pending Review", order=None,
			modified="2026-11-17 16:00:00.000000", sender_number="919876543210", whatsapp_account="TEST WA",
			customer=None, manual_match_fields="[]", source_messages=[frappe._dict(message="MESSAGE-A")],
			check_permission=Mock(), save=Mock())
		self.target = frappe._dict(name="CUSTOMER-A", mobile_number="8765432109", contacts=[], save=Mock())
		self.target.append = lambda field, value: self.target[field].append(frappe._dict(value))
		self.message = frappe._dict(type="Incoming", whatsapp_account="TEST WA", **{"from": "+91 98765 43210"},
			check_permission=Mock())
		self.require = self.stack.enter_context(patch.object(customer_contacts, "_require_reviewer"))
		self.lock = self.stack.enter_context(patch.object(customer_contacts, "lock_customer_numbers",
			side_effect=lambda: self.events.append("phone_gate")))
		self.get_doc = self.stack.enter_context(patch.object(frappe, "get_doc", side_effect=self._get_doc))
		self.stack.enter_context(patch.object(frappe, "db", SimpleNamespace(get_single_value=lambda *args: "91")))
		self.stack.enter_context(patch.object(frappe, "throw", side_effect=self._throw))
		self.identity = self.stack.enter_context(patch(
			"kunal_enterprises.integrations.order_intake_capture._identity",
			return_value={"identity_candidates": "[]"}))
		self.refresh = self.stack.enter_context(patch(
			"kunal_enterprises.integrations.order_intake_capture.refresh_sender_identity"))

	@staticmethod
	def _throw(message, exc=frappe.ValidationError, **kwargs):
		raise exc(message)

	def _get_doc(self, doctype, name, **kwargs):
		if (doctype, name) == ("Order Intake Request", "REQUEST-A"):
			return self.doc
		if (doctype, name) == ("WhatsApp Message", "MESSAGE-A"):
			return self.message
		if (doctype, name) == ("Customer", "CUSTOMER-A"):
			self.events.append("target_customer")
			return self.target
		raise AssertionError((doctype, name, kwargs))

	def link(self, **kwargs):
		return customer_contacts.link_sender(request="REQUEST-A", customer="CUSTOMER-A",
			contact_name=" Ramesh ", designation=" Purchase Manager ",
			expected_modified=kwargs.pop("expected_modified", self.doc.modified), **kwargs)

	def test_unknown_sender_is_added_once_without_changing_primary_login(self):
		result = self.link()
		self.assertEqual(result["customer"], "CUSTOMER-A")
		self.assertEqual(self.target.mobile_number, "8765432109")
		self.assertEqual(self.target.contacts, [frappe._dict(contact_name="Ramesh",
			mobile_number="+919876543210", designation="Purchase Manager")])
		self.target.save.assert_called_once_with(ignore_permissions=True)
		self.assertEqual(self.doc.customer, "CUSTOMER-A")
		# Protected fields must be left to the request controller's save lifecycle.
		self.assertEqual(self.doc.manual_match_fields, "[]")
		self.doc.save.assert_called_once()
		self.refresh.assert_called_once_with("MESSAGE-A")
		self.assertLess(self.events.index("phone_gate"), self.events.index("target_customer"))
		self.require.assert_called_once()
		self.doc.check_permission.assert_any_call("read")
		self.doc.check_permission.assert_any_call("write")
		self.message.check_permission.assert_called_once_with("read")
		self.link()
		self.assertEqual(len(self.target.contacts), 1)
		self.target.save.assert_called_once()

	def test_linking_uses_real_request_guards_to_record_the_manual_customer_choice(self):
		Request = order_intake_request.OrderIntakeRequest
		request, before = object.__new__(Request), object.__new__(Request)
		state = dict(self.doc)
		state.update(doctype="Order Intake Request", items=[], sales_employee=None,
			proposed_updates=None, matching_json=None, ai_initial_values=None,
			first_received_at=None, last_received_at=None, reviewed_by=None, processed_at=None)
		request.__dict__.update(state)
		before.__dict__.update(state)
		request.flags = frappe._dict()
		before.flags = frappe._dict()
		request._doc_before_save = before
		self.doc = request
		# Exercise the real validate() protected-field checks and its real manual
		# match protection; unrelated item/attachment validation has separate tests.
		for method in ("_validate_legacy_evidence", "_simplify_legacy_layout", "_validate_items",
			"_validate_attachments", "_validate_sources"):
			self.stack.enter_context(patch.object(Request, method, return_value=None))
		self.stack.enter_context(patch.object(order_intake_request, "_require_reviewer"))
		frappe.db.get_value = lambda *args, **kwargs: "Customer display name"
		request.save = Mock(side_effect=request.validate)
		self.link()
		self.assertEqual(request.customer, "CUSTOMER-A")
		self.assertEqual(json.loads(request.manual_match_fields), ["customer"])
		request.save.assert_called_once()

	def test_existing_primary_number_does_not_create_a_contact_duplicate(self):
		self.target.mobile_number = "+91 98765 43210"
		self.link()
		self.assertEqual(self.target.contacts, [])
		self.target.save.assert_not_called()

	def test_revision_and_request_permissions_are_enforced_before_master_write(self):
		with self.assertRaises(frappe.TimestampMismatchError):
			self.link(expected_modified="older revision")
		self.target.save.assert_not_called()
		self.lock.assert_not_called()
		self.doc.check_permission.side_effect = frappe.PermissionError("No access")
		with self.assertRaises(frappe.PermissionError):
			self.link()
		self.target.save.assert_not_called()

	def test_nonreviewer_cannot_link_a_sender(self):
		self.require.side_effect = frappe.PermissionError("Reviewers only")
		with self.assertRaises(frappe.PermissionError):
			self.link()
		self.get_doc.assert_not_called()

	def test_foreign_or_outgoing_sources_cannot_register_arbitrary_numbers(self):
		for field, value in (("type", "Outgoing"), ("whatsapp_account", "OTHER WA"),
			("from", "919111112222")):
			original = self.message[field]
			with self.subTest(field=field):
				self.message[field] = value
				with self.assertRaises(frappe.ValidationError):
					self.link()
				self.target.save.assert_not_called()
				self.assertIsNone(self.doc.customer)
			self.message[field] = original

	def test_missing_source_and_unreadable_source_are_rejected(self):
		self.doc.source_messages = []
		with self.assertRaises(frappe.ValidationError):
			self.link()
		self.doc.source_messages = [frappe._dict(message="MESSAGE-A")]
		self.message.check_permission.side_effect = frappe.PermissionError("No source access")
		with self.assertRaises(frappe.PermissionError):
			self.link()
		self.target.save.assert_not_called()

	def test_existing_different_request_customer_is_never_silently_replaced(self):
		self.doc.customer = "CUSTOMER-B"
		with self.assertRaises(frappe.ValidationError):
			self.link()
		self.assertEqual(self.doc.customer, "CUSTOMER-B")
		self.target.save.assert_not_called()

	def test_sales_employee_and_other_customer_phone_ownership_cannot_be_relinked(self):
		for candidate in ({"doctype": "Sales Employee", "name": "EMPLOYEE-A"},
			{"doctype": "Customer", "name": "CUSTOMER-B"}):
			with self.subTest(candidate=candidate):
				self.identity.return_value = {"identity_candidates": json.dumps([candidate])}
				with self.assertRaises(frappe.ValidationError):
					self.link()
				self.target.save.assert_not_called()

	def test_customer_validation_failure_does_not_modify_the_request(self):
		self.target.save.side_effect = frappe.ValidationError("Phone already belongs to CUSTOMER-B")
		with self.assertRaises(frappe.ValidationError):
			self.link()
		self.assertIsNone(self.doc.customer)
		self.doc.save.assert_not_called()
		self.refresh.assert_not_called()

	def test_stale_phone_snapshot_requires_a_whole_request_retry(self):
		with patch.object(frappe.db, "multisql", create=True,
			side_effect=frappe.QueryDeadlockError("record changed since last read")) as query:
			with self.assertRaisesRegex(frappe.TimestampMismatchError, "Reload and try again"):
				phone_ownership._query("SELECT name FROM `tabCustomer`", (), current=True)
			query.assert_called_once()
		# Unrelated non-locking reads retain the framework's native DB error.
		with patch.object(frappe.db, "multisql", create=True,
			side_effect=frappe.QueryDeadlockError("unrelated read")):
			with self.assertRaises(frappe.QueryDeadlockError):
				phone_ownership._query("SELECT name FROM `tabCustomer`", ())


if __name__ == "__main__":
	unittest.main()
