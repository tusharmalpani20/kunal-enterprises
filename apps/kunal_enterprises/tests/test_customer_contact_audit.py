"""Independent regressions found while auditing customer phone ownership."""
import unittest
from unittest.mock import patch

import frappe

from kunal_enterprises.integrations import customer_contacts


class CustomerContactAuditTests(unittest.TestCase):
	def test_explicit_international_prefix_does_not_receive_default_country_twice(self):
		for value in ("+3826012345", "+382 60 12345", "003826012345"):
			with self.subTest(value=value):
				self.assertEqual(customer_contacts.normalize_phone(value, "91"), "3826012345")
		self.assertEqual(customer_contacts.normalize_phone("9876543210", "91"), "919876543210")

	def test_contact_save_preserves_explicit_country_and_is_idempotent(self):
		doc = frappe._dict(name="CUSTOMER-A", mobile_number="", contacts=[
			frappe._dict(contact_name="Foreign contact", mobile_number="+3826012345", designation="Purchase")])
		with patch.object(customer_contacts, "lock_customer_numbers"), \
			patch.object(customer_contacts, "configured_country_code", return_value="91"), \
			patch.object(customer_contacts, "_matches", return_value=[]):
			customer_contacts.validate_customer_numbers(doc)
			self.assertEqual(doc.contacts[0].mobile_number, "+3826012345")
			customer_contacts.validate_customer_numbers(doc)
			self.assertEqual(doc.contacts[0].mobile_number, "+3826012345")

	def test_national_and_explicit_foreign_numbers_with_same_digits_are_distinct(self):
		doc = frappe._dict(name="CUSTOMER-A", mobile_number="3826012345", contacts=[
			frappe._dict(contact_name="Foreign contact", mobile_number="+3826012345", designation="")])
		def reject(message, exception=frappe.ValidationError, **kwargs):
			raise exception(message)
		with patch.object(customer_contacts, "lock_customer_numbers"), \
			patch.object(customer_contacts, "configured_country_code", return_value="91"), \
			patch.object(customer_contacts, "_matches", return_value=[]), \
			patch.object(frappe, "throw", side_effect=reject):
			customer_contacts.validate_customer_numbers(doc)
		self.assertEqual(doc.mobile_number, "3826012345")
		self.assertEqual(doc.contacts[0].mobile_number, "+3826012345")


	def test_embedded_or_repeated_plus_cannot_change_number_ownership(self):
		def reject(message, exception=frappe.ValidationError, **kwargs):
			raise exception(message)
		with patch.object(frappe, "throw", side_effect=reject):
			for malformed in ("98765+43210", "+91+9876543210", "++919876543210"):
				with self.subTest(malformed=malformed):
					with self.assertRaises(frappe.ValidationError):
						customer_contacts.normalize_phone(malformed, "91")
					self.assertEqual(customer_contacts.normalize_phone(malformed, "91", strict=False), "")


if __name__ == "__main__":
	unittest.main()
