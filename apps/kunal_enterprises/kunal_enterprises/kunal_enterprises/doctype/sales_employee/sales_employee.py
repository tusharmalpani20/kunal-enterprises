import frappe
from frappe import _
from frappe.model.document import Document


class SalesEmployee(Document):
	def validate(self):
		self._normalize_mobile_number()
		self._validate_mobile_number_is_global_identity()
		self._validate_product_group_access()

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
				["is_root", "is_active"],
				as_dict=True,
			)
			if not group or not group.is_root or not group.is_active:
				frappe.throw(
					_("Product Group Access can only include active root Product Groups"),
					title=_("Invalid Product Group Access"),
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
def reject_sales_employee(sales_employee_name):
	sales_employee = frappe.get_doc("Sales Employee", sales_employee_name)
	if not sales_employee.mobile_verified:
		frappe.throw(_("Sales Employee mobile number must be verified before rejection"))
	sales_employee.status = "Disabled"
	sales_employee.save()
	return {
		"sales_employee": sales_employee.name,
		"status": sales_employee.status,
		"mobile_verified": bool(sales_employee.mobile_verified),
	}
