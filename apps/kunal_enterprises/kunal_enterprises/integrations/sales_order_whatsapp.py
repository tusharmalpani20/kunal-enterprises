"""Text confirmations for sales employees assigned to a placed Order."""

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from functools import partial
from hashlib import sha256
from ipaddress import ip_address
import re
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import frappe
import requests
from frappe.utils import get_system_timezone, now_datetime

from kunal_enterprises.integrations.customer_contacts import normalize_phone, phone_sql

NOTIFICATION = 'Order WhatsApp Notification'
JOB = 'kunal_enterprises.integrations.sales_order_whatsapp.dispatch'
CLAIM_TIMEOUT = timedelta(minutes=5)


def queue_order(order, method=None):
	"""Write one durable sales dispatch per eligible employee in the Order transaction."""
	if order.status != 'Placed' or not order.customer or frappe.flags.in_import or frappe.flags.in_patch:
		return
	intake_sender = _intake_sender(order)
	placing_employee = None if order.order_intake_request else order.sales_employee
	employees = frappe.db.sql('''
		SELECT DISTINCT e.name, e.mobile_number FROM `tabSales Employee Assigned Customer` a
		JOIN `tabSales Employee` e ON e.name=a.parent
		WHERE a.parenttype='Sales Employee' AND a.parentfield='assigned_customers'
			AND a.customer=%s AND e.name<>%s AND e.status='Active'
			AND COALESCE(e.sales_order_whatsapp_opt_out,0)=0
		ORDER BY e.name
	''', (order.customer, placing_employee or ''), as_dict=True)
	for employee in employees:
		if intake_sender and normalize_phone(employee.mobile_number, strict=False) == intake_sender:
			continue
		key = sha256(f'{order.name}\0{employee.name}'.encode()).hexdigest()
		if frappe.db.exists(NOTIFICATION, {'sales_dispatch_key': key}):
			continue
		notification = frappe.get_doc(dict(doctype=NOTIFICATION, order=order.name,
			recipient_type='Sales Employee', recipient_sales_employee=employee.name, mobile_number=employee.mobile_number,
			order_customer=order.customer, sales_dispatch_key=key, status='Queued', created_at=now_datetime())).insert(ignore_permissions=True)
		frappe.db.after_commit.add(partial(_publish, notification.name))


def _publish(name):
	try:
		frappe.enqueue(JOB, queue='short', timeout=90, job_id=f'sales-order-whatsapp-{name}',
			deduplicate=True, name=name)
	except Exception:
		# The scheduler can recover a dispatch if Redis was temporarily unavailable.
		frappe.logger('sales_order_whatsapp').warning('Could not publish dispatch %s', name)


def tick():
	# A worker stopped after claiming a notification may already have sent it.
	# Mark those attempts for review without automatically sending them again.
	jobs = frappe.qb.DocType(NOTIFICATION)
	(frappe.qb.update(jobs).set(jobs.status, 'Failed')
		.set(jobs.skip_reason, 'Dispatch outcome unknown. Check WhatsApp before resending.')
		.where((jobs.recipient_type == 'Sales Employee') & jobs.sales_dispatch_key.notnull()
			& (jobs.status == 'Sending') & (jobs.modified < now_datetime() - CLAIM_TIMEOUT))).run()
	for name in frappe.get_all(NOTIFICATION, filters={'recipient_type': 'Sales Employee',
		'status': 'Queued', 'sales_dispatch_key': ('is', 'set')}, pluck='name', order_by='creation', limit_page_length=100):
		frappe.db.after_commit.add(partial(_publish, name))


def _portal_link(order):
	base = str(frappe.conf.get('sales_portal_url') or frappe.conf.get('host_name') or '').strip()
	try:
		parts = urlsplit(base)
		host = parts.hostname or ''
		port = parts.port  # Parsing the port rejects malformed configured URLs.
		if (parts.scheme != 'https' or '.' not in host or host.rstrip('.').endswith('.localhost')
				or parts.username or parts.password or parts.query or parts.fragment or len(base) > 500
				or port == 0 or '\\' in base or any(char.isspace() for char in base)):
			return None
		if re.fullmatch(r'[\d.]+', host) and not ip_address(host).is_global:
			return None
	except ValueError:
		return None
	return f"{base.rstrip('/')}/app/order/{quote(order, safe='')}"


