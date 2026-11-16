"""Reviewer-scoped matching; no writes to customer, stock or actual Orders."""
import frappe
from kunal_enterprises.api.quick_orders import _require_reviewer
from kunal_enterprises.integrations.order_intake_match_requests import save_matches


@frappe.whitelist(methods=['POST'])
def match_request(request, expected_modified):
	_require_reviewer()
	doc = frappe.get_doc('Order Intake Request', request, for_update=True)
	doc.check_permission('read'); doc.check_permission('write')
	if str(doc.modified) != str(expected_modified):
		frappe.throw('The request changed. Reload it before finding matches.', frappe.TimestampMismatchError)
	if doc.status not in {'Pending Review', 'In Review', 'Awaiting Confirmation'} or doc.order:
		frappe.throw('Only open intake drafts can be matched.')
	return save_matches(doc)
