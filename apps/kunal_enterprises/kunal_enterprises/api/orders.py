import json
from collections import defaultdict
from html import escape

import frappe
from frappe.utils.file_manager import save_file
from frappe.utils.pdf import get_pdf
from frappe.utils import get_datetime, now_datetime

from kunal_enterprises.api.product_groups import get_allowed_product_groups
from kunal_enterprises.api.token_verification import verify_token
from kunal_enterprises.api.utils import create_success_response, handle_error_response


@frappe.whitelist(allow_guest=True, methods=["POST"])
def submit(customer, allocations, sales_employee=None, sales_employee_note=None, headers=None):
	try:
		token_error = _validate_submit_token(customer, sales_employee, headers)
		if token_error:
			return token_error
		order = submit_order(
			customer=customer,
			allocations=allocations,
			sales_employee=sales_employee,
			sales_employee_note=sales_employee_note,
		)
		return create_success_response(
			"Order placed",
			{
				"order": order.name,
				"portal_reference_number": order.portal_reference_number,
				"status": order.status,
				"total_item_count": order.total_item_count,
				"total_quantity": order.total_quantity,
			},
		)
	except Exception as error:
		return handle_error_response(error, "Unable to submit order")


@frappe.whitelist(allow_guest=True, methods=["GET"])
def history(customer=None, sales_employee=None, headers=None):
	try:
		token_error = _validate_order_token(customer, sales_employee, headers, "Order history")
		if token_error:
			return token_error
		_validate_order_history_access(customer, sales_employee)
		filters = {}
		if customer:
			filters["customer"] = customer
		if sales_employee:
			filters["sales_employee"] = sales_employee

		orders = frappe.get_all(
			"Order",
			filters=filters,
			fields=[
				"name",
				"portal_reference_number",
				"order_source",
				"customer",
				"sales_employee",
				"status",
				"confirmation_datetime",
				"total_item_count",
				"total_quantity",
			],
			order_by="confirmation_datetime desc",
		)

		return create_success_response(
			"Order history",
			{"orders": [_serialize_order_summary(order) for order in orders]},
		)
	except Exception as error:
		return handle_error_response(error, "Unable to load order history")


@frappe.whitelist(allow_guest=True, methods=["GET"])
def detail(order, customer=None, sales_employee=None, headers=None):
	try:
		token_error = _validate_order_token(customer, sales_employee, headers, "Order detail")
		if token_error:
			return token_error
		order_doc = frappe.get_doc("Order", order)
		_validate_order_detail_access(order_doc, customer, sales_employee)
		return create_success_response("Order detail", _serialize_order_detail(order_doc, customer, sales_employee))
	except Exception as error:
		return handle_error_response(error, "Unable to load order detail")


def submit_order(customer, allocations, sales_employee=None, sales_employee_note=None, confirmation_datetime=None):
	confirmation_datetime = get_datetime(confirmation_datetime) if confirmation_datetime else now_datetime()
	merged_allocations = _merge_allocations(allocations)
	allowed_group_names = {group["name"] for group in get_allowed_product_groups(customer, sales_employee)}
	items_by_name = _load_items([row["item"] for row in merged_allocations])
	_validate_active_godowns({row["godown"] for row in merged_allocations})

	item_rows = {}
	allocation_rows = []
	for allocation in merged_allocations:
		item = items_by_name.get(allocation["item"])
		if not item:
			frappe.throw(f"Item {allocation['item']} was not found or is inactive", title="Invalid Item")
		if item.root_stock_group not in allowed_group_names:
			frappe.throw(f"Item {item.name} is not allowed", title="Item Access Required")

		item_rows.setdefault(
			item.name,
			{
				"item": item.name,
				"item_name_at_order": item.item_name,
				"root_stock_group": item.root_stock_group,
				"unit": item.uom,
				"requested_quantity": 0,
				"fulfilled_quantity": 0,
				"pending_quantity": 0,
				"status": "Placed",
			},
		)
		item_rows[item.name]["requested_quantity"] += allocation["quantity"]
		item_rows[item.name]["pending_quantity"] += allocation["quantity"]
		allocation_rows.append(
			{
				"item": item.name,
				"godown": allocation["godown"],
				"requested_quantity": allocation["quantity"],
				"stock_shown_at_order_time": allocation.get("stock_shown_at_order_time") or 0,
				"stock_snapshot_at": allocation.get("stock_snapshot_at"),
				"fulfilled_quantity": 0,
				"pending_quantity": allocation["quantity"],
			}
		)

	order = frappe.get_doc(
		{
			"doctype": "Order",
			"portal_reference_number": _next_reference_number(confirmation_datetime),
			"order_source": "Sales Employee" if sales_employee else "Customer",
			"customer": customer,
			"sales_employee": sales_employee,
			"status": "Placed",
			"confirmation_datetime": confirmation_datetime,
			"sales_employee_note": sales_employee_note if sales_employee else None,
			"items": list(item_rows.values()),
			"godown_allocations": allocation_rows,
		}
	)
	order.insert(ignore_permissions=True)
	_create_order_confirmation_records(order)
	return order