def _default_account():
	accounts = frappe.get_all('WhatsApp Account', filters={'status': 'Active', 'is_default_outgoing': 1},
		pluck='name', limit_page_length=2)
	return frappe.get_doc('WhatsApp Account', accounts[0]) if len(accounts) == 1 else None


def _intake_sender(order):
	if not order.order_intake_request:
		return None
	request = frappe.db.get_value('Order Intake Request', order.order_intake_request, ['source', 'sender_number'], as_dict=True)
	return normalize_phone(request.sender_number, strict=False, international=True) if request and request.source == 'WhatsApp' else None


def _eligible_number(employee, order):
	if not employee or (not order.order_intake_request and employee == order.sales_employee):
		return None
	current = frappe.db.get_value('Sales Employee', employee,
		['status', 'mobile_number', 'sales_order_whatsapp_opt_out', 'sales_employee_name'], as_dict=True)
	if not current or current.status != 'Active' or current.sales_order_whatsapp_opt_out:
		return None
	if not frappe.db.exists('Sales Employee Assigned Customer', dict(parent=employee, parenttype='Sales Employee',
			parentfield='assigned_customers', customer=order.customer)):
		return None
	number = normalize_phone(current.mobile_number, strict=False)
	if not number or number == _intake_sender(order):
		return None
	# Legacy records can contain different spellings of the same number.
	owners = frappe.db.sql(f'SELECT name FROM `tabSales Employee` WHERE {phone_sql("mobile_number")}=%s LIMIT 2', number, pluck=True)
	return (number, current.sales_employee_name) if owners == [employee] else None


def _has_service_window(account, number, as_of):
	if not account.phone_id:
		return False
	# Desk corrections can change the saved sender or account. Only the original
	# authenticated webhook can establish this recipient's service window.
	payload = "CASE WHEN JSON_VALID(intake_raw_payload) THEN intake_raw_payload ELSE '{}' END"
	stamp = f"JSON_UNQUOTE(JSON_EXTRACT({payload}, '$.message.timestamp'))"
	timezone = ZoneInfo(get_system_timezone())
	end = as_of.replace(tzinfo=timezone).timestamp()
	start_at = datetime.fromtimestamp(end - 86400, timezone).replace(tzinfo=None)
	return bool(frappe.db.sql(f'''
		SELECT name FROM `tabWhatsApp Message`
		WHERE type='Incoming' AND whatsapp_account=%(account)s AND intake_sender_key=%(number)s
			AND intake_phone_id=%(phone_id)s AND intake_sent_at BETWEEN %(start_at)s AND %(end_at)s
			AND message_id=JSON_UNQUOTE(JSON_EXTRACT({payload}, '$.message.id'))
			AND JSON_UNQUOTE(JSON_EXTRACT({payload}, '$.metadata.phone_number_id'))=%(phone_id)s
			AND TRIM(LEADING '+' FROM COALESCE(NULLIF(JSON_UNQUOTE(JSON_EXTRACT({payload}, '$.message.from')), ''),
				JSON_UNQUOTE(JSON_EXTRACT({payload}, '$.message.from_user_id'))))=%(number)s
			AND JSON_UNQUOTE(JSON_EXTRACT({payload}, '$.message.type')) NOT IN ('reaction', 'system', 'unknown')
			AND {stamp} REGEXP '^[0-9]{{1,12}}$'
			AND CAST({stamp} AS UNSIGNED)>%(start_epoch)s AND CAST({stamp} AS UNSIGNED)<=%(end_epoch)s
		LIMIT 1
	''', dict(account=account.name, phone_id=account.phone_id, number=number, end_at=as_of,
		start_at=start_at, start_epoch=end-86400, end_epoch=end)))


