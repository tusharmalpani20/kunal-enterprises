"""Narrow sales corrections and attributable, non-blocking intake approval."""
import hashlib
import json
import math

import frappe
from frappe.utils import now_datetime, get_datetime

AUDIT_FIELDS = ('sales_approval_status', 'sales_approved_by', 'sales_approved_at',
    'sales_approval_fingerprint', 'sales_approval_history')
OPEN = {'Pending Review', 'In Review', 'Awaiting Confirmation'}


def fingerprint(doc):
    payload = {'customer': doc.customer or '', 'items': sorted([
        [row.row_key, row.item or '', float(row.quantity or 0), bool(row.quantity_unknown), row.godown or '']
        for row in doc.items], key=lambda row: row[0] or '')}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def guard_approval(doc, before):
    # All save paths, including admin corrections and AI updates, invalidate a
    # changed approval. Keep its author/time and history as an audit record.
    if not frappe.flags.sales_portal_write:
        for field in AUDIT_FIELDS:
            current = doc.get(field) or ''
            previous = before.get(field) or '' if before else ''
            if field == 'sales_approved_at':
                current = get_datetime(current) if current else ''
                previous = get_datetime(previous) if previous else ''
            if current != previous:
                # Defaults on a new document do not constitute a forged approval.
                if not before and field == 'sales_approval_status' and doc.get(field) == 'Not Approved':
                    continue
                frappe.throw('Sales approval fields are managed by the sales review action.', frappe.PermissionError)


def finalize_approval(doc, before):
    # Run after legacy layout and quantity normalization, on the values that
    # will actually be persisted. The server-only action flag is not Doc.flags.
    current = fingerprint(doc)
    if frappe.flags.sales_portal_approving:
        doc.sales_approval_fingerprint = current
        history = frappe.parse_json(doc.sales_approval_history or '[]')
        history[-1]['fingerprint'] = current
        doc.sales_approval_history = json.dumps(history)
    elif before and before.sales_approval_status == 'Approved' and current != before.sales_approval_fingerprint:
        doc.sales_approval_status = 'Needs Reapproval'


def _request(name, expected_modified):
    from kunal_enterprises.permission_guards.sales_portal import employee_for_user, can_access
    employee = employee_for_user()
    if not employee:
        frappe.throw('An active linked sales portal user is required.', frappe.PermissionError)
    doc = frappe.get_doc('Order Intake Request', name, for_update=True)
    if not can_access(doc):
        frappe.throw('This intake request is outside your sales access.', frappe.PermissionError)
    doc.check_permission('read')
    if not expected_modified or str(doc.modified) != str(expected_modified):
        frappe.throw('The request changed. Reload before saving.', frappe.TimestampMismatchError)
    if doc.status not in OPEN or doc.order:
        frappe.throw('Only open intake requests can be corrected or approved.')
    return employee, doc


def _save(doc, approving=False):
    previous = frappe.flags.sales_portal_write
    previous_approving = frappe.flags.sales_portal_approving
    try:
        frappe.flags.sales_portal_write = True
        frappe.flags.sales_portal_approving = approving
        doc.save(ignore_permissions=True)
    finally:
        frappe.flags.sales_portal_write = previous
        frappe.flags.sales_portal_approving = previous_approving
    return {'request': doc.name, 'modified': str(doc.modified), 'approval_status': doc.sales_approval_status}


