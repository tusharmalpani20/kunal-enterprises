"""Permission-checked incoming chat browsing. This module never sends or marks read."""
import base64
import json
from html import unescape
from types import SimpleNamespace

import frappe
from frappe.utils import cint, get_datetime

from kunal_enterprises.api.order_intake_conversation import _message, _sender_identity
from kunal_enterprises.integrations.order_intake_ai_state import OWNED_WARNINGS, REVIEW_PREFIX
from kunal_enterprises.kunal_enterprises.doctype.order_intake_request.order_intake_request import _sender_key

DT = 'WhatsApp Message'
ROLES = {'Owner', 'Admin', 'Order Coordinator', 'System Manager'}
FIELDS = ['name', 'creation', 'message_id', 'from', 'profile_name', 'message', 'content_type',
	'intake_original_type', 'intake_received_at', 'intake_sender_key']


def _require_reader():
	if frappe.session.user == 'Guest' or (frappe.session.user != 'Administrator' and not ROLES.intersection(frappe.get_roles())):
		frappe.throw('WhatsApp inbox access is not permitted.', frappe.PermissionError)
	frappe.has_permission(DT, 'read', throw=True)


def _account(name):
	_require_reader()
	if not isinstance(name, str) or not name.strip() or len(name) > 140:
		frappe.throw('Select a WhatsApp account.')
	doc = frappe.get_doc('WhatsApp Account', name)
	doc.check_permission('read')
	return doc


def _limit(value, maximum):
	return min(max(cint(value), 1), maximum)


def _encode(scope, row):
	return base64.urlsafe_b64encode(json.dumps([scope, str(row.creation), row.name], separators=(',', ':')).encode()).decode()


def _decode(value, scope):
	if not value:
		return None
	try:
		if not isinstance(value, str) or len(value) > 4000:
			raise ValueError
		parts = json.loads(base64.b64decode(value.encode(), altchars=b'-_', validate=True))
		if not isinstance(parts, list) or len(parts) != 3 or parts[0] != scope or not isinstance(parts[1], str) or not isinstance(parts[2], str) or len(parts[2]) > 140:
			raise ValueError
		return str(get_datetime(parts[1])), parts[2]
	except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
		frappe.throw('Invalid inbox page. Refresh the inbox.')


def _key_condition(alias, point, direction):
	stamp, name = point
	comparison = '<' if direction == 'before' else '>'
	return f"({alias}.creation {comparison} {frappe.db.escape(stamp)} OR ({alias}.creation = {frappe.db.escape(stamp)} AND {alias}.name {comparison} {frappe.db.escape(name)}))"


def _normalized(expression):
	for char in ('+', ' ', '-', '(', ')'):
		expression = f"REPLACE({expression}, '{char}', '')"
	return expression


def _sender_expression(alias):
	# Use the actual sender, matching document-level scope checks. A cached
	# intake key can be stale after a source correction or historical import.
	raw = f"TRIM(COALESCE({alias}.`from`, ''))"
	return f"CASE WHEN {raw} REGEXP '^[+0-9 ()-]+$' THEN {_normalized(raw)} ELSE {raw} END"


def _base(account):
	# Let Frappe apply shares, User Permissions and permission-query hooks before
	# grouping; aggregating unrestricted rows would leak inaccessible chats.
	return frappe.get_list(DT, fields=FIELDS, filters={'type': 'Incoming', 'whatsapp_account': account},
		order_by='', limit_page_length=0, run=False)


def _phone_match(alias):
	phone = _normalized(f"COALESCE({alias}.mobile_number, '')")
	code = str(frappe.db.get_single_value('Order Intake Settings', 'default_country_calling_code') or '91').strip().lstrip('+')
	quoted_code = frappe.db.escape(code)
	# Match exactly the same default-country variants as capture._identity.
	return f"(s.sender REGEXP '^[0-9]+$' AND ({phone} = s.sender OR (CHAR_LENGTH(s.sender)=10 AND {phone}=CONCAT({quoted_code},s.sender)) OR (LEFT(s.sender,{len(code)})={quoted_code} AND CHAR_LENGTH(s.sender)={len(code)+10} AND {phone}=SUBSTRING(s.sender,{len(code)+1}))))"