def _validate_submit_token(customer, sales_employee=None, headers=None):
	return _validate_order_token(customer, sales_employee, headers, "Order submit")


def _validate_order_token(customer=None, sales_employee=None, headers=None, action="Order"):
	resolved_headers = _resolve_headers(headers)
	if resolved_headers is None:
		return None

	is_valid, result = verify_token(resolved_headers)
	if not is_valid:
		return result

	if sales_employee:
		if result["identity_type"] != "Sales Employee" or result["identity"] != sales_employee:
			frappe.throw(f"{action} token identity does not match Sales Employee", title="Token Identity Mismatch")
	elif result["identity_type"] != "Customer" or result["identity"] != customer:
		frappe.throw(f"{action} token identity does not match Customer", title="Token Identity Mismatch")

	return None


def _resolve_headers(headers=None):
	if headers is not None:
		return headers

	request = getattr(frappe.local, "request", None)
	if request and getattr(request, "headers", None):
		return request.headers
	return None


def _validate_order_history_access(customer, sales_employee=None):
	if not customer and not sales_employee:
		frappe.throw("Customer or Sales Employee is required", title="Order Access Required")
	if customer:
		customer_doc = frappe.get_doc("Customer", customer)
		if not customer_doc.customer_app_access:
			frappe.throw("Customer App Access is not active", title="Customer App Access Required")
	if sales_employee:
		sales_employee_doc = frappe.get_doc("Sales Employee", sales_employee)
		if sales_employee_doc.status != "Active":
			frappe.throw("Sales Employee is disabled", title="Sales Employee Access Required")


def _validate_order_detail_access(order, customer=None, sales_employee=None):
	if customer and order.customer != customer:
		frappe.throw("Order is not visible for this Customer", title="Order Access Required")
	if sales_employee:
		if order.sales_employee != sales_employee:
			frappe.throw("Order is not visible for this Sales Employee", title="Order Access Required")
		sales_employee_doc = frappe.get_doc("Sales Employee", sales_employee)
		if sales_employee_doc.status != "Active":
			frappe.throw("Sales Employee is disabled", title="Sales Employee Access Required")


def _serialize_order_summary(order):
	return {
		"name": order.name,
		"portal_reference_number": order.portal_reference_number,
		"order_source": order.order_source,
		"customer": order.customer,
		"customer_name": frappe.db.get_value("Customer", order.customer, "customer_name"),
		"sales_employee": order.sales_employee,
		"status": order.status,
		"display_status": _display_status(order.status),
		"confirmation_datetime": str(order.confirmation_datetime) if order.confirmation_datetime else None,
		"total_item_count": order.total_item_count,
		"total_quantity": order.total_quantity,
	}


