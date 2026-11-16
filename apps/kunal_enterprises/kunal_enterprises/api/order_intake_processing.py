"""Explicit, atomic portal review actions; never a mobile authorization bypass."""
from uuid import uuid4

import frappe
from frappe.utils import now_datetime

from kunal_enterprises.api.quick_orders import _require_reviewer
from kunal_enterprises.api.order_intake_conversation import _messages
from kunal_enterprises.integrations.order_intake_order import create_order, create_pdf
from kunal_enterprises.integrations.order_intake_learning import record_confirmation
from kunal_enterprises.integrations.order_intake_feedback import record_inquiry_confirmation

OPEN_STATUSES = {'Pending Review', 'In Review', 'Awaiting Confirmation'}
INQUIRIES = {'Stock Inquiry', 'Price Inquiry'}


def _locked_request(request):
	_require_reviewer()
	if not isinstance(request, str) or not request.strip():
		frappe.throw('Choose a saved Order Intake Request.')
	first = frappe.get_doc('Order Intake Request', request)
	first.check_permission('read'); first.check_permission('write')
	if first.whatsapp_account:
		from kunal_enterprises.integrations.order_intake_queue import _lock_account
		frappe.get_doc('WhatsApp Account', first.whatsapp_account).check_permission('read')
		_lock_account(first.whatsapp_account)
	doc = frappe.get_doc('Order Intake Request', request, for_update=True)
	doc.check_permission('read'); doc.check_permission('write')
	if doc.whatsapp_account != first.whatsapp_account:
		frappe.throw('The receiving account changed. Reload before processing.', frappe.TimestampMismatchError)
	return doc


def _review_fence(doc, expected_modified, revision):
	if not expected_modified or str(expected_modified) != str(doc.modified):
		frappe.throw('The request changed. Reload it before processing.', frappe.TimestampMismatchError)
	if not isinstance(revision, str) or not revision:
		frappe.throw('Review the current messages before processing.')
	_messages(doc.name, revision=revision, expected_modified=expected_modified, limit=1, lock=True)
	updates = frappe.parse_json(doc.proposed_updates or '[]')
	if not isinstance(updates, list) or any(not isinstance(row, dict) or not row.get('reviewed_at') for row in updates):
		frappe.throw('Review pending message updates before processing this request.')


def _result(doc, order=None):
	return dict(state=doc.status, request=doc.name, order=doc.order,
		portal_reference_number=order.portal_reference_number if order else None,
		godown_assignment_pending=bool(order.godown_assignment_pending) if order else False)


def _existing_order(doc):
	if doc.status != 'Converted to Order' or not doc.order:
		return None
	order = frappe.get_doc('Order', doc.order)
	order.check_permission('read')
	if order.order_intake_request != doc.name or order.customer != doc.customer:
		frappe.throw('The converted Order link needs administrator review.')
	return order


@frappe.whitelist(methods=['POST'])
def convert(request, expected_modified=None, revision=None):
	doc = _locked_request(request)
	order = _existing_order(doc)
	if order:
		return _result(doc, order)
	if doc.status not in OPEN_STATUSES or doc.order or doc.request_type != 'Order':
		frappe.throw('Only an open request classified as Order can create an Order. Separate mixed requests and confirm the request type first.')
	if not doc.customer:
		frappe.throw('Select the customer before creating the Order.')
	point = 'intake_convert_' + uuid4().hex
	frappe.db.savepoint(point)
	pdf = None
	try:
		_review_fence(doc, expected_modified, revision)
		order = create_order(doc)
		doc.order = order.name
		doc.status = 'Converted to Order'
		doc.reviewed_by = frappe.session.user
		doc.processed_at = now_datetime()
		doc.flags.in_order_intake_conversion = True
		doc.save()
		pdf = create_pdf(order)
		record_confirmation(doc.name, order.name)
		frappe.db.release_savepoint(point)
		return _result(doc, order)
	except Exception:
		frappe.db.rollback(save_point=point)
		# Savepoints only revert SQL, so remove a newly written private PDF too.
		if pdf and pdf.flags.intake_pdf_file:
			pdf.flags.intake_pdf_file.on_rollback()
		raise


@frappe.whitelist(methods=['POST'])
def handle_inquiry(request, expected_modified=None, revision=None):
	doc = _locked_request(request)
	if doc.status == 'Resolved' and doc.request_type in INQUIRIES and not doc.order and doc.processed_at:
		return _result(doc)
	if doc.status not in OPEN_STATUSES or doc.order or doc.request_type not in INQUIRIES:
		frappe.throw('Only an open stock or price inquiry can be marked handled.')
	_review_fence(doc, expected_modified, revision)
	point = 'intake_inquiry_' + uuid4().hex
	frappe.db.savepoint(point)
	try:
		doc.status = 'Resolved'
		doc.reviewed_by = frappe.session.user
		doc.processed_at = now_datetime()
		doc.flags.in_order_intake_transition = True
		doc.save()
		record_inquiry_confirmation(doc.name)
		frappe.db.release_savepoint(point)
		return _result(doc)
	except Exception:
		frappe.db.rollback(save_point=point)
		raise