def _customer_phone_match(alias='c'):
	# Count Customer parents, not contact rows. A contact and the primary phone
	# referring to the same Customer must not make its sender look ambiguous.
	from kunal_enterprises.integrations.customer_contacts import phone_sql

	sender_phone = phone_sql('s.sender', international=True)
	return f"({sender_phone} REGEXP '^[0-9]+$' AND ({phone_sql(alias+'.mobile_number')}={sender_phone} OR EXISTS (SELECT 1 FROM `tabCustomer Contact` cc WHERE cc.parent={alias}.name AND cc.parenttype='Customer' AND cc.parentfield='contacts' AND {phone_sql('cc.mobile_number')}={sender_phone})))"


def _like(value):
	# An explicit escape character keeps percent/underscore/backslash literal.
	return '%' + value.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'



@frappe.whitelist(methods=['GET'])
def accounts():
	_require_reader()
	rows = frappe.get_list('WhatsApp Account', fields=['name', 'account_name'], order_by='account_name', limit_page_length=0)
	allowed = [row for row in rows if frappe.get_doc('WhatsApp Account', row.name).has_permission('read')]
	default = frappe.db.get_single_value('WhatsApp Settings', 'default_incoming_account')
	return {'accounts': [dict(name=row.name, label=row.account_name or row.name) for row in allowed],
		'default_account': default if default in {row.name for row in allowed} else None}


@frappe.whitelist(methods=['GET'])
def conversations(account, search='', sender_type='All', cursor=None, limit=30):
	_account(account)
	if not isinstance(search, str) or len(search) > 200 or not isinstance(sender_type, str) or sender_type not in {'All', 'Salespersons', 'Clients', 'Unknown'}:
		frappe.throw('Invalid inbox search or sender filter.')
	search = search.strip()
	point = _decode(cursor, ['chats', account, search, sender_type])
	base = _base(account)
	profile_order = "CASE WHEN TRIM(COALESCE(incoming.profile_name,''))<>'' THEN 0 ELSE 1 END,incoming.creation DESC,incoming.name DESC"
	latest = f"SELECT ranked.* FROM (SELECT incoming.*, ROW_NUMBER() OVER (PARTITION BY incoming.sender ORDER BY incoming.creation DESC,incoming.name DESC) inbox_rank, FIRST_VALUE(incoming.profile_name) OVER (PARTITION BY incoming.sender ORDER BY {profile_order}) chat_profile, FIRST_VALUE(incoming.name) OVER (PARTITION BY incoming.sender ORDER BY {profile_order}) profile_message FROM (SELECT original.*, {_sender_expression('original')} sender FROM ({base}) original) incoming) ranked WHERE ranked.inbox_rank=1"
	customer_match, employee_match = _customer_phone_match(), _phone_match('e')
	counts = f"SELECT s.*, (SELECT COUNT(*) FROM `tabCustomer` c WHERE {customer_match}) customer_count, (SELECT COUNT(*) FROM `tabSales Employee` e WHERE {employee_match}) employee_count FROM ({latest}) s"
	conditions = []
	if sender_type == 'Clients':
		conditions.append('s.customer_count=1 AND s.employee_count=0')
	elif sender_type == 'Salespersons':
		conditions.append('s.employee_count=1 AND s.customer_count=0')
	elif sender_type == 'Unknown':
		conditions.append('(s.customer_count+s.employee_count)<>1')
	if search:
		term = frappe.db.escape(_like(search))
		phone_term = frappe.db.escape(_like(_sender_key(search))) if _sender_key(search).isdigit() else term
		conditions.append(f"(s.sender LIKE {phone_term} ESCAPE '!' OR s.chat_profile LIKE {term} ESCAPE '!' OR EXISTS (SELECT 1 FROM `tabCustomer` c WHERE {customer_match} AND (c.customer_name LIKE {term} ESCAPE '!' OR c.name LIKE {term} ESCAPE '!')) OR EXISTS (SELECT 1 FROM `tabSales Employee` e WHERE {employee_match} AND (e.sales_employee_name LIKE {term} ESCAPE '!' OR e.name LIKE {term} ESCAPE '!')))")
	if point:
		conditions.append(_key_condition('s', point, 'before'))
	where = ' WHERE ' + ' AND '.join('('+condition+')' for condition in conditions) if conditions else ''
	size = _limit(limit, 100)
	rows = frappe.db.sql(f"SELECT s.* FROM ({counts}) s{where} ORDER BY s.creation DESC,s.name DESC LIMIT {size+1}", as_dict=True)
	page = rows[:size]
	result = []
	for row in page:
		source = frappe.get_doc(DT, row.name)
		source.check_permission('read')
		identity = _sender_identity(row.sender)
		if row.profile_message != row.name:
			frappe.get_doc(DT, row.profile_message).check_permission('read')
		profile = (row.chat_profile or '').strip()
		label = identity['matches'][0]['label'] if identity['status'] == 'Matched' else profile or row.sender or 'Unknown sender'
		media = row.intake_original_type or row.content_type
		preview = ' '.join(_display_text(source).split())[:160] or {'document':'Document', 'image':'Image', 'audio':'Voice message', 'video':'Video', 'location':'Location', 'sticker':'Sticker'}.get(media, 'Message')
		from kunal_enterprises.api.whatsapp_inbox_relationships import reaction_data
		reaction = reaction_data(source)
		if reaction:
			preview = 'Reacted ' + reaction['emoji'] if reaction['emoji'] else 'Removed a reaction'
		result.append(dict(sender=row.sender, display_name=label, profile_name=profile,
			last_received_at=str(row.intake_received_at or row.creation), preview=preview,
			identity=identity, last_message=row.name))
	return dict(account=account, conversations=result, has_more=len(rows)>size,
		next_cursor=_encode(['chats', account, search, sender_type], page[-1]) if page and len(rows)>size else None)


