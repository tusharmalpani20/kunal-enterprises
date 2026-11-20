"""Portal-confirmed intake Orders and their private customer confirmation PDFs."""
import math

import frappe
from frappe.utils import now_datetime

from kunal_enterprises.api.orders import (
	_merge_allocations, _next_reference_number,
	_build_customer_pdf_summary, _attach_order_pdf_file,
)
from kunal_enterprises.kunal_enterprises.doctype.customer.customer import CLOSED_TALLY_LEDGER_RE


def create_order(request):
	customer = frappe.get_doc('Customer', request.customer, for_update=True)
	# Customer's normal linking UI connects by Client Code, not its legacy GUID.
	if not (customer.client_code or '').strip():
		frappe.throw('Connect the customer to Tally before creating the Order.')
	ledger = frappe.get_doc('Tally Customer Ledger', {'client_code': customer.client_code}, for_update=True)
	if not ledger.is_active or CLOSED_TALLY_LEDGER_RE.search(ledger.ledger_name or ''):
		frappe.throw('Connect the customer to an active Tally ledger before creating the Order.')
	if request.sales_employee:
		frappe.get_doc('Sales Employee', request.sales_employee, for_update=True)
	if not request.items or len(request.items) > 100:
		frappe.throw('Select between 1 and 100 item rows before creating the Order.')
	if any(row.get('quantity_unknown') for row in request.items):
		frappe.throw('Confirm the requested quantity for every item before creating the Order.')
	allocations = _merge_allocations([dict(item=row.item, quantity=row.quantity, godown=row.godown) for row in request.items])
	# Lock chosen masters so activity or identity cannot change during creation.
	masters = {}
	for doctype, names in (('Tally Item', {row['item'] for row in allocations}),
		('Tally Godown', {row['godown'] for row in allocations if row['godown']})):
		masters[doctype] = {}
		for name in sorted(names):
			master = frappe.get_doc(doctype, name, for_update=True)
			if not master.is_active:
				frappe.throw(f'Select an active {doctype}: {name}.')
			masters[doctype][name] = master
	# Keep the locked current rows: a nonlocking reread may see the transaction's
	# older repeatable-read snapshot, including a now-disabled master or old UOM.
	items = masters['Tally Item']
	for row in request.items:
		item = items.get(row.item)
		if not item:
			frappe.throw('Every row must select an active Tally Item.')
		# Incoming units are descriptive labels. Keep the quantity unchanged;
		# the Order carries its selected item's canonical Tally unit below.
	item_rows, allocation_rows = {}, []
	for allocation in allocations:
		item = items[allocation['item']]
		item_rows.setdefault(item.name, dict(item=item.name, item_name_at_order=item.item_name,
			root_stock_group=item.root_stock_group, unit=item.uom, requested_quantity=0,
			fulfilled_quantity=0, pending_quantity=0, status='Placed'))
		item_rows[item.name]['requested_quantity'] += allocation['quantity']
		item_rows[item.name]['pending_quantity'] += allocation['quantity']
		if not math.isfinite(item_rows[item.name]['requested_quantity']):
			frappe.throw('Total item quantity must be finite and positive.')
		allocation_rows.append(dict(item=item.name, godown=allocation['godown'], requested_quantity=allocation['quantity'],
			fulfilled_quantity=0, pending_quantity=allocation['quantity'], stock_shown_at_order_time=0))
	stamp = now_datetime()
	order = frappe.get_doc(dict(doctype='Order', portal_reference_number=_next_reference_number(stamp),
		order_source='Sales Employee' if request.sales_employee else 'Customer', customer=request.customer,
		sales_employee=request.sales_employee, status='Placed', confirmation_datetime=stamp,
		order_intake_request=request.name, items=list(item_rows.values()), godown_allocations=allocation_rows))
	order.flags.in_order_intake_conversion = True
	order.insert(ignore_permissions=True)
	return order


def intake_pdf_summary(order):
	"""Keep customer identity explicit when a salesperson places the intake Order."""
	summary = _build_customer_pdf_summary(order)
	customer = frappe.db.get_value('Customer', order.customer, 'customer_name') or order.customer
	heading, separator, remainder = summary.partition('\n')
	return f"{heading}\nCustomer: {customer}" + (separator + remainder if separator else '')


def create_pdf(order):
	"""Generate the private PDF separately from the sales alert."""
	summary = intake_pdf_summary(order)
	pdf = frappe.get_doc(dict(doctype='Order PDF', order=order.name, customer=order.customer,
		status='Generated', summary_text=summary, generated_at=now_datetime())).insert(ignore_permissions=True)
	file = _attach_order_pdf_file(pdf, order, summary)
	pdf.flags.intake_pdf_file = file
	try:
		pdf.file_url = file.file_url
		pdf.save(ignore_permissions=True)
	except Exception:
		file.on_rollback()
		raise
	return pdf