def _placer_label(order):
	placer = order.sales_employee
	if order.order_intake_request:
		# The salesperson selected during review can differ from the sender.
		sender = _intake_sender(order)
		if not sender:
			return 'Order intake'
		from kunal_enterprises.integrations.order_intake_capture import _identity
		identity = _identity(sender)
		if identity['identity_type'] == 'Customer':
			return 'Customer'
		placer = identity['sales_employee']
		if not placer:
			return 'WhatsApp intake'
	return (frappe.db.get_value('Sales Employee', placer, 'sales_employee_name') or placer) if placer else 'Customer'


def _order_text(order, employee, link):
	items = {row.item: row for row in order.items}
	warehouses = {row.godown for row in order.godown_allocations if row.godown}
	labels = {row.name: row.godown_name for row in frappe.get_all('Tally Godown',
		filters={'name': ('in', sorted(warehouses))}, fields=['name', 'godown_name'])} if warehouses else {}
	allocations = []
	remaining = defaultdict(Decimal)
	for row in order.items:
		remaining[row.item] += Decimal(str(row.requested_quantity))
	for row in order.godown_allocations:
		item = items[row.item]
		quantity = Decimal(str(row.requested_quantity))
		remaining[row.item] -= quantity
		allocations.append((labels.get(row.godown) or row.godown, item.item_name_at_order or row.item,
			quantity, item.unit))
	for name, quantity in remaining.items():
		if quantity > 0:
			item = items[name]
			allocations.append((None, item.item_name_at_order or name, quantity, item.unit))
	customer = frappe.db.get_value('Customer', order.customer, 'customer_name') or order.customer
	return format_message(employee, customer, order.portal_reference_number, _placer_label(order), allocations, link)


def _send_text(account, phone, message):
	base = (account.url or 'https://graph.facebook.com').rstrip('/')
	if base != 'https://graph.facebook.com' or not re.fullmatch(r'v\d+\.\d+', account.version or '') or not re.fullmatch(r'\d+', account.phone_id or ''):
		raise ValueError('Invalid WhatsApp Graph API configuration')
	token = account.get_password('token')
	if not token:
		raise ValueError('The WhatsApp account has no access token')
	with requests.post(f'{base}/{account.version}/{account.phone_id}/messages', timeout=(5, 25),
			allow_redirects=False, headers={'Authorization': f'Bearer {token}'},
			json={'messaging_product': 'whatsapp', 'to': phone, 'type': 'text',
				'text': {'body': message, 'preview_url': False}}) as response:
		response.raise_for_status()
		if not 200 <= response.status_code < 300:
			raise ValueError('Unexpected WhatsApp response status')
		message_id = response.json()['messages'][0]['id']
		if not isinstance(message_id, str) or not message_id:
			raise ValueError('Missing WhatsApp message ID')
		return message_id


def _skip(name, reason):
	frappe.db.set_value(NOTIFICATION, name, dict(status='Skipped', skip_reason=reason))


