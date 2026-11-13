"""On-demand, request-scoped evidence review. No external media is fetched."""
import hashlib
import json
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import frappe
from frappe.utils import cint, get_datetime

from kunal_enterprises.api.quick_orders import _require_reviewer
from kunal_enterprises.kunal_enterprises.doctype.order_intake_request.order_intake_request import _sender_key

MAX_SOURCES = 1000


def _file_evidence(doc, sources, lock=False):
	"""Fence replacement files as well as changes to the message attachment URL."""
	urls = sorted({source.get('attach') for source in sources if source.get('attach')} |
		{row.file for row in doc.attachments if row.reference_type == 'File' and row.file})
	if not urls:
		return []
	file = frappe.qb.DocType('File')
	query = frappe.qb.from_(file).select(file.name, file.file_url, file.content_hash, file.modified,
		file.is_private, file.file_size, file.attached_to_doctype, file.attached_to_name
	).where(file.file_url.isin(urls)).orderby(file.name)
	if lock:
		query = query.for_update()
	return query.run(as_dict=True)


def _authorized(request, lock=False):
	_require_reviewer()
	doc = frappe.get_doc('Order Intake Request', request, for_update=lock)
	doc.check_permission('read')
	names = list(dict.fromkeys(row.message for row in doc.source_messages if row.message))
	if len(names) > MAX_SOURCES:
		frappe.throw('This request has too many linked messages for this view. Review its source table directly.')
	sources = []
	for name in sorted(names):
		source = frappe.get_doc('WhatsApp Message', name, for_update=lock)
		source.check_permission('read')
		if source.type != 'Incoming' or source.whatsapp_account != doc.whatsapp_account or _sender_key(source.get('from')) != _sender_key(doc.sender_number):
			frappe.throw('A linked message belongs to a different chat. Correct the request sources before reviewing.', frappe.PermissionError)
		sources.append(source)
	if any(row.source_message and row.source_message not in names for row in doc.attachments):
		frappe.throw('An attachment refers to an unlinked message. Correct the request sources before reviewing.', frappe.PermissionError)
	return doc, sources


def _file_reference(url, doc, source_names):
	"""Only source-owned private files that this reviewer can read get links."""
	unavailable = dict(available=False, note='File unavailable or not permitted. Review the original attachment.')
	if not isinstance(url, str) or not url:
		return unavailable
	try:
		parts = urlsplit(url)
		decoded = unquote(parts.path)
	except ValueError:
		return unavailable
	if parts.scheme or parts.netloc or parts.query or parts.fragment or not decoded.startswith('/private/files/') or '\\' in decoded or '\x00' in decoded:
		return unavailable
	try:
		root = Path(frappe.get_site_path('private', 'files')).resolve()
		path = (root / decoded.removeprefix('/private/files/')).resolve()
		if path == root or not path.is_relative_to(root) or not path.is_file():
			return unavailable
	except (OSError, ValueError, RuntimeError):
		return unavailable
	# File deduplication may share a URL; authorize a matching attachment record,
	# never whichever unrelated File happens to be returned first.
	rows = frappe.db.sql("""SELECT name, attached_to_doctype, attached_to_name FROM `tabFile`
		WHERE file_url=%s AND is_private=1 AND (
			(attached_to_doctype='Order Intake Request' AND attached_to_name=%s) OR
			(attached_to_doctype='WhatsApp Message' AND attached_to_name IN %s))
		ORDER BY name LIMIT 50""", (decoded, doc.name, tuple(sorted(source_names)) or ('',)), as_dict=True)
	for row in rows:
		owned = (row.attached_to_doctype == 'WhatsApp Message' and row.attached_to_name in source_names) or (
			row.attached_to_doctype == 'Order Intake Request' and row.attached_to_name == doc.name)
		if not owned:
			continue
		file = frappe.get_doc('File', row.name)
		if not file.has_permission('read'):
			continue
		try:
			size = path.stat().st_size
		except OSError:
			return unavailable
		return dict(available=True, url=quote(decoded, safe='/'), file_name=file.file_name or path.name,
			file_type=file.file_type or '', size_bytes=size,
			note='Open manually to review. No automatic preview or external download.')
	return unavailable


def _location(source):
	if not source.get('intake_has_location'):
		return None
	return dict(latitude=source.get('intake_latitude'), longitude=source.get('intake_longitude'),
		address=source.get('intake_location_address'), name=source.get('intake_location_name'))


def _sender_identity(number):
	# Use the same exact normalized phone matching as incoming capture. This is
	# a record match, not mobile approval or permission to place an Order.
	from kunal_enterprises.integrations.order_intake_capture import _identity
	identity = _identity(number)
	matches = [{key: row.get(key) for key in ('doctype', 'name', 'label')}
		for row in frappe.parse_json(identity['identity_candidates'])]
	return dict(status='Matched' if len(matches) == 1 else 'Ambiguous' if matches else 'Unknown', matches=matches)