def _serialize_order_detail(order, customer=None, sales_employee=None):
	return {
		**_serialize_order_summary(order),
		"placed_by": _placed_by(order, customer, sales_employee),
		"items": [
			{
				"item": row.item,
				"item_name": row.item_name_at_order,
				"root_stock_group": row.root_stock_group,
				"unit": row.unit,
				"requested_quantity": row.requested_quantity,
				"fulfilled_quantity": row.fulfilled_quantity,
				"pending_quantity": row.pending_quantity,
				"status": row.status,
			}
			for row in order.items
		],
		"godown_allocations": [
			{
				"item": row.item,
				"godown": row.godown,
				"requested_quantity": row.requested_quantity,
				"fulfilled_quantity": row.fulfilled_quantity,
				"pending_quantity": row.pending_quantity,
			}
			for row in order.godown_allocations
		],
	}


def _display_status(status):
	if status == "Manual Review":
		return "Under Review"
	return status


def _placed_by(order, customer=None, sales_employee=None):
	if order.order_source == "Customer":
		return "You" if customer and order.customer == customer else "Customer"
	if sales_employee and order.sales_employee == sales_employee:
		return "You"
	return frappe.db.get_value("Sales Employee", order.sales_employee, "sales_employee_name") or "Sales Employee"


def _create_order_confirmation_records(order):
	summary_text = _build_customer_pdf_summary(order)
	pdf = frappe.get_doc(
		{
			"doctype": "Order PDF",
			"order": order.name,
			"customer": order.customer,
			"status": "Generated",
			"summary_text": summary_text,
			"generated_at": now_datetime(),
		}
	).insert(ignore_permissions=True)
	file_doc = _attach_order_pdf_file(pdf, order, summary_text)
	pdf.file_url = file_doc.file_url
	pdf.save(ignore_permissions=True)
	customer_mobile = frappe.db.get_value("Customer", order.customer, "mobile_number")
	frappe.get_doc(
		{
			"doctype": "Order WhatsApp Notification",
			"order": order.name,
			"recipient_type": "Customer",
			"recipient_customer": order.customer,
			"mobile_number": customer_mobile,
			"order_pdf": pdf.name,
			"status": "Queued",
			"request_payload": json.dumps(
				{
					"event": "Order Placed",
					"order": order.name,
					"portal_reference_number": order.portal_reference_number,
					"recipient": order.customer,
					"mobile_number": customer_mobile,
					"order_pdf": pdf.name,
				},
				sort_keys=True,
			),
			"provider_response": json.dumps(
				{
					"provider": "frappe_whatsapp",
					"status": "Queued",
					"retry_count": 0,
					"message": "Queued for WhatsApp provider dispatch",
				},
				sort_keys=True,
			),
			"created_at": now_datetime(),
		}
	).insert(ignore_permissions=True)


def _build_customer_pdf_summary(order):
	lines = [
		f"Order: {order.portal_reference_number}",
		f"Placed by: {_customer_pdf_placed_by(order)}",
		"Items:",
	]
	for allocation in order.godown_allocations:
		item_name = frappe.db.get_value("Tally Item", allocation.item, "item_name") or allocation.item
		lines.append(
			f"- {item_name} | Godown: {allocation.godown} | Quantity: {allocation.requested_quantity:g}"
		)
	return "\n".join(lines)


def _attach_order_pdf_file(pdf, order, summary_text):
	html = _build_order_pdf_html(order, summary_text)
	try:
		content = get_pdf(html)
	except OSError:
		content = _build_plain_text_pdf(summary_text)
	return save_file(
		f"{order.portal_reference_number}.pdf",
		content,
		pdf.doctype,
		pdf.name,
		is_private=1,
	)


def _build_order_pdf_html(order, summary_text):
	escaped_lines = [escape(line) for line in summary_text.splitlines()]
	body = "".join(f"<p>{line}</p>" for line in escaped_lines)
	return f"""
		<html>
			<head>
				<meta charset="utf-8">
				<style>
					body {{ font-family: Arial, sans-serif; font-size: 12px; color: #111; }}
					h1 {{ font-size: 18px; margin: 0 0 16px; }}
					p {{ margin: 0 0 8px; }}
				</style>
			</head>
			<body>
				<h1>Order Summary</h1>
				{body}
			</body>
		</html>
	"""


