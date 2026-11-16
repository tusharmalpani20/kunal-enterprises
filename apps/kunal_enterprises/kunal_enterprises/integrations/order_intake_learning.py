"""Confirmed, chat-scoped aliases; drafts never contribute learning evidence.

The later conversion transaction must call record_confirmation after persisting
both records. Nothing here commits, creates an Order, or exposes a write API.
"""
import hashlib
import re

import frappe
from frappe.utils import now_datetime

DT = "Order Intake Match Evidence"
MASTERS = {"customer": ("Customer", "customer_name"), "sales_employee": ("Sales Employee", "sales_employee_name"),
	"item": ("Tally Item", "item_name"), "godown": ("Tally Godown", "godown_name")}


def normalize_text(value):
	# Keep punctuation, numbers and abbreviations. In particular MR and MR+ are
	# different aliases; no catalogue-specific semantic rule belongs here.
	return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _key(value):
	return hashlib.sha256(normalize_text(value).encode()).hexdigest()


def record_confirmation(request, order):
	"""Write verified selections in the caller's Order-conversion transaction."""
	from kunal_enterprises.api.quick_orders import _require_reviewer
	from kunal_enterprises.kunal_enterprises.doctype.order_intake_request.order_intake_request import _sender_key
	_require_reviewer()
	request = frappe.get_doc("Order Intake Request", request if isinstance(request, str) else request.name, for_update=True)
	order = frappe.get_doc("Order", order if isinstance(order, str) else order.name, for_update=True)
	request.check_permission("read")
	if request.status != "Converted to Order" or request.order != order.name:
		frappe.throw("Learning requires a successfully converted intake request")
	if order.status == "Cancelled" or order.docstatus == 2 or order.customer != request.customer:
		frappe.throw("Learning requires the matching, non-cancelled Order")
	if (order.sales_employee or None) != (request.sales_employee or None):
		frappe.throw("Confirmed salesperson does not match the Order")
	if not request.whatsapp_account or not request.sender_number:
		return 0
	items = {row.item for row in order.items}
	pairs = {(row.item, row.godown) for row in order.godown_allocations}
	for row in request.items:
		if row.item and row.item not in items:
			frappe.throw("Confirmed intake item is absent from the Order")
		if row.godown and (row.item, row.godown) not in pairs:
			frappe.throw("Confirmed dispatch warehouse is absent from the Order item")
	entries = [("customer", "customer", request.get("customer_text"), request.customer, ""),
		("sales_employee", "sales_employee", request.get("salesperson_text"), request.sales_employee, "")]
	for row in request.items:
		entries.extend([("item", row.row_key, row.original_text, row.item, request.customer),
			("godown", row.row_key, row.warehouse_text, row.godown, request.customer)])
	from kunal_enterprises.integrations.order_intake_feedback import feedback_fields, source_excerpt_details, record_type_correction
	excerpt, excerpt_truncated = source_excerpt_details(request)
	stamp, count = now_datetime(), 0
	for kind, row_key, original, selected, customer in entries:
		if not selected or not normalize_text(original):
			continue
		if not frappe.db.exists(MASTERS[kind][0], selected):
			frappe.throw("Confirmed master selection no longer exists")
		name = "OIME-" + hashlib.sha256(f"{order.name}:{request.name}:{kind}:{row_key}".encode()).hexdigest()[:40]
		if frappe.db.exists(DT, name):
			continue
		values = dict(doctype=DT, name=name, kind=kind, original_text=original, normalized_text=normalize_text(original),
			normalized_key=_key(original), selected_master=selected, whatsapp_account=request.whatsapp_account,
			sender=_sender_key(request.sender_number), customer_context=customer or "", source_request=request.name,
			source_order=order.name, row_key=row_key, reviewer=frappe.session.user, active=1,
			creation=stamp, modified=stamp, owner=frappe.session.user, modified_by=frappe.session.user,
			**feedback_fields(request, kind, row_key, excerpt=excerpt, excerpt_truncated=excerpt_truncated))
		# Raw insertion is deliberately private: the DocType rejects all ordinary
		# document writes, including administrator REST writes.
		frappe.get_doc(values).db_insert()
		count += 1
	return count + record_type_correction(request, order.name, excerpt=excerpt, excerpt_truncated=excerpt_truncated)


def lookup_confirmed(kind, text, account, sender, customer=None):
	"""Return only confirmed evidence from this receiving account and sender."""
	from kunal_enterprises.kunal_enterprises.doctype.order_intake_request.order_intake_request import _sender_key
	empty = dict(candidates=[], selected=None, overflow=False)
	if kind not in MASTERS or not normalize_text(text) or not account or not sender:
		return empty
	if kind in {"item", "godown"} and not customer:
		return empty
	context = customer if kind in {"item", "godown"} else ""
	valid_selection = {
		"customer": "e.selected_master=o.customer",
		"sales_employee": "e.selected_master=o.sales_employee",
		"item": "EXISTS (SELECT 1 FROM `tabOrder Item` i WHERE i.parent=o.name AND i.item=e.selected_master)",
		"godown": "EXISTS (SELECT 1 FROM `tabOrder Godown Allocation` a INNER JOIN `tabOrder Intake Item` i ON i.parent=r.name AND i.row_key=e.row_key WHERE a.parent=o.name AND a.item=i.item AND a.godown=e.selected_master)",
	}[kind]
	rows = frappe.db.sql(f"""SELECT DISTINCT e.selected_master FROM `tab{DT}` e
		INNER JOIN `tabOrder` o ON o.name=e.source_order
		INNER JOIN `tabOrder Intake Request` r ON r.name=e.source_request
		WHERE e.active=1 AND e.kind=%s AND e.normalized_key=%s
		AND e.whatsapp_account=%s AND e.sender=%s AND COALESCE(e.customer_context,'')=%s
		AND o.status!='Cancelled' AND o.docstatus!=2 AND r.status='Converted to Order'
		AND r.`order`=o.name AND r.customer=o.customer AND {valid_selection}
		ORDER BY e.selected_master LIMIT 41""", (kind, _key(text), account, _sender_key(sender), context), as_dict=True)
	candidates = []
	master, label = MASTERS[kind]
	filters = {"name": ("in", [row.selected_master for row in rows])}
	if kind in {'item', 'godown'}:
		filters['is_active'] = 1
	labels = {row.name: row.get(label) for row in frappe.get_all(master,
		filters=filters, fields=["name", label], limit_page_length=41)} if rows else {}
	for row in rows:
		if row.selected_master in labels:
			candidates.append(dict(name=row.selected_master, label=labels[row.selected_master] or row.selected_master, score=100,
				reason="Previously confirmed for this chat"))
	overflow = len(rows) > 40
	return dict(candidates=candidates[:5], selected=candidates[0]["name"] if len(candidates) == 1 and not overflow else None,
		overflow=overflow or len(candidates) > 5)


def order_changed(doc, method=None):
	"""Cancellation invalidates active contributions, keeping the audit trail."""
	if doc.status == "Cancelled" or doc.docstatus == 2:
		frappe.db.sql(f"UPDATE `tab{DT}` SET active=0, modified=%s, modified_by=%s WHERE source_order=%s AND active=1",
			(now_datetime(), frappe.session.user, doc.name))
