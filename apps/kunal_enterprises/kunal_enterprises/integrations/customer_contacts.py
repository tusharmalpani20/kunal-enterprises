"""Customer-only phone ownership; these contacts are not mobile login identities."""
import re

import frappe


PHONE_SEPARATORS = re.compile(r"[ +().\-\t\r\n\u00a0\u202f]")


def configured_country_code():
	value = str(frappe.db.get_single_value("Order Intake Settings", "default_country_calling_code") or "91").strip().lstrip("+")
	if not value.isascii() or not value.isdigit() or not 1 <= len(value) <= 3:
		frappe.throw("Set a valid default country calling code in Order Intake Settings.")
	return value


def normalize_phone(number, country_code=None, *, strict=True, international=False):
	text = str(number or "").strip(" \t\r\n\u00a0\u202f")
	if not text:
		return ""
	digits = PHONE_SEPARATORS.sub("", text)
	explicit_country = international or "+" in text or digits.startswith("00")
	if digits.startswith("00"):
		digits = digits[2:]
	invalid_plus = text.count("+") > 1 or ("+" in text and not text.startswith("+"))
	if invalid_plus or not digits.isascii() or not digits.isdigit() or not 7 <= len(digits) <= 15:
		if not strict:
			return ""
		frappe.throw("Enter a valid phone number, including its country code for international numbers.")
	code = str(country_code) if country_code is not None else configured_country_code()
	if len(digits) == 10 and not explicit_country:
		digits = code + digits
	return digits


def lock_customer_numbers():
	# Acquire BEFORE Customer's own row lock, and hold until commit/rollback.
	# A stable metadata row supplies a cross-database transaction lock without
	# advisory locks or a second phone registry that could get out of sync.
	frappe.db.get_value("DocType", "Customer", "name", for_update=True)


def phone_sql(field, *, international=False):
	clean = f"COALESCE({field}, '')"
	for char in ("+", " ", "-", "(", ")", ".", "\t", "\n", "\r", "\u00a0", "\u202f"):
		clean = f"REPLACE({clean}, {frappe.db.escape(char)}, '')"
	explicit_country = f"(POSITION('+' IN COALESCE({field}, ''))>0 OR LEFT({clean},2)='00')"
	clean = f"CASE WHEN LEFT({clean},2)='00' THEN SUBSTRING({clean},3) ELSE {clean} END"
	if international:
		return clean
	return f"CASE WHEN CHAR_LENGTH({clean})=10 AND NOT {explicit_country} THEN CONCAT('{configured_country_code()}',{clean}) ELSE {clean} END"


def _query(sql, values, current=False):
	if current:
		sql += " FOR UPDATE"
	try:
		return frappe.db.multisql({"mariadb": sql, "postgres": sql.replace('`', '"')}, values, as_dict=True)
	except frappe.QueryDeadlockError:
		if not current:
			raise
		# A stale transaction snapshot must be retried as a whole. Never roll
		# back or retry only part of a Customer/intake save inside validation.
		frappe.throw("Customer phone records changed during this save. Reload and try again.", frappe.TimestampMismatchError)


def _matches(key, exclude="", current=False):
	main = _query(f"SELECT name, customer_name AS label, status FROM `tabCustomer` WHERE {phone_sql('mobile_number')}=%s AND name<>%s", (key, exclude), current)
	contacts = _query(f"SELECT c.name,c.customer_name AS label,c.status,cc.contact_name,cc.designation FROM `tabCustomer Contact` cc JOIN `tabCustomer` c ON c.name=cc.parent WHERE cc.parenttype='Customer' AND cc.parentfield='contacts' AND {phone_sql('cc.mobile_number')}=%s AND c.name<>%s", (key, exclude), current)
	return main + contacts


def find_customer_matches(number):
	# WhatsApp supplies country-code-inclusive sender IDs, even without a +.
	key = normalize_phone(number, strict=False, international=True)
	if not key:
		return []
	matches = {}
	for row in _matches(key):
		matches.setdefault(row.name, dict(row))
	return list(matches.values())


def validate_customer_numbers(doc):
	lock_customer_numbers()
	code = configured_country_code()
	seen = {}
	if doc.mobile_number:
		seen[normalize_phone(doc.mobile_number, code)] = "main Mobile Number"
	for index, row in enumerate(doc.get("contacts") or [], 1):
		key = normalize_phone(row.mobile_number, code)
		if not key:
			frappe.throw(f"Customer Contacts row {index}: Mobile Number is required.")
		if key in seen:
			frappe.throw(f"Customer Contacts row {index}: this number is already used in {seen[key]}.")
		row.contact_name = str(row.contact_name or "").strip()
		row.designation = str(row.designation or "").strip()
		if not row.contact_name:
			frappe.throw(f"Customer Contacts row {index}: Person Name is required.")
		row.mobile_number = "+" + key
		seen[key] = f"Customer Contacts row {index}"
	for key in sorted(seen):
		matches = _matches(key, doc.name or "", current=True)
		if matches:
			frappe.throw(f"Phone number +{key} is already linked to Customer {matches[0].name} ({matches[0].label}).")