@frappe.whitelist(methods=['GET'])
def messages(account, sender, before=None, after=None, limit=50, refresh_names=None):
	_account(account)
	if not isinstance(sender, str) or len(sender) > 256 or (before and after):
		frappe.throw('Choose a valid sender and message page.')
	sender = _sender_key(sender)
	try:
		refresh_names = frappe.parse_json(refresh_names) if isinstance(refresh_names, str) else refresh_names
	except (ValueError, TypeError):
		frappe.throw('Invalid messages to refresh.')
	if refresh_names is None:
		refresh_names = []
	if not isinstance(refresh_names, list) or len(refresh_names) > 1000 or any(not isinstance(name, str) or not name or len(name) > 140 for name in refresh_names):
		frappe.throw('Choose at most 1000 valid messages to refresh.')
	refresh_names = list(dict.fromkeys(refresh_names))
	scope = ['messages', account, sender]
	point = _decode(before or after, scope)
	base = _base(account)
	conditions = [f"s.sender={frappe.db.escape(sender)}"]
	if point:
		conditions.append(_key_condition('s', point, 'after' if after else 'before'))
	size = _limit(limit, 100)
	direction = 'ASC' if after else 'DESC'
	rows = frappe.db.sql(f"SELECT s.name,s.creation FROM (SELECT original.*, {_sender_expression('original')} sender FROM ({base}) original) s WHERE {' AND '.join(conditions)} ORDER BY s.creation {direction},s.name {direction} LIMIT {size+1}", as_dict=True)
	page = rows[:size]
	if not after:
		page.reverse()
	sources = [frappe.get_doc(DT, row.name) for row in page]
	for source in sources:
		source.check_permission('read')
		if source.type != 'Incoming' or source.whatsapp_account != account or _sender_key(source.get('from')) != sender:
			frappe.throw('The conversation changed. Refresh the inbox.', frappe.PermissionError)
	refreshed = []
	if refresh_names:
		names_sql = ','.join(frappe.db.escape(name) for name in refresh_names)
		refresh_rows = frappe.db.sql(f"SELECT s.name FROM (SELECT original.*, {_sender_expression('original')} sender FROM ({base}) original) s WHERE s.sender={frappe.db.escape(sender)} AND s.name IN ({names_sql})", as_dict=True)
		for row in refresh_rows:
			source = frappe.get_doc(DT, row.name)
			if source.has_permission('read') and source.type == 'Incoming' and source.whatsapp_account == account and _sender_key(source.get('from')) == sender:
				refreshed.append(source)
	profile_rows = frappe.db.sql(f"SELECT s.name,s.profile_name FROM (SELECT original.*, {_sender_expression('original')} sender FROM ({base}) original) s WHERE s.sender={frappe.db.escape(sender)} AND TRIM(COALESCE(s.profile_name,''))<>'' ORDER BY s.creation DESC,s.name DESC LIMIT 1", as_dict=True)
	profile = ''
	if profile_rows:
		frappe.get_doc(DT, profile_rows[0].name).check_permission('read')
		profile = profile_rows[0].profile_name.strip()
	formatted = _format_messages(sources)
	refreshed_messages = _format_messages(refreshed)
	removed_names = sorted(set(refresh_names) - {source.name for source in refreshed})
	return dict(account=account, sender=sender, sender_number=sender, sender_name=profile, sender_profile_name=profile,
		sender_identity=_sender_identity(sender), messages=formatted, refreshed_messages=refreshed_messages,
		removed_names=removed_names, references=[], has_more=len(rows)>size,
		next_cursor=_encode(scope, page[0]) if page else None,
		newest_cursor=_encode(scope, page[-1]) if page else after)



