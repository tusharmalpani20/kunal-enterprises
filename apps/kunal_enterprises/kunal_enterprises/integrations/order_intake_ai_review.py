"""Reviewable suggestions preserve existing rows and explain missing information."""
import re


def _wording(value):
	return re.sub(r'\s+', ' ', str(value or '').strip()).casefold()


def preserve_existing_items(proposal, doc):
	"""Omission is not a removal instruction, even in a proposed correction.

	Staff can explicitly remove a row after reading the actual message. A model's
	partial extraction must not present that removal as an already established fact.
	"""
	incoming = {_wording(row.get('original_text')) for row in proposal['items']}
	retained = []
	for row in doc.items:
		aliases = {_wording(row.get(field)) for field in ('original_text', 'item', 'item_name')} - {''}
		if incoming & aliases:
			continue
		retained.append(dict(original_text=row.original_text, source_message=row.source_message,
			quantity=None if row.get('quantity_unknown') else row.quantity,
			quantity_unknown=bool(row.get('quantity_unknown')), unit=row.unit,
			warehouse_text=row.warehouse_text, warehouse_source_message=row.warehouse_source_message,
			notes='Existing item retained. Remove it only after checking an explicit removal instruction.', retained=True))
	if retained:
		proposal['items'].extend(retained)
		proposal['review_warnings'] = ['Earlier items are retained. A missing item in this update does not mean it was cancelled or moved to another customer.']
		proposal['summary'] = 'Review the new message alongside the existing items. No item removal or reassignment has been applied.'
	return proposal


def review_questions(doc, extraction_questions, relationship_note=None):
	questions = list(extraction_questions)
	if relationship_note:
		questions.append(relationship_note)
	if not doc.customer:
		questions.append(f'Select the customer for “{doc.customer_text}”.' if doc.customer_text else 'The customer was not identified. Select the customer.')
	if doc.salesperson_text and not doc.sales_employee:
		questions.append(f'Confirm the salesperson mentioned as “{doc.salesperson_text}”.')
	for row in doc.items:
		if row.get('quantity_unknown'):
			questions.append(f'Confirm the quantity for “{row.original_text}”; it was not understood.')
		if not row.item:
			questions.append(f'Select the product or variant for “{row.original_text}”.')
		if row.warehouse_text and not row.godown:
			questions.append(f'Select the dispatch warehouse for “{row.warehouse_text}”.')
	return list(dict.fromkeys(questions))


# These are the exact templates emitted by review_questions, not a broad list
# of customer/product keywords: extraction doubts must survive normal matching.
_GENERATED_QUESTIONS = tuple(re.compile(pattern, re.I) for pattern in (
	r'The customer was not identified\. Select the customer\.',
	r'Select the customer for “.+”\.',
	r'Confirm the salesperson mentioned as “.+”\.',
	r'Confirm the quantity for “.+”; it was not understood\.',
	r'Select the product or variant for “.+”\.',
	r'Select the dispatch warehouse for “.+”\.',
))


def _company_context():
	"""Read company naming only; do not fetch catalogue rows or provider secrets."""
	import frappe
	return dict(receiving_company=frappe.db.get_single_value('Order Intake Settings', 'company_name'),
		company_aliases=(frappe.db.get_single_value('Order Intake Settings', 'company_aliases') or '').splitlines())


def _field(doc, name):
	return doc.get(name) if hasattr(doc, 'get') else getattr(doc, name, None)


def _obsolete_context_question(question, doc, context):
	"""Suppress narrow historic policy doubts, never conflicting source evidence.

	Old records mix generated and extracted questions without provenance. Unknown
	phrasing intentionally stays visible instead of guessing that it is obsolete.
	"""
	text = _wording(question)
	if re.search(r'\b(?:conflict\w*|contradict\w*|mismatch\w*|unreadable|illegible|disagree\w*|contact\w*|phone\w*)\b|cannot read|can.t read|does not match|different (?:buyers|customers|parties|quantities|prices|rates)', text):
		return False
	if _field(doc, 'customer') and re.search(r'\b(?:project|site|table|document)\s+(?:titles?|headings?)\b', text):
		if not re.search(r'\b(?:buyer|customer|party|parties|quantity|quantities|buying)\b', text) and re.search(r'\b(?:split|separate|scopes?)\b|same order|one order', text):
			return True
	# No numeric rate may be discarded: that could be an actual price conflict.
	if _field(doc, 'request_type') == 'Order' and not re.search(r'\d|\b(?:currency|currencies|exchange|tax|gst)\b', text) and re.search(r'\b(?:last|previous)[ -]supply\b', text):
		if re.search(r'\b(?:price|prices|pricing|rate|rates)\b', text) and re.search(r'\b(?:refer|mean|apply|applied|clarify|confirm|specify)\b', text):
			return True
	if not _field(doc, 'customer'):
		return False
	# Questions may quote the sender's short or misspelled trading name while
	# the selected master uses its full legal/branch name. Both are wording
	# evidence only after a customer record has actually been selected.
	buyers = {_wording(_field(doc, name)) for name in ('customer_name', 'customer_text')} - {''}
	aliases = context.get('company_aliases') or []
	aliases = aliases.splitlines() if isinstance(aliases, str) else aliases
	aliases = [_wording(value) for value in [context.get('receiving_company'), *aliases] if value]
	contains = lambda value: bool(value and re.search(r'(?<!\w)' + re.escape(value) + r'(?!\w)', text))
	if any(contains(buyer) and any(alias != buyer and contains(alias) for alias in aliases) for buyer in buyers) and not re.search(r'\b(?:quantity|quantities|qty|price|prices|rate|rates)\b', text):
		return bool(re.search(r'\b(?:customer|buyer|buying party)\b', text) and re.search(r'\bor\b|\bversus\b|\bvs\.?\b', text))
	return False


def current_review_questions(doc, business_context=None):
	"""Read-only current questions: refresh generated checks, keep real doubts.

	This display projection never edits the stored extraction or warning ledger.
	Only recognized historic templates/policy questions are removed; unsupported
	legacy phrasing remains reviewable because its origin cannot be recovered.
	"""
	stored = _field(doc, 'unresolved_questions') or ''
	stored = stored.splitlines() if isinstance(stored, str) else list(stored)
	context = business_context if business_context is not None else _company_context()
	questions = []
	for value in stored:
		question = str(value or '').strip()
		if not question or any(pattern.fullmatch(question) for pattern in _GENERATED_QUESTIONS):
			continue
		if not _obsolete_context_question(question, doc, context):
			questions.append(question)
	questions.extend(review_questions(doc, []))
	seen, result = set(), []
	for question in questions:
		key = _wording(question).rstrip('.?!')
		if key and key not in seen:
			seen.add(key)
			result.append(question)
	return result
