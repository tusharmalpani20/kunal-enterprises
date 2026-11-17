import frappe
from frappe import _
from frappe.model.document import Document


class SalesEmployee(Document):
	def validate(self):
		self._normalize_mobile_number()
		self._validate_portal_user()
		self._validate_mobile_number_is_global_identity()
		self._validate_product_group_access()

	def _validate_portal_user(self):
		self.portal_user = str(self.portal_user or "").strip() or None
		if not self.portal_user:
			return
		# Lock the shared login before checking ownership; the unique column also
		# protects concurrent links made through other writers.
		user = frappe.db.get_value("User", self.portal_user,
			["enabled", "user_type"], as_dict=True, for_update=True)
		before = self.get_doc_before_save()
		link_changed = self.is_new() or not before or self.portal_user != before.portal_user
		if link_changed:
			if not user or not user.enabled or user.user_type != "System User":
				frappe.throw(_("Portal User must be an enabled System User."))
			if "Sales Portal User" not in frappe.get_roles(self.portal_user):
				frappe.throw(_("Portal User must have the Sales Portal User role or role profile."))
		# An existing login can later be disabled or lose its role without breaking
		# independent mobile OTP verification or employee maintenance. Live portal
		# scope still rejects that login; never relax one-to-one ownership below.
		if frappe.db.exists("Sales Employee", {"portal_user": self.portal_user, "name": ("!=", self.name or "")}):
			frappe.throw(_("This Portal User is already linked to another Sales Employee."))

	def _normalize_mobile_number(self):
		if self.mobile_number:
			self.mobile_number = self.mobile_number.strip()

	def _validate_mobile_number_is_global_identity(self):
		if not self.mobile_number:
			return

		customer = frappe.db.exists(
			"Customer",
			{
				"mobile_number": self.mobile_number,
			},
		)
		if customer:
			frappe.throw(
				_("This mobile number is already in use"),
				title=_("Duplicate Mobile Login Identity"),
			)

	def _validate_product_group_access(self):
		for row in self.product_group_access:
			if not row.product_group:
				continue

			group = frappe.db.get_value(
				"Tally Stock Group",
				row.product_group,
				["is_root", "is_active", "parent_stock_group"],
				as_dict=True,
			)
			if not group or not group.is_active:
				frappe.throw(
					_("Product Group Access can only include active Product Groups"),
					title=_("Invalid Product Group Access"),
				)
			if group.parent_stock_group and not frappe.db.exists("Tally Stock Group", group.parent_stock_group):
				frappe.throw(
					_("Product Group Access references a group with a missing parent"),
					title=_("Invalid Product Group Hierarchy"),
				)


@frappe.whitelist()
def approve_sales_employee(sales_employee_name):
	sales_employee = frappe.get_doc("Sales Employee", sales_employee_name)
	if not sales_employee.mobile_verified:
		frappe.throw(_("Sales Employee mobile number must be verified before approval"))
	sales_employee.status = "Active"
	sales_employee.save()
	return {
		"sales_employee": sales_employee.name,
		"status": sales_employee.status,
		"mobile_verified": bool(sales_employee.mobile_verified),
	}


@frappe.whitelist()
def disable_sales_employee(sales_employee_name):
	sales_employee = frappe.get_doc("Sales Employee", sales_employee_name)
	if not sales_employee.mobile_verified:
		frappe.throw(_("Sales Employee mobile number must be verified before disabling"))
	sales_employee.status = "Disabled"
	sales_employee.save()
	return {
		"sales_employee": sales_employee.name,
		"status": sales_employee.status,
		"mobile_verified": bool(sales_employee.mobile_verified),
	}


@frappe.whitelist()
def reject_sales_employee(sales_employee_name):
	return disable_sales_employee(sales_employee_name)
