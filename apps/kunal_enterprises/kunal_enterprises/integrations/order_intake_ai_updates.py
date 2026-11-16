"""Business-value comparisons for editable suggestions, without model calls."""
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation


def wording(value):
	value = unicodedata.normalize('NFKC', str(value or '')).casefold().strip()
	return re.sub(r'\s+', ' ', value).strip(' .,:;!?')


def _warehouse(value):
	return wording(re.sub(r'\b(?:godown|warehouse)\b', '', str(value or ''), flags=re.I).lstrip('@'))


def _notes(value):
	# Generated explanations of a correction do not add a new instruction when
	# the actual quantity is already represented. Prices/discounts remain notes.
	text = wording(value)
	unit = r'(?:nos|sheets?|pieces?|pcs|kgs?|kilograms?|sq\.? ?ft|sqft|units?)'
	if re.fullmatch(rf'(?:quantity )?corrected from \d+(?:\.\d+)?(?: {unit})? to \d+(?:\.\d+)?(?: {unit})?(?: (?:by message|in) [\w-]+)?', text):
		return ''
	if text == 'existing item retained. remove it only after checking an explicit removal instruction':
		return ''
	return text


def _quantity(row):
	if row.get('quantity_unknown') or row.get('quantity') is None:
		return None
	try:
		return Decimal(str(row.get('quantity')))
	except (InvalidOperation, TypeError, ValueError):
		return str(row.get('quantity'))


def reference_key(row):
	kind = row.get('reference_type') or ''
	base = (kind, str(row.get('source_message') or ''))
	if kind == 'File':
		return base + (str(row.get('file') or ''),)
	if kind == 'External Link':
		return base + (str(row.get('external_url') or ''),)
	if kind == 'Contact':
		return base + (wording(row.get('contact_name')), re.sub(r'[\s()\-]', '', str(row.get('contact_number') or '')))
	if kind == 'Location':
		def coordinate(field):
			value = row.get(field)
			return '' if value is None else str(Decimal(str(value)).normalize())
		return base + (coordinate('latitude'), coordinate('longitude'), wording(row.get('location_address')))
	return base


def _new_questions(proposal, doc):
	existing = {wording(line) for line in (doc.get('unresolved_questions') or '').splitlines()}
	questions = list(proposal.get('unresolved_questions') or [])
	questions += [entry for entries in (proposal.get('media_warnings') or {}).values() for entry in entries]
	questions += [entry for entry in proposal.get('review_warnings') or [] if not str(entry).startswith('Earlier items are retained.')]
	return any(wording(question) and wording(question) not in existing for question in questions)


def proposal_changes_values(proposal, doc):
	"""Missing extraction values never remove existing reviewer selections.

	Source IDs and prose summaries are evidence, not a business-field edit. New
	instructions in item notes or delivery fields do count as changes. All source
	messages remain linked independently of whether this returns True.
	"""
	if proposal.get('request_type') and proposal['request_type'] != doc.get('request_type'):
		return True
	for field, aliases in (
		('customer_text', ('customer_text', 'customer', 'customer_name')),
		('salesperson_text', ('salesperson_text', 'sales_employee', 'sales_employee_name')),
	):
		value = wording(proposal.get(field))
		if value and value not in {wording(doc.get(alias)) for alias in aliases}:
			return True
	for field in ('delivery_address', 'delivery_contact_name', 'delivery_contact_number'):
		value = proposal.get(field)
		compare = (lambda text: re.sub(r'[\s()\-]', '', str(text or ''))) if field == 'delivery_contact_number' else wording
		if value and compare(value) != compare(doc.get(field)):
			return True
	if _new_questions(proposal, doc):
		return True
	available = list(doc.get('items') or [])
	for row in proposal.get('items') or []:
		aliases = {wording(row.get('original_text')), wording(row.get('item'))} - {''}
		matches = [current for current in available if aliases & {
			wording(current.get('original_text')), wording(current.get('item')), wording(current.get('item_name'))} - {''}]
		# Repeated item wording can represent separate warehouse rows; only pair
		# it when the quantity and warehouse match one of those rows.
		matching = next((current for current in matches if _quantity(row) == _quantity(current)
			and (not row.get('warehouse_text') or _warehouse(row['warehouse_text']) in {
				_warehouse(current.get('warehouse_text')), _warehouse(current.get('godown'))})
			and (not _notes(row.get('notes')) or _notes(row.get('notes')) == _notes(current.get('notes')))), None)
		if matching is None:
			return True
		available.remove(matching)
	# preserve_existing_items() fills any omitted earlier rows before calling us.
	if available:
		return True
	for ref in proposal.get('new_references') or []:
		current = next((row for row in doc.get('attachments') or [] if reference_key(row) == reference_key(ref)), None)
		if current is None or current.get('review_status') != 'Reviewed':
			return True
	return False


def proposal_signature(proposal):
	"""Equivalent pending suggestions share values despite summary/ref prose."""
	data = {key: wording(proposal.get(key)) for key in ('request_type', 'customer_text', 'salesperson_text',
		'delivery_address', 'delivery_contact_name', 'delivery_contact_number')}
	data['delivery_contact_number'] = re.sub(r'[\s()\-]', '', str(proposal.get('delivery_contact_number') or ''))
	data['items'] = sorted((wording(row.get('original_text')), str(_quantity(row).normalize()) if isinstance(_quantity(row), Decimal) else str(_quantity(row)), _warehouse(row.get('warehouse_text')),
		_notes(row.get('notes'))) for row in proposal.get('items') or [])
	data['questions'] = sorted(wording(value) for value in proposal.get('unresolved_questions') or [])
	data['warnings'] = sorted(wording(value) for values in (proposal.get('media_warnings') or {}).values() for value in values)
	data['review_warnings'] = sorted(wording(value) for value in proposal.get('review_warnings') or []
		if not str(value).startswith('Earlier items are retained.'))
	data['references'] = sorted(reference_key(row) for row in proposal.get('new_references') or [])
	return json.dumps(data, sort_keys=True, default=str)


def prune_noop_updates(doc, updates):
	"""Remove only unreviewed no-ops; retain reviewed audit history and real edits.

	Returns the new list plus the number removed. The caller owns backup, flags,
	permissions and persistence; this helper never writes or marks human review.
	"""
	known = {row.get('message') for row in doc.get('source_messages') or []}
	kept = [proposal for proposal in updates if proposal.get('reviewed_at') or
		not set(proposal.get('source_messages') or []).issubset(known) or proposal_changes_values(proposal, doc)]
	return kept, len(updates) - len(kept)
