"""Bounded business contact-card data, without vCards or provider envelopes."""
from html import unescape
import json
import re

CONTACT_LIMIT = 10
PHONE_LIMIT = 10
WARNING = 'Contact card is incomplete or exceeds supported limits; review original payload.'


def _text(value, limit):
	return value.strip()[:limit] if isinstance(value, str) else ''


def project_contacts(body):
	"""Return names/phones only; keep malformed or clipped data visible for review."""
	if not isinstance(body, list) or not body:
		return [], WARNING
	result, incomplete = [], len(body) > CONTACT_LIMIT
	for source in body[:CONTACT_LIMIT]:
		if not isinstance(source, dict):
			incomplete = True
			continue
		name = source.get('name') or {}
		if not isinstance(name, dict):
			name, incomplete = {}, True
		full_name = name.get('formatted_name') or ' '.join(
			_text(name.get(part), 140) for part in ('first_name', 'middle_name', 'last_name') if name.get(part))
		name_text = _text(full_name, 140)
		incomplete |= not isinstance(full_name, str) or len(str(full_name)) > 140
		phones = source.get('phones') or []
		if not isinstance(phones, list):
			phones, incomplete = [], True
		incomplete |= len(phones) > PHONE_LIMIT
		values = []
		for entry in phones[:PHONE_LIMIT]:
			if not isinstance(entry, dict):
				incomplete = True
				continue
			phone, wa_id = _text(entry.get('phone'), 64), _text(entry.get('wa_id'), 32)
			if phone and (not any(char.isdigit() for char in phone) or not re.fullmatch(r'[+0-9(). /#xXextEXT-]+', phone)):
				phone, incomplete = '', True
			if wa_id and not wa_id.isdigit():
				wa_id, incomplete = '', True
			if len(str(entry.get('phone') or '')) > 64 or len(str(entry.get('wa_id') or '')) > 32:
				incomplete = True
			if not phone and not wa_id:
				incomplete = True
				continue
			value = dict(phone=phone or wa_id)
			if wa_id:
				value['wa_id'] = wa_id
			kind = _text(entry.get('type'), 32)
			if kind:
				value['type'] = kind
			if value not in values:
				values.append(value)
		incomplete |= not bool(values)
		if name_text or values:
			result.append(dict(name=name_text, phones=values))
		else:
			incomplete = True
	return result, WARNING if incomplete or not result else None


def contact_text(contacts):
	return '\n'.join(' · '.join(part for part in [contact['name'],
		', '.join(phone['phone'] for phone in contact['phones'])] if part) for contact in contacts)


def contacts_from_source(source):
	"""Read captured raw cards; support older escaped list bodies without exposing them."""
	raw = source.get('intake_raw_payload')
	try:
		raw = raw if isinstance(raw, dict) else json.loads(raw or '{}')
	except (TypeError, ValueError):
		raw = {}
	message = raw.get('message', raw) if isinstance(raw, dict) else {}
	body = message.get('contacts') if isinstance(message, dict) else None
	if body is None:
		try:
			body = json.loads(unescape(source.get('message') or ''))
		except (TypeError, ValueError):
			body = None
	return project_contacts(body)


def repair_contact_message(name):
	"""Explicit local repair only; never invoke the webhook or AI/provider again."""
	import frappe
	from kunal_enterprises.api.quick_orders import _require_reviewer
	_require_reviewer()
	doc = frappe.get_doc('WhatsApp Message', name, for_update=True)
	doc.check_permission('read'); doc.check_permission('write')
	if doc.type != 'Incoming' or (doc.intake_original_type or doc.content_type) not in ('contacts', 'contact'):
		frappe.throw('Select an incoming contact-card message.')
	if doc.intake_ai_state == 'Queued' or doc.intake_prepare_state == 'Queued':
		frappe.throw('Wait for the current message job before repairing its display.')
	contacts, warning = contacts_from_source(doc)
	if not contacts:
		frappe.throw('No readable contact data is available; review the original payload.')
	from html import escape
	owned = ('WhatsApp parser could not save this message (', 'WhatsApp parser did not save this message;')
	remaining = [line for line in (doc.intake_attention or '').splitlines() if not line.startswith(owned)]
	if warning and warning not in remaining:
		remaining.append(warning)
	values = dict(message=escape(contact_text(contacts)), content_type='contact',
		intake_attention='\n'.join(remaining), intake_prepare_state='Pending',
		intake_prepare_note='Contact-card display repaired; prepare context before further AI processing.')
	if not remaining and doc.intake_status == 'Needs Attention':
		values['intake_status'] = 'New'
	frappe.db.set_value('WhatsApp Message', name, values, update_modified=False)
	return dict(message=name, contacts=len(contacts), warning=warning)