@frappe.whitelist(methods=['POST'])
def correct(request, expected_modified, customer, items):
    employee, doc = _request(request, expected_modified)
    if customer is not None and not isinstance(customer, str):
        frappe.throw("Choose an existing customer.")
    customer = customer or ""
    # Even an owned order cannot be reassigned to an unassigned customer.
    assigned = {row.customer for row in employee.assigned_customers if row.customer}
    if customer != (doc.customer or '') and customer not in assigned:
        frappe.throw('Choose a customer assigned to your Sales Employee.', frappe.PermissionError)
    if customer and not frappe.db.exists('Customer', customer):
        frappe.throw('Choose an existing customer.')
    rows = frappe.parse_json(items) if isinstance(items, str) else items
    if not isinstance(rows, list) or len(rows) != len(doc.items):
        frappe.throw('Sales corrections cannot add or remove item rows.')
    keyed = {}
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'row_key', 'item', 'quantity', 'godown'}
                or not isinstance(row['row_key'], str) or row['row_key'] in keyed):
            frappe.throw('Provide each existing item row once with only item, quantity and godown.')
        keyed[row['row_key']] = row
    if set(keyed) != {row.row_key for row in doc.items}:
        frappe.throw('Item rows changed. Reload before saving.')
    doc.customer = customer
    for row in doc.items:
        change = keyed[row.row_key]
        for field, doctype in (('item', 'Tally Item'), ('godown', 'Tally Godown')):
            value = change[field]
            if value and (not isinstance(value, str) or not frappe.db.exists(doctype, value)):
                frappe.throw('Select an existing item and godown.')
            row.set(field, value or None)
        value = change['quantity']
        if value in (None, '') and row.quantity_unknown:
            # A partial review must not turn an unresolved quantity into zero.
            continue
        try:
            quantity = float(value)
        except (ValueError, TypeError, OverflowError):
            frappe.throw('Enter a valid quantity.')
        if isinstance(value, bool) or not math.isfinite(quantity) or quantity < 0:
            frappe.throw('Enter a finite non-negative quantity.')
        row.quantity = quantity
        row.quantity_unknown = 0
    return _save(doc)


@frappe.whitelist(methods=['POST'])
def approve(request, expected_modified):
    employee, doc = _request(request, expected_modified)
    current = fingerprint(doc)
    if doc.sales_approval_status == 'Approved' and doc.sales_approval_fingerprint == current:
        return {'request': doc.name, 'modified': str(doc.modified), 'approval_status': 'Approved'}
    stamp = str(now_datetime())
    history = frappe.parse_json(doc.sales_approval_history or '[]')
    history.append({'approved_by': frappe.session.user, 'approved_at': stamp,
        'sales_employee': employee.name, 'fingerprint': current})
    doc.update(dict(sales_approved_by=frappe.session.user, sales_approved_at=stamp,
        sales_approval_status='Approved', sales_approval_fingerprint=current,
        sales_approval_history=json.dumps(history)))
    return _save(doc, approving=True)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def customer_query(doctype, txt, searchfield, start, page_len, filters):
    from kunal_enterprises.permission_guards.sales_portal import employee_for_user
    employee = employee_for_user()
    if not employee:
        frappe.throw('A linked sales portal user is required.', frappe.PermissionError)
    names = [row.customer for row in employee.assigned_customers if row.customer]
    if not names:
        return []
    rows = frappe.get_all('Customer', filters={'name': ['in', names]},
        or_filters=[['name', 'like', '%' + txt + '%'], ['customer_name', 'like', '%' + txt + '%']],
        fields=['name', 'customer_name'], limit_start=max(int(start), 0), limit_page_length=min(max(int(page_len), 1), 40))
    return [[row.name, row.customer_name] for row in rows]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def master_query(doctype, txt, searchfield, start, page_len, filters):
    from kunal_enterprises.permission_guards.sales_portal import employee_for_user
    if not employee_for_user() or doctype not in {'Tally Item', 'Tally Godown'}:
        frappe.throw('Sales intake lookup is not permitted.', frappe.PermissionError)
    label = 'item_name' if doctype == 'Tally Item' else 'godown_name'
    rows = frappe.get_all(doctype, fields=['name', label],
        or_filters=[['name', 'like', '%' + txt + '%'], [label, 'like', '%' + txt + '%']],
        order_by='name', limit_start=max(int(start), 0), limit_page_length=min(max(int(page_len), 1), 40))
    return [[row.name, row.get(label)] for row in rows]