def _format_messages(sources):
	names = {source.name for source in sources}
	provider_names = {}
	for source in sources:
		if source.message_id:
			provider_names[source.message_id] = None if source.message_id in provider_names else source.name
	formatted = []
	for source in sources:
		item = _message(source, SimpleNamespace(name=None), names, provider_names)
		# Intake interpretation belongs on the request's current review section,
		# not on original WhatsApp chat bubbles. Preserve real capture/media errors.
		item['warnings'] = [warning for warning in item['warnings']
			if warning not in OWNED_WARNINGS and not warning.startswith(REVIEW_PREFIX)]
		item['creation'] = str(source.creation)
		if item.get('attachment') and item['attachment'].get('available'):
			if not item['attachment'].get('file_type') or item['attachment']['file_type'] == 'application/octet-stream':
				item['attachment']['file_type'] = source.get('intake_media_mime') or source.content_type
		if source.reply_to_message_id and not item['reply_to']:
			item['reply_to'] = 'earlier-message'
		formatted.append(item)
	from kunal_enterprises.api.whatsapp_inbox_relationships import enrich
	return enrich(sources, formatted)



def _display_text(source):
	"""Hide provider media envelopes while preserving actual captions and text."""
	raw = str(source.get('message') or '')
	kind = str(source.get('intake_original_type') or source.get('content_type') or '').lower()
	if kind in {'contacts', 'contact'}:
		from kunal_enterprises.integrations.order_intake_contacts import contacts_from_source, contact_text
		contacts, _ = contacts_from_source(source)
		if contacts:
			return contact_text(contacts)
	if kind not in {'image', 'document', 'audio', 'video', 'sticker', 'location', 'contacts', 'contact'}:
		return raw
	try:
		payload = json.loads(unescape(raw))
	except (ValueError, TypeError):
		return unescape(raw) if kind in {'contacts', 'contact'} else raw
	# Some upstream versions store the provider envelope rather than just the
	# media object. Only traverse known WhatsApp envelope structures.
	value = payload
	provider_messages = None
	if isinstance(value, dict) and isinstance(value.get('entry'), list):
		provider_messages = []
		for entry in value['entry']:
			if not isinstance(entry, dict) or not isinstance(entry.get('changes'), list):
				continue
			for change in entry['changes']:
				body = change.get('value') if isinstance(change, dict) else None
				if isinstance(body, dict) and isinstance(body.get('messages'), list):
					provider_messages.extend(body['messages'])
	elif isinstance(value, dict) and isinstance(value.get('messages'), list):
		provider_messages = value['messages']
	if provider_messages is not None:
		# A webhook batch can contain multiple records. Never borrow another
		# record's caption simply because it is first in the provider envelope.
		matching = [row for row in provider_messages if isinstance(row, dict)
			and source.get('message_id') and row.get('id') == source.get('message_id')]
		if len(matching) == 1:
			value = matching[0]
		elif not matching and len(provider_messages) == 1 and isinstance(provider_messages[0], dict):
			value = provider_messages[0]
		else:
			return ''
	wrapped = isinstance(value, dict) and kind in value
	if wrapped:
		value = value[kind]
	if kind in {'contacts', 'contact'}:
		from kunal_enterprises.integrations.order_intake_contacts import project_contacts, contact_text
		contacts, _ = project_contacts(value if isinstance(value, list) else [value])
		return contact_text(contacts) or 'Contact shared'
	if not isinstance(value, dict):
		return raw
	if isinstance(value.get('caption'), str):
		return value['caption']
	provider_media = ('id' in value and any(key in value for key in ('mime_type', 'sha256', 'url'))) or ('mime_type' in value and any(key in value for key in ('sha256', 'url')))
	provider_location = kind == 'location' and 'latitude' in value and 'longitude' in value
	return '' if wrapped or provider_media or provider_location else raw


