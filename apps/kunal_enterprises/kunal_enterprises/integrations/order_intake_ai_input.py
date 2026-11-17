"""Business-only model inputs; provider envelopes stay in the local evidence ledger."""
from html import unescape
import json
from kunal_enterprises.integrations.order_intake_contacts import contacts_from_source, contact_text


MEDIA_TYPES = {'image', 'document', 'audio', 'video', 'sticker'}
KNOWN_TYPES = MEDIA_TYPES | {'text', 'location', 'reaction', 'contact', 'contacts'}
FIELDS = ('name', 'from', 'profile_name', 'message_id', 'content_type', 'reply_to_message_id',
	'intake_received_at', 'intake_sent_at', 'intake_original_type', 'intake_has_location',
	'intake_latitude', 'intake_longitude', 'intake_location_address', 'intake_location_name',
	'intake_media_filename', 'intake_media_mime', 'intake_identity_type')


def _object(value):
	if isinstance(value, dict):
		return value
	try:
		decoded = json.loads(value or '{}')
		return decoded if isinstance(decoded, dict) else {}
	except (TypeError, ValueError):
		return {}


def model_messages(messages):
	"""Project each source without changing the full snapshot used for fencing/logs.

	Meta media bodies contain expiring credential-bearing download URLs. Only
	captions belong in model text; binaries are supplied separately after local
	ownership and size checks. Unknown formats remain visible manual evidence.
	"""
	result = []
	for source in messages:
		row = {key: source.get(key) for key in FIELDS if source.get(key) is not None}
		# Pass only the uniquely matched Customer/contact, never the full table.
		if source.get('intake_identity_type') == 'Customer':
			try:
				candidates = source.get('intake_identity_candidates') or []
				candidates = json.loads(candidates) if isinstance(candidates, str) else candidates
			except (TypeError, ValueError):
				candidates = []
			if isinstance(candidates, list) and len(candidates) == 1 and isinstance(candidates[0], dict):
				candidate = candidates[0]
				if candidate.get('doctype') == 'Customer' and candidate.get('name') == source.get('intake_customer'):
					keys = ('doctype', 'name', 'label') + tuple(key for key in ('contact_name', 'designation') if candidate.get(key))
					row['recognized_sender'] = {key: str(candidate.get(key) or '')[:140] for key in keys}
		kind = str(source.get('intake_original_type') or source.get('content_type') or '').lower()
		raw = _object(source.get('intake_raw_payload'))
		message = _object(raw.get('message', raw))
		body = message.get(kind)
		text = str(source.get('message') or '')
		if kind in MEDIA_TYPES:
			if not isinstance(body, dict):
				# Older captures may have stored escaped provider JSON as message
				# text instead of a separate raw envelope. Do not transmit it.
				body = _object(unescape(text))
			if body:
				text = body.get('caption') if isinstance(body.get('caption'), str) else ''
		elif kind in {"contact", "contacts"}:
			contacts, warning = contacts_from_source(source)
			row["contacts"] = contacts
			text = contact_text(contacts)
			if warning:
				row["manual_review_reason"] = warning
		elif kind not in KNOWN_TYPES:
			text = ''
			row['manual_review_reason'] = 'Unsupported message format; review the original source manually.'
		row['message'] = text
		context = _object(message.get('context'))
		if context:
			row['reply_context'] = {key: context[field] for key, field in
				(('message_id', 'id'), ('forwarded', 'forwarded'), ('frequently_forwarded', 'frequently_forwarded'))
				if field in context}
		if kind == 'reaction':
			reaction = _object(message.get('reaction'))
			row['reaction'] = dict(emoji=reaction.get('emoji', text),
				message_id=reaction.get('message_id') or source.get('reply_to_message_id'))
		if source.get('intake_legacy_evidence') not in (None, '', '[]'):
			row['manual_review_reason'] = 'Additional conflicting source evidence is retained locally; review the original source manually.'
		result.append(row)
	return result
