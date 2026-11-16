"""Compact confirmed corrections, separate from unfinished reviewer edits."""
import hashlib

import frappe
from frappe.utils import now_datetime

from kunal_enterprises.integrations.order_intake_ai_input import model_messages

DT = 'Order Intake Match Evidence'
INQUIRIES = {'Stock Inquiry', 'Price Inquiry'}


def initial_values(request):
	"""Legacy drafts without an AI baseline cannot claim an AI correction."""
	try:
		value = frappe.parse_json(request.get('ai_initial_values') or '{}')
	except (TypeError, ValueError):
		return {}
	return value if isinstance(value, dict) else {}


def source_excerpt_details(request):
	"""Return compact business text and whether any source text was omitted."""
	names = [row.message for row in request.source_messages if row.message]
	if not names:
		return '', False
	rows = frappe.get_all('WhatsApp Message', filters={'name': ['in', names]},
		fields=['name', 'message', 'content_type', 'intake_original_type', 'intake_raw_payload'],
		limit_page_length=100)
	by_name = {row['name']: row for row in model_messages(rows)}
	text = '\n'.join(str(by_name[name].get('message') or '').strip()
		for name in names if name in by_name).strip()
	return text[:1000], len(text) > 1000 or bool(set(names) - by_name.keys())


def source_excerpt(request):
	"""Use only linked business message text; never copy media download URLs."""
	return source_excerpt_details(request)[0]


def feedback_fields(request, kind, row_key=None, excerpt=None, excerpt_truncated=False):
	"""Keep the AI's first selection and human reason alongside verified aliases."""
	baseline = initial_values(request)
	field = {'customer': 'customer', 'sales_employee': 'sales_employee',
		'item': 'item', 'godown': 'godown', 'request_type': 'request_type'}[kind]
	row = next((row for row in request.items if row.row_key == row_key), None) if kind in {'item', 'godown'} else None
	initial_items = baseline.get('items') if isinstance(baseline.get('items'), list) else []
	original = next((entry for entry in initial_items
		if isinstance(entry, dict) and entry.get('row_key') == row_key), {}) if row else baseline
	selected = row.get(field) if row else request.get(field)
	suggested = original.get(field)
	reason = (row.get('correction_reason') if row else None) or request.get('correction_reason') or ''
	if excerpt is None:
		excerpt, excerpt_truncated = source_excerpt_details(request)
	return dict(suggested_value=str(suggested or '')[:1000],
		was_corrected=int(field in original and (suggested or '') != (selected or '')),
		correction_reason=str(reason).strip()[:1000], message_excerpt=excerpt,
		source_excerpt_truncated=int(excerpt_truncated),
		confirmed_request_type=request.request_type)


def record_type_correction(request, order=None, excerpt=None, excerpt_truncated=False):
	"""Internal caller has locked and verified the confirmed persisted outcome."""
	baseline = initial_values(request)
	old = baseline.get('request_type')
	if not old or old == request.request_type or request.request_type not in INQUIRIES | {'Order'}:
		return 0
	# Retain the correction for audit even if its source is too long. Retrieval
	# excludes incomplete classification examples: a cropped tail may contain a
	# negation or confirmation that changes the intent.
	if excerpt is None:
		excerpt, excerpt_truncated = source_excerpt_details(request)
	if not excerpt:
		return 0
	from kunal_enterprises.integrations.order_intake_learning import normalize_text, _key
	from kunal_enterprises.kunal_enterprises.doctype.order_intake_request.order_intake_request import _sender_key
	confirmation = order or f'inquiry:{request.processed_at}'
	name = 'OIME-' + hashlib.sha256(f'{confirmation}:{request.name}:request_type'.encode()).hexdigest()[:40]
	if frappe.db.exists(DT, name):
		return 0
	stamp = now_datetime()
	values = dict(doctype=DT, name=name, kind='request_type', original_text=excerpt,
		normalized_text=normalize_text(excerpt), normalized_key=_key(excerpt), selected_master=request.request_type,
		whatsapp_account=request.whatsapp_account, sender=_sender_key(request.sender_number),
		customer_context=request.customer or '', source_request=request.name, source_order=order,
		row_key='request_type', reviewer=frappe.session.user, active=1,
		creation=stamp, modified=stamp, owner=frappe.session.user, modified_by=frappe.session.user,
		**feedback_fields(request, 'request_type', excerpt=excerpt, excerpt_truncated=excerpt_truncated))
	frappe.get_doc(values).db_insert()
	return 1


def record_inquiry_confirmation(request):
	"""Only an explicit handled inquiry may contribute classification feedback."""
	from kunal_enterprises.api.quick_orders import _require_reviewer
	_require_reviewer()
	request = frappe.get_doc('Order Intake Request', request if isinstance(request, str) else request.name, for_update=True)
	request.check_permission('read')
	request.check_permission('write')
	if (request.status != 'Resolved' or request.request_type not in INQUIRIES or request.order
		or not request.processed_at or not request.reviewed_by):
		frappe.throw('Learning requires a successfully handled stock or price inquiry')
	# Re-review is a new confirmation, not an opportunity for an older reason
	# or classification to become active again. A repeat of this same event is
	# idempotent, including when the final type now equals the original baseline.
	frappe.db.sql(f"""UPDATE `tab{DT}` SET active=0, modified=%s, modified_by=%s
		WHERE source_request=%s AND COALESCE(source_order,'')='' AND kind='request_type'
		AND active=1 AND creation < %s""",
		(now_datetime(), frappe.session.user, request.name, request.processed_at))
	if not request.whatsapp_account or not request.sender_number:
		return 0
	return record_type_correction(request)