def _message(source, doc, source_names, provider_names):
	ref = source.get('reply_to_message_id')
	reply_to = ref if ref in source_names else provider_names.get(ref)
	file = _file_reference(source.get('attach'), doc, {source.name}) if source.get('attach') else None
	media_type = source.get('intake_original_type') or source.content_type
	warnings = list(dict.fromkeys(line for text in (source.get('intake_attention'), source.get('intake_media_note')) for line in (text or '').splitlines() if line))
	if media_type in {'image', 'document', 'audio', 'video', 'sticker'} and not file:
		warnings.append('Media is not available locally yet; review or retry its download from the original message.')
	return dict(name=source.name, text=source.message or '', sender=source.get('from'), sender_name=source.profile_name or '',
		received_at=str(source.get('intake_received_at') or source.creation), content_type=media_type,
		reply_to=reply_to, attachment=file, location=_location(source), warnings=warnings)


@frappe.whitelist(methods=['GET'])
def messages(request, cursor=None, limit=50, revision=None, expected_modified=None):
	"""Latest page first, with chronological bubbles and an explicit older cursor."""
	return _messages(request, cursor, limit, revision, expected_modified)


def _messages(request, cursor=None, limit=50, revision=None, expected_modified=None, lock=False):
	# Final processing uses current locking reads, not an older repeatable-read
	# snapshot opened before a concurrent correction committed. GET stays read-only.
	if not isinstance(request, str) or not request.strip():
		frappe.throw('Choose a saved Order Intake Request.')
	if cursor is not None and not isinstance(cursor, str):
		frappe.throw('Invalid message page. Refresh the Messages section.')
	if revision is not None and not isinstance(revision, str):
		frappe.throw('Invalid message revision. Refresh the Messages section.')
	doc, sources = _authorized(request, lock=lock)
	if expected_modified and str(expected_modified) != str(doc.modified):
		frappe.throw('The request changed. Reload it before viewing messages.', frappe.TimestampMismatchError)
	rendered_fields = ('name', 'modified', 'message', 'attach', 'reply_to_message_id', 'message_id', 'from',
		'profile_name', 'content_type', 'intake_original_type', 'intake_received_at', 'creation', 'intake_has_location',
		'intake_latitude', 'intake_longitude', 'intake_location_address', 'intake_location_name', 'intake_attention',
		'intake_media_note', 'intake_media_state')
	# Internal capture/download updates deliberately keep modified unchanged.
	# Hash the evidence itself so a multi-page review cannot mix revisions.
	current_revision = hashlib.sha256(json.dumps([str(doc.modified),
		[{field: source.get(field) for field in rendered_fields} for source in sorted(sources, key=lambda s: s.name)],
		_file_evidence(doc, sources, lock=lock)],
		default=str, sort_keys=True).encode()).hexdigest()
	if (cursor and not revision) or (revision and revision != current_revision):
		frappe.throw('Messages changed. Refresh the Messages section.', frappe.TimestampMismatchError)
	sources.sort(key=lambda source: (get_datetime(source.get('intake_received_at') or source.creation), source.name))
	names = {s.name for s in sources}
	provider_names = {}
	for source in sources:
		if source.message_id:
			# Ambiguous provider IDs are not usable reply references.
			provider_names[source.message_id] = None if source.message_id in provider_names else source.name
	if cursor:
		if cursor not in names:
			frappe.throw('Invalid message page. Refresh the Messages section.')
		sources_page = sources[:next(index for index, source in enumerate(sources) if source.name == cursor)]
	else:
		sources_page = sources
	page_size = min(max(cint(limit), 1), 50)
	page = sources_page[-page_size:]
	pdf_limit = cint(frappe.db.get_single_value('Order Intake Settings', 'pdf_page_limit') or 10)
	references = []
	for row in doc.attachments:
		item = dict(name=row.name, reference_type=row.reference_type, label=row.label or '', source_message=row.source_message,
			review_status=row.review_status or 'Not Reviewed', notes=row.notes or '', page_count=row.page_count or None,
			external_url=row.external_url or '', latitude=row.latitude, longitude=row.longitude, location_address=row.location_address or '')
		if row.reference_type == 'File':
			item['attachment'] = _file_reference(row.file, doc, {row.source_message} if row.source_message else names)
			item['manual_review'] = not row.page_count or row.page_count > pdf_limit or row.review_status == 'Needs Manual Review'
		references.append(item)
	return dict(request=doc.name, modified=str(doc.modified), revision=current_revision, total_linked=len(sources),
		sender_number=doc.sender_number or '', sender_name=doc.sender_name or '',
		sender_profile_name=next((source.profile_name for source in reversed(sources) if source.profile_name), ''),
		sender_identity=_sender_identity(doc.sender_number),
		messages=[_message(source, doc, names, provider_names) for source in page], references=references,
		has_more=len(sources_page) > len(page), next_cursor=page[0].name if page and len(sources_page) > len(page) else None,
		pdf_page_limit=pdf_limit)
