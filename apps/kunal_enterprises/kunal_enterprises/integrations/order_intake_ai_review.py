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
