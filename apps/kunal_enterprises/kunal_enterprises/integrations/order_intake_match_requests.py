"""Resolve master suggestions without changing an existing human selection."""
import json

import frappe

from kunal_enterprises.integrations.order_intake_capture import _identity
from kunal_enterprises.integrations.order_intake_matching import search_candidates


def _search(kind, text, doc):
	if len(text or '') > 300:
		result = dict(candidates=[], selected=None, overflow=True, note='Long wording needs manual lookup.')
	else:
		result = search_candidates(kind, text)
	result['text'] = text or ''
	# Learning is scoped to this receiving account/sender and customer. It can
	# never be created by this matching operation or by merely saving a draft.
	if text and doc.whatsapp_account and doc.sender_number:
		from kunal_enterprises.integrations.order_intake_learning import lookup_confirmed
		learned = lookup_confirmed(kind, text, doc.whatsapp_account, doc.sender_number, doc.customer)
		if learned:
			# Multiple historical choices are alternatives, not a majority vote.
			choices = learned.get('candidates', [])
			if choices:
				if any(c['score'] == 100 and c['name'] != learned.get('selected') for c in result['candidates']):
					# A new exact master identity must not silently override or be
					# overridden by a conflicting historical alias.
					by_name = {c['name']: c for c in result['candidates'] + choices}
					result.update(candidates=list(by_name.values())[:5], selected=None,
						overflow=result['overflow'] or learned.get('overflow', False) or len(by_name) > 5)
				else:
					result.update(candidates=choices, selected=learned.get('selected'), overflow=learned.get('overflow', False))
	return result


def matching_context(doc):
	"""Master suggestions are valid only for this evidence and customer scope."""
	return dict(customer=doc.customer or '', whatsapp_account=doc.whatsapp_account or '',
		sender_number=doc.sender_number or '', customer_text=doc.customer_text or '', salesperson_text=doc.salesperson_text or '',
		items=sorted([dict(row_key=row.row_key or '', original_text=row.original_text or '', warehouse_text=row.warehouse_text or '')
			for row in doc.items], key=lambda row: row['row_key']))


def match_document(doc, autofill=True):
	"""Only populate blank master fields; quantities/units stay source-derived."""
	if len(doc.items) > 100:
		frappe.throw('Match at most 100 item rows at a time; all original rows are retained.')
	results = {}
	protected = set(frappe.parse_json(doc.get('manual_match_fields') or '[]'))
	count = 0
	identity = _identity(doc.sender_number) if doc.sender_number else {}
	for kind, field, text in (
		('customer', 'customer', doc.customer_text),
		('sales_employee', 'sales_employee', doc.salesperson_text),
	):
		result = _search(kind, text, doc)
		# A salesperson sender is never automatically used as the customer.
		# Explicit customer wording takes precedence over the sender's identity.
		if not text and identity.get(field):
			name = identity[field]
			label_field = 'customer_name' if kind == 'customer' else 'sales_employee_name'
			result.update(candidates=[dict(name=name, label=frappe.db.get_value(
				'Customer' if kind == 'customer' else 'Sales Employee', name, label_field),
				score=100, reason='Unique sender phone match')], selected=name)
		results[kind] = result
		if autofill and field not in protected and not doc.get(field) and result.get('selected'):
			doc.set(field, result['selected']); count += 1
	results['items'] = []
	for row in doc.items:
		entry = dict(row_key=row.row_key)
		for kind, field, text in (('item', 'item', row.original_text), ('godown', 'godown', row.warehouse_text)):
			result = _search(kind, text, doc)
			entry[kind] = result
			if autofill and f'{field}:{row.row_key}' not in protected and not row.get(field) and result.get('selected'):
				row.set(field, result['selected']); count += 1
			if kind == 'item':
				row.match_score = next((c['score'] for c in result['candidates'] if c['name'] == row.item), 0)
		results['items'].append(entry)
	results['context'] = matching_context(doc)
	doc.matching_json = json.dumps(results, ensure_ascii=False)
	return dict(state='Matched', selected_count=count,
		candidate_count=sum(len(r.get('candidates', [])) for r in [results['customer'], results['sales_employee'],
			*(r[k] for r in results['items'] for k in ('item', 'godown'))]))


def save_matches(doc):
	previous = frappe.flags.intake_matching_write
	try:
		frappe.flags.intake_matching_write = True
		result = match_document(doc)
		doc.save()
	finally:
		frappe.flags.intake_matching_write = previous
	return result


def match_new_document(doc):
	"""A lookup failure must not prevent preserving a possible order as a draft."""
	before = (doc.customer, doc.sales_employee,
		[(row.item, row.godown, row.match_score) for row in doc.items])
	try:
		return match_document(doc)
	except Exception as error:
		doc.customer, doc.sales_employee = before[:2]
		for row, values in zip(doc.items, before[2], strict=True):
			row.item, row.godown, row.match_score = values
		doc.matching_json = None
		doc.unresolved_questions = "\n".join(filter(None, [doc.unresolved_questions,
			"Master matching was unavailable. Original details are preserved; select records manually or use Find matches again."]))
		# Do not put customer text or provider credentials into framework errors.
		frappe.log_error(title="Order intake matching unavailable", message=type(error).__name__)
		return dict(state='Needs Review', selected_count=0, candidate_count=0)