def _build_plain_text_pdf(text):
	lines = text.splitlines() or ["Order Summary"]
	content_lines = ["BT", "/F1 11 Tf", "50 790 Td", "14 TL"]
	for line in lines:
		content_lines.append(f"({_escape_pdf_text(line)}) Tj")
		content_lines.append("T*")
	content_lines.append("ET")
	stream = "\n".join(content_lines).encode("latin-1", "replace")

	objects = [
		b"<< /Type /Catalog /Pages 2 0 R >>",
		b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
		b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
		b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
		b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
	]
	pdf = bytearray(b"%PDF-1.4\n")
	offsets = [0]
	for index, obj in enumerate(objects, start=1):
		offsets.append(len(pdf))
		pdf.extend(f"{index} 0 obj\n".encode())
		pdf.extend(obj)
		pdf.extend(b"\nendobj\n")
	xref_at = len(pdf)
	pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
	pdf.extend(b"0000000000 65535 f \n")
	for offset in offsets[1:]:
		pdf.extend(f"{offset:010d} 00000 n \n".encode())
	pdf.extend(
		f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
	)
	return bytes(pdf)


def _escape_pdf_text(text):
	return str(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _customer_pdf_placed_by(order):
	if order.order_source == "Customer":
		return "Customer"
	return frappe.db.get_value("Sales Employee", order.sales_employee, "sales_employee_name") or "Sales Employee"


def _merge_allocations(allocations):
	if not allocations:
		frappe.throw("Order must contain at least one allocation")

	merged = defaultdict(float)
	allocation_metadata = {}
	for allocation in allocations:
		item = allocation.get("item")
		godown = allocation.get("godown")
		quantity = float(allocation.get("quantity") or 0)
		if not item or not godown:
			frappe.throw("Item and godown are required for every allocation")
		if quantity <= 0:
			frappe.throw("Order Quantity must be positive")

		key = (item, godown)
		merged[key] += quantity
		allocation_metadata.setdefault(
			key,
			{
				"stock_shown_at_order_time": allocation.get("stock_shown_at_order_time") or 0,
				"stock_snapshot_at": allocation.get("stock_snapshot_at"),
			},
		)

	return [
		{
			"item": item,
			"godown": godown,
			"quantity": quantity,
			**allocation_metadata[(item, godown)],
		}
		for (item, godown), quantity in merged.items()
	]


def _load_items(item_names):
	return {
		item.name: item
		for item in frappe.get_all(
			"Tally Item",
			filters={"name": ("in", item_names), "is_active": 1},
			fields=["name", "item_name", "root_stock_group", "uom"],
		)
	}


def _validate_active_godowns(godown_names):
	if not frappe.db.count("Tally Godown"):
		return

	active_godowns = set(
		frappe.get_all(
			"Tally Godown",
			filters={"name": ("in", tuple(godown_names)), "is_active": 1},
			pluck="name",
		)
	)
	for godown in godown_names:
		if godown not in active_godowns:
			frappe.throw(f"Godown {godown} is not active or was not found", title="Godown Access Required")


def _next_reference_number(confirmation_datetime):
	period = confirmation_datetime.strftime("%y-%m")
	current_number = frappe.db.get_value(
		"Order Reference Sequence",
		period,
		"current_number",
		for_update=True,
	)
	if current_number is not None:
		next_number = int(current_number) + 1
		frappe.db.set_value("Order Reference Sequence", period, "current_number", next_number)
	else:
		next_number = 1
		frappe.get_doc(
			{
				"doctype": "Order Reference Sequence",
				"period": period,
				"current_number": next_number,
			}
		).insert(ignore_permissions=True)

	return f"KE-{period}-{next_number:04d}"
