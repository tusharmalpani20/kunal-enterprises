"""Real User/Sales Employee saves and admin link search for portal identities."""

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.api.sales_portal_users import available_users


class TestSalesPortalUsers(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.prefix = "sales-link-" + uuid4().hex[:12]

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def user(self, suffix, role="Sales Portal User", **values):
		user = frappe.get_doc(dict(doctype="User", email=f"{self.prefix}-{suffix}@example.com",
			first_name=self.prefix, send_welcome_email=0, user_type="System User", **values))
		if role:
			user.append("roles", dict(role=role))
		return user.insert(ignore_permissions=True)

	def employee(self, user=None):
		return frappe.get_doc(dict(doctype="Sales Employee", sales_employee_name=self.prefix,
			mobile_number="8" + str(uuid4().int)[:9], portal_user=user,
			status="Active")).insert()

	def names(self, employee=""):
		return {row[0] for row in available_users("User", self.prefix, "name", 0, 100,
			dict(sales_employee=employee))}

	def test_link_preserves_mobile_identity_and_is_unique(self):
		user = self.user("one")
		employee = self.employee(user.name)
		mobile = employee.mobile_number
		employee.sales_employee_name += " Updated"
		employee.save()
		self.assertEqual(employee.mobile_number, mobile)
		self.assertFalse(employee.mobile_verified)
		with self.assertRaises(frappe.ValidationError):
			self.employee(user.name)

	def test_dropdown_filters_roles_and_occupied_logins_but_keeps_current_link(self):
		available = self.user("available")
		linked = self.user("linked")
		employee = self.employee(linked.name)
		self.user("wrong-role", role="Branch Employee")
		self.user("disabled", enabled=0)
		self.assertEqual(self.names(), {available.name})
		self.assertEqual(self.names(employee.name), {available.name, linked.name})

	def test_invalid_disabled_and_website_users_cannot_be_linked(self):
		wrong = self.user("wrong", role="Branch Employee")
		disabled = self.user("disabled", enabled=0)
		website = self.user("website", role=None)
		# Use a database change to represent an existing Website User without
		# having Frappe convert its desk-capable role into System User on save.
		frappe.db.set_value("User", website.name, "user_type", "Website User")
		for name in (wrong.name, disabled.name, website.name, "missing@example.com"):
			with self.subTest(user=name), self.assertRaises(frappe.ValidationError):
				self.employee(name)

	def test_role_profile_users_are_eligible_after_user_save(self):
		user = self.user("profile", role=None, role_profile_name="Sales Portal User")
		self.assertIn("Sales Portal User", frappe.get_roles(user.name))
		self.assertIn(user.name, self.names())
		self.assertEqual(self.employee(user.name).portal_user, user.name)

	def test_sales_user_cannot_enumerate_portal_login_candidates(self):
		user = self.user("no-enumeration")
		frappe.set_user(user.name)
		with self.assertRaises(frappe.PermissionError):
			self.names()

	def test_disabling_portal_login_does_not_block_existing_mobile_otp_verification(self):
		from kunal_enterprises.api.otp import verify_sales_employee_otp
		from kunal_enterprises.permission_guards.sales_portal import employee_for_user
		user = self.user("mobile-independent")
		employee = self.employee(user.name)
		otp = frappe.get_doc(dict(doctype="Mobile OTP", mobile_number=employee.mobile_number,
			otp_code="1234", purpose="Sales Employee Login", otp_type="Login",
			status="Open", provider_status="Sent")).insert(ignore_permissions=True)
		frappe.db.set_value("User", user.name, "enabled", 0)
		frappe.set_user("Guest")
		result = verify_sales_employee_otp(employee.mobile_number, "1234")
		self.assertTrue(result["success"], result.get("error"))
		employee.reload()
		self.assertTrue(employee.mobile_verified)
		self.assertEqual(employee.portal_user, user.name)
		self.assertEqual(frappe.db.get_value("Mobile OTP", otp.name, "status"), "Verified")
		frappe.set_user(user.name)
		self.assertIsNone(employee_for_user())

	def test_unchanged_stale_portal_link_does_not_block_employee_administration(self):
		for suffix, changed in (("website", {"user_type": "Website User"}),
			("disabled", {"enabled": 0}), ("role-removed", None)):
			with self.subTest(state=suffix):
				user = self.user("stale-" + suffix)
				employee = self.employee(user.name)
				if changed:
					frappe.db.set_value("User", user.name, changed)
				else:
					frappe.db.delete("Has Role", {"parenttype": "User", "parent": user.name, "role": "Sales Portal User"})
					frappe.clear_cache(user=user.name)
				employee.sales_employee_name += " Updated"
				employee.save()
				self.assertEqual(employee.portal_user, user.name)
				self.assertTrue(employee.sales_employee_name.endswith("Updated"))