@frappe.whitelist(methods=['GET'])
def message_context(account, sender, target):
    """Load a bounded incoming history window, or an outgoing quote only."""
    _account(account)
    if not isinstance(sender, str) or not sender.strip() or len(sender) > 256 or not isinstance(target, str) or not target or len(target) > 140:
        frappe.throw('Choose a valid message.')
    sender = _sender_key(sender)
    from kunal_enterprises.api.whatsapp_inbox_relationships import resolve, is_quoted_in_chat
    source = resolve(account, sender, [target]).get(target)
    if not source or (source.type == 'Outgoing' and not is_quoted_in_chat(source, account, sender)):
        frappe.throw('The original message is not stored or is unavailable to you.', frappe.DoesNotExistError)
    formatted_target = _format_messages([source])[0]
    if source.type == 'Outgoing':
        return dict(target=formatted_target, context_only=True, messages=[], has_more=False, has_newer=False,
            next_cursor=None, newest_cursor=None)
    scope = ['messages', account, sender]
    base = _base(account)
    chat = f"SELECT original.*, {_sender_expression('original')} sender FROM ({base}) original"
    point = (str(source.creation), source.name)
    sides = []
    for direction, order in [('before', 'DESC'), ('after', 'ASC')]:
        sides.append(frappe.db.sql(f"SELECT s.name,s.creation FROM ({chat}) s WHERE s.sender={frappe.db.escape(sender)} AND {_key_condition('s',point,direction)} ORDER BY s.creation {order},s.name {order} LIMIT 26", as_dict=True))
    before, after = sides
    rows = list(reversed(before[:25])) + [frappe._dict(name=source.name, creation=source.creation)] + after[:25]
    sources = [frappe.get_doc(DT, row.name) for row in rows]
    for row in sources:
        row.check_permission('read')
        if row.type != 'Incoming' or row.whatsapp_account != account or _sender_key(row.get('from')) != sender:
            frappe.throw('The conversation changed. Refresh the inbox.', frappe.PermissionError)
    return dict(target=formatted_target, context_only=False, messages=_format_messages(sources),
        next_cursor=_encode(scope,rows[0]), newest_cursor=_encode(scope,rows[-1]),
        has_more=len(before)>25, has_newer=len(after)>25)