def dispatch(name):
	"""Claim once before contacting Meta, then recheck eligibility at send time."""
	row = frappe.db.get_value(NOTIFICATION, name, ['order', 'recipient_type', 'recipient_sales_employee',
		'sales_dispatch_key', 'status', 'mobile_number', 'created_at', 'order_customer'], as_dict=True, for_update=True)
	if not row or row.status != 'Queued' or row.recipient_type != 'Sales Employee' or not row.sales_dispatch_key:
		return
	frappe.db.set_value(NOTIFICATION, name, 'status', 'Sending')
	frappe.db.commit()
	try:
		if not frappe.db.exists('Order', row.order):
			return _skip(name, 'Order is unavailable.')
		order = frappe.get_doc('Order', row.order)
		if order.status in {'Cancelled', 'Partially Closed'}:
			return _skip(name, 'Order is closed.')
		if order.customer != row.order_customer:
			return _skip(name, 'Customer changed after the Order was placed.')
		identity = _eligible_number(row.recipient_sales_employee, order)
		if not identity:
			return _skip(name, 'Employee is no longer eligible for WhatsApp alerts on this Order.')
		phone, employee = identity
		if phone != normalize_phone(row.mobile_number, strict=False):
			return _skip(name, 'Recipient number changed after the Order was placed.')
		link = _portal_link(order.name)
		if not link:
			return _skip(name, 'A public HTTPS portal URL is required.')
		account = _default_account()
		if not account:
			return _skip(name, 'Select exactly one active default outgoing WhatsApp account.')
		message = _order_text(order, employee, link)
		# A new message can refresh an open window, but cannot revive an alert
		# for an Order placed while the recipient's window was closed.
		if not _has_service_window(account, phone, row.created_at) or not _has_service_window(account, phone, now_datetime()):
			return _skip(name, 'No incoming message within the last 24 hours at placement or dispatch on the outgoing account.')
		provider_id = _send_text(account, phone, message)
		frappe.db.set_value(NOTIFICATION, name, dict(status='Sent', mobile_number=phone,
			request_payload=frappe.as_json({'text': message, 'account': account.name}),
			provider_response=frappe.as_json({'message_id': provider_id})))
	except Exception as exc:
		# A timeout may happen after Meta accepted the text. Never blindly retry.
		frappe.db.set_value(NOTIFICATION, name, dict(status='Failed',
			skip_reason='WhatsApp dispatch could not be confirmed. Check the conversation before resending.',
			provider_response=frappe.as_json({'error_type': type(exc).__name__})))
		return
	# Keep the provider ID available to the existing status and reply handlers.
	# Inserting through the normal controller would send the same message again.
	frappe.db.savepoint('sales_whatsapp_message_log')
	try:
		frappe.get_doc(dict(doctype='WhatsApp Message', type='Outgoing', content_type='text',
			to=phone, message=message, whatsapp_account=account.name, message_id=provider_id,
			status='Success', reference_doctype='Order', reference_name=order.name)).db_insert()
	except Exception:
		frappe.db.rollback(save_point='sales_whatsapp_message_log')
		frappe.logger('sales_order_whatsapp').warning('Could not log the outgoing WhatsApp message for %s', name)
	finally:
		frappe.db.release_savepoint('sales_whatsapp_message_log')


def _single_line(value, limit=180):
	return ' '.join(str(value or '').split())[:limit]


def format_message(employee, customer, reference, placed_by, allocations, order_link):
	"""Group allocation tuples (warehouse, item, quantity, unit) by warehouse."""
	heading = [f'Hi {_single_line(employee)},', '', '*New order placed*',
		f'Customer: {_single_line(customer)}', f'Order reference: {_single_line(reference)}',
		f'Placed by: {_single_line(placed_by)}']
	footer = ['', '*View the full order*', order_link]
	groups = defaultdict(list)
	for warehouse, item, quantity, unit in allocations:
		qty = format(Decimal(str(quantity)).normalize(), 'f')
		amount = f'{qty} {_single_line(unit, 30)}'.rstrip()
		groups[_single_line(warehouse)].append(f'• {_single_line(item)} — {amount}')
	lines = heading.copy()
	for warehouse in sorted(groups, key=lambda name: (not name, name.casefold())):
		section = f'*Dispatch from {warehouse}*' if warehouse else '*Dispatch warehouse pending*'
		lines.extend(['', section, *groups[warehouse]])
	message = '\n'.join(lines + footer)
	if len(message) <= 4000:
		return message

	# Keep the link available for large orders. Truncate on allocation lines,
	# leaving room for the continuation notice and the order link.
	continuation = ['', 'More items are listed in the portal.']
	for position in range(len(lines) - 1, len(heading) - 1, -1):
		if not lines[position - 1].startswith('• '):
			continue
		message = '\n'.join(lines[:position] + continuation + footer)
		if len(message) <= 4000:
			return message
	return '\n'.join(heading + continuation + footer)
