import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now_datetime


class Customer(Document):
	def validate(self):
		self._normalize_identity_fields()
		self._validate_mobile_number_is_global_identity()
		self._validate_rejected_customer_mobile_reuse()
		self._validate_unique_optional_identity_fields()
		self._validate_client_code()
		self._validate_product_group_access()
		self._apply_customer_app_access()

	def _normalize_identity_fields(self):
		if self.mobile_number:
			self.mobile_number = self.mobile_number.strip()
		if self.client_code:
			self.client_code = self.client_code.strip()
		if self.email_id:
			self.email_id = self.email_id.strip().lower()
		if self.gstin:
			self.gstin = self.gstin.strip().upper()

	def _validate_mobile_number_is_global_identity(self):
		if not self.mobile_number:
			return

		sales_employee = frappe.db.exists(
			"Sales Employee",
			{
				"mobile_number": self.mobile_number,
			},
		)
		if sales_employee:
			frappe.throw(
				_("This mobile number is already in use"),
				title=_("Duplicate Mobile Login Identity"),
			)

	def _validate_rejected_customer_mobile_reuse(self):
		if not self.mobile_number or self.status == "Rejected":
			return

		rejected_customer = frappe.db.exists(
			"Customer",
			{
				"mobile_number": self.mobile_number,
				"status": "Rejected",
				"name": ("!=", self.name or ""),
			},
		)
		if rejected_customer:
			frappe.throw(
				_("This mobile number is not available for signup"),
				title=_("Rejected Customer Exists"),
			)

	def _validate_unique_optional_identity_fields(self):
		for fieldname, label in (("email_id", _("Email ID")), ("gstin", _("GSTIN"))):
			value = self.get(fieldname)
			if not value:
				continue

			duplicate_customer = frappe.db.exists(
				"Customer",
				{
					fieldname: value,
					"name": ("!=", self.name or ""),
				},
			)
			if duplicate_customer:
				frappe.throw(
					_("{0} is already in use").format(label),
					title=_("Duplicate Customer Identity"),
				)

	def _validate_client_code(self):
		if not self.client_code:
			return

		duplicate_customer = frappe.db.exists(
			"Customer",
			{
				"client_code": self.client_code,
				"name": ("!=", self.name or ""),
			},
		)
		if duplicate_customer:
			frappe.throw(
				_("This Client Code is already in use"),
				title=_("Duplicate Client Code"),
			)

		if not frappe.db.exists(
			"Tally Customer Ledger",
			{
				"client_code": self.client_code,
				"is_active": 1,
			},
		):
			frappe.throw(
				_("Client Code {0} was not found in imported Tally Customer Ledgers").format(self.client_code),
				title=_("Invalid Client Code"),
			)

	def _apply_customer_app_access(self):
		has_access = bool(
			self.mobile_verified
			and self.admin_approved
			and self.client_code
			and self.status == "Active"
		)
		self.customer_app_access = 1 if has_access else 0

		if self.mobile_verified and not self.mobile_verified_at:
			self.mobile_verified_at = now_datetime()

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


def get_access_status(customer_name):
	customer = frappe.get_doc("Customer", customer_name)
	checklist = get_customer_access_checklist(customer)
	return {
		"customer": customer.name,
		"status": customer.status,
		"customer_app_access": bool(customer.customer_app_access),
		"checklist": checklist,
		"missing_requirements": [
			label for label, passed in checklist.items() if not passed
		],
	}


def get_customer_access_checklist(customer):
	client_code_found = False
	if customer.client_code:
		client_code_found = bool(
			frappe.db.exists(
				"Tally Customer Ledger",
				{
					"client_code": customer.client_code,
					"is_active": 1,
				},
			)
		)

	return {
		"mobile_verified": bool(customer.mobile_verified),
		"admin_approved": bool(customer.admin_approved),
		"client_code_present": bool(customer.client_code),
		"client_code_found_in_tally": client_code_found,
		"account_active": customer.status == "Active",
		"account_not_disabled_or_rejected": customer.status not in ("Disabled", "Rejected"),
	}


@frappe.whitelist()
def approve_customer(customer_name):
	customer = frappe.get_doc("Customer", customer_name)
	if not customer.mobile_verified:
		frappe.throw(_("Customer mobile number must be verified before approval"))
	customer.admin_approved = 1
	customer.status = "Active"
	customer.save()
	return get_access_status(customer.name)


@frappe.whitelist()
def reject_customer(customer_name):
	customer = frappe.get_doc("Customer", customer_name)
	if not customer.mobile_verified:
		frappe.throw(_("Customer mobile number must be verified before rejection"))
	customer.admin_approved = 0
	customer.status = "Rejected"
	customer.save()
	return get_access_status(customer.name)


@frappe.whitelist()
def disable_customer(customer_name):
	customer = frappe.get_doc("Customer", customer_name)
	if not customer.mobile_verified:
		frappe.throw(_("Customer mobile number must be verified before disabling"))
	customer.status = "Disabled"
	customer.save()
	return get_access_status(customer.name)


@frappe.whitelist()
def set_customer_client_code(customer_name, client_code):
	customer = frappe.get_doc("Customer", customer_name)
	client_code = (client_code or "").strip()
	if not client_code:
		frappe.throw(_("Client Code is required"))

	customer.client_code = client_code
	customer.save()
	return get_access_status(customer.name)


@frappe.whitelist()
def search_tally_customer_ledgers(search_text="", customer_name=None, limit=10):
	search_text = (search_text or "").strip()
	current_customer = (customer_name or "").strip()
	limit = min(max(cint(limit) or 10, 1), 10)
	if current_customer:
		frappe.get_doc("Customer", current_customer).check_permission("write")
	elif not frappe.has_permission("Tally Customer Ledger", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	filters = []
	values = {"current_customer": current_customer, "limit": limit}
	if search_text:
		values["search_text"] = f"%{search_text}%"
		filters.append("(ledger.client_code like %(search_text)s or ledger.ledger_name like %(search_text)s)")

	where_clause = " and ".join(filters)
	if where_clause:
		where_clause = f" and {where_clause}"

	return frappe.db.sql(
		f"""
		select
			ledger.client_code,
			ledger.ledger_name,
			ledger.tally_guid,
			mapped_customer.name as mapped_customer,
			mapped_customer.customer_name as mapped_customer_name,
			mapped_customer.business_legal_name as mapped_customer_business
		from `tabTally Customer Ledger` ledger
		left join `tabCustomer` mapped_customer
			on mapped_customer.client_code = ledger.client_code
		where ledger.is_active = 1
			and (mapped_customer.name is null or mapped_customer.name = %(current_customer)s)
			{where_clause}
		order by
			case
				when ledger.client_code = %(search_exact)s then 0
				when ledger.client_code like %(search_prefix)s then 1
				when ledger.ledger_name like %(search_prefix)s then 2
				else 3
			end,
			ledger.client_code
		limit %(limit)s
		""",
		{
			**values,
			"search_exact": search_text,
			"search_prefix": f"{search_text}%",
		},
		as_dict=True,
	)
