"""Bounded retrieval of confirmed examples, never a transcript/history dump.

Examples are reference evidence, not commands. Exact master matching remains a
separate deterministic step; a similar request-type example cannot set intent.
"""
import json
import re

import frappe

from kunal_enterprises.integrations.order_intake_ai_input import model_messages
from kunal_enterprises.integrations.order_intake_learning import normalize_text

MAX_BYTES = 1800
MAX_EXAMPLES = 3
INTENTS = {'order', 'book', 'booking', 'confirm', 'confirmed', 'confirmation', 'purchase',
	'price', 'prices', 'rate', 'rates', 'quotation', 'quote', 'stock', 'availability', 'available', 'inquiry'}
STOP = {'the', 'and', 'for', 'from', 'this', 'that', 'with', 'please', 'send', 'sheet', 'sheets', 'nos', 'pcs', 'godown', 'warehouse'}


def _words(value):
	return {word for word in re.findall(r'[^\W\d_]+', normalize_text(value), re.UNICODE)
		if len(word) >= 3 and word not in STOP}


def _score(kind, original, text):
	original, text = normalize_text(original), normalize_text(text)
	if not original or not text:
		return 0
	if kind != 'request_type':
		# Only literal alias wording is useful; fuzzy matches already have a
		# separate scoring/review path. Plus is meaningful catalogue wording:
		# a confirmed MR alias must not silently become evidence for MR+.
		return 100 if re.search(r'(?<![\w+])' + re.escape(original) + r'(?![\w+])', text) else 0
	left, right = _words(original), _words(text)
	if original == text:
		intent = bool(left & INTENTS)
		non_english = sum(any(not char.isascii() for char in word) for word in left) >= 2
		return 100 if intent or non_english else 0
	shared = left & right
	if len(shared) < 2:
		return 0
	jaccard = len(shared) / max(len(left | right), 1)
	# A repeated SKU/customer alone says nothing about buying versus asking.
	# For other scripts, require much closer wording instead of English gates.
	intent = bool(shared & INTENTS)
	non_english = sum(any(not char.isascii() for char in word) for word in shared) >= 2
	return round(jaccard * 100) if (intent and jaccard >= .25) or (non_english and jaccard >= .7) else 0


def _short(value, limit):
	text = ' '.join(str(value or '').split())
	return text if len(text) <= limit else text[:limit - 1] + '…'


def _rows(account, sender):
	# Both branches validate the CURRENT confirmed source, so cancelled orders,
	# reopened inquiries and stale evidence stop contributing without a purge.
	return frappe.db.sql("""SELECT e.kind,e.original_text,e.selected_master,e.suggested_value,
		e.correction_reason,e.message_excerpt,e.was_corrected,e.customer_context,r.sender_number AS source_sender,
		CASE e.kind
		 WHEN 'customer' THEN (SELECT customer_name FROM `tabCustomer` m WHERE m.name=e.selected_master)
		 WHEN 'sales_employee' THEN (SELECT sales_employee_name FROM `tabSales Employee` m WHERE m.name=e.selected_master)
		 WHEN 'item' THEN (SELECT item_name FROM `tabTally Item` m WHERE m.name=e.selected_master)
		 WHEN 'godown' THEN (SELECT godown_name FROM `tabTally Godown` m WHERE m.name=e.selected_master)
		 ELSE e.selected_master END AS confirmed_label
		FROM `tabOrder Intake Match Evidence` e
		INNER JOIN `tabOrder Intake Request` r ON r.name=e.source_request
		LEFT JOIN `tabOrder` o ON o.name=e.source_order
		WHERE e.active=1 AND e.whatsapp_account=%s AND e.sender=%s
		AND r.whatsapp_account=e.whatsapp_account AND r.sender_number IS NOT NULL
		AND ((e.kind='customer' AND EXISTS (SELECT 1 FROM `tabCustomer` m WHERE m.name=e.selected_master))
		 OR (e.kind='sales_employee' AND EXISTS (SELECT 1 FROM `tabSales Employee` m WHERE m.name=e.selected_master))
		 OR (e.kind='item' AND EXISTS (SELECT 1 FROM `tabTally Item` m WHERE m.name=e.selected_master AND m.is_active=1))
		 OR (e.kind='godown' AND EXISTS (SELECT 1 FROM `tabTally Godown` m WHERE m.name=e.selected_master AND m.is_active=1))
		 OR e.kind='request_type')
		AND (e.kind!='request_type' OR (COALESCE(e.source_excerpt_truncated,0)=0
		 AND CHAR_LENGTH(COALESCE(NULLIF(e.message_excerpt,''),e.original_text,''))<1000))
		AND (e.kind!='request_type' OR NOT EXISTS (
		 SELECT 1 FROM `tabOrder Intake Source Message` s INNER JOIN `tabOrder Intake Source Message` other
		 ON other.message=s.message AND other.parent!=s.parent
		 WHERE s.parent=r.name AND s.parenttype='Order Intake Request' AND other.parenttype='Order Intake Request'))
		AND (
		 (r.status='Converted to Order' AND r.`order`=o.name AND o.status!='Cancelled'
		 AND o.docstatus!=2 AND r.customer=o.customer AND (
		  (e.kind='customer' AND e.selected_master=r.customer)
		  OR (e.kind='sales_employee' AND e.selected_master=r.sales_employee AND r.sales_employee=o.sales_employee)
		  OR (e.kind='item' AND e.customer_context=r.customer AND EXISTS
		   (SELECT 1 FROM `tabOrder Intake Item` i INNER JOIN `tabOrder Item` oi ON oi.parent=o.name AND oi.item=i.item
		    WHERE i.parent=r.name AND i.row_key=e.row_key AND i.item=e.selected_master))
		  OR (e.kind='godown' AND e.customer_context=r.customer AND EXISTS
		   (SELECT 1 FROM `tabOrder Intake Item` i INNER JOIN `tabOrder Godown Allocation` a ON a.parent=o.name AND a.item=i.item
		    WHERE i.parent=r.name AND i.row_key=e.row_key AND i.godown=e.selected_master AND a.godown=e.selected_master))
		  OR (e.kind='request_type' AND e.was_corrected=1 AND e.selected_master=r.request_type)
		 ))
		 OR (r.status='Resolved' AND r.modified<=e.creation
		 AND r.processed_at IS NOT NULL AND COALESCE(r.reviewed_by,'')!=''
		 AND r.request_type IN ('Stock Inquiry','Price Inquiry') AND COALESCE(r.`order`,'')=''
		 AND COALESCE(e.source_order,'')='' AND e.kind='request_type' AND e.was_corrected=1
		 AND e.selected_master=r.request_type)
		)
		ORDER BY e.creation DESC,e.name DESC LIMIT 100""", (account, sender), as_dict=True)


def confirmed_learning(snapshot):
	"""Return at most three relevant examples within a fixed UTF-8 JSON budget.

	Only the supplied receiving account and normalized sender are searched. Item
	and warehouse examples additionally require one known customer, avoiding an
	unrelated customer's shorthand when a salesperson sends for several parties.
	"""
	from kunal_enterprises.kunal_enterprises.doctype.order_intake_request.order_intake_request import _sender_key
	account, sender = snapshot.get('whatsapp_account'), _sender_key(snapshot.get('sender') or '')
	if not account or not sender:
		return []
	messages = model_messages(snapshot.get('messages') or [])
	text = '\n'.join(row.get('message') or '' for row in messages)
	if not text.strip():
		return []
	rows = [row for row in _rows(account, sender) if _sender_key(row.source_sender) == sender]
	# An earlier open order in the same chat does not establish the party for
	# fresh messages. Only explicit scope or an unambiguous current alias can.
	customers = {snapshot['customer']} if snapshot.get('customer') else set()
	if not customers:
		aliases = {}
		for row in rows:
			if row.kind == 'customer' and _score('customer', row.original_text, text):
				aliases.setdefault(normalize_text(row.original_text), set()).add(row.selected_master)
		if not any(len(choices) > 1 for choices in aliases.values()):
			customers.update(next(iter(choices)) for choices in aliases.values())
	ranked = []
	for index, row in enumerate(rows):
		if row.kind in {'item', 'godown'} and (len(customers) != 1 or row.customer_context not in customers):
			continue
		if row.kind not in {'customer', 'sales_employee', 'item', 'godown', 'request_type'}:
			continue
		original = (row.message_excerpt or row.original_text) if row.kind == 'request_type' else row.original_text
		score = max((_score(row.kind, original, message.get('message') or '') for message in messages), default=0)
		if score:
			ranked.append((-score, index, row, original))
	selections = {}
	for _, _, row, _ in ranked:
		alias_key = (row.kind, normalize_text(row.original_text), row.customer_context or '')
		selections.setdefault(alias_key, set()).add(row.selected_master)
	result, seen = [], set()
	for _, _, row, original in sorted(ranked, key=lambda entry: (entry[2].kind != 'request_type', *entry[:2])):
		key = (row.kind, normalize_text(row.original_text), row.selected_master)
		if key in seen:
			continue
		seen.add(key)
		# Never cut a classification/alias phrase mid-way: a later negation or
		# variant can change its meaning. The total JSON byte cap below drops
		# oversized examples instead of presenting a misleading prefix.
		example = dict(kind=row.kind, wording=' '.join(str(original or '').split()), confirmed=row.selected_master)
		if row.confirmed_label and row.confirmed_label != row.selected_master:
			example['label'] = _short(row.confirmed_label, 140)
		if len(selections[(row.kind, normalize_text(row.original_text), row.customer_context or '')]) > 1:
			example['conflicting'] = True
		if row.customer_context:
			example['customer'] = row.customer_context
		if row.was_corrected:
			example['previous'] = _short(row.suggested_value, 140)
		if row.correction_reason:
			example['reason'] = _short(row.correction_reason, 180)
		candidate = result + [example]
		if len(json.dumps(candidate, ensure_ascii=False).encode('utf-8')) > MAX_BYTES:
			continue
		result = candidate
		if len(result) >= MAX_EXAMPLES:
			break
	return result


def relevant_examples(examples, messages, customer=None):
	"""Filter the already bounded batch examples to one extraction's source scope.

	No database or model call is made. An order for another customer in the same
	batch must not borrow an item/warehouse alias from the current group.
	"""
	semantic = model_messages(messages)
	texts = [row.get('message') or '' for row in semantic]
	customers = {customer} if customer else set()
	if not customer:
		parties = [example for example in examples if example.get('kind') == 'customer'
			and any(_score('customer', example.get('wording'), text) for text in texts)]
		if not any(example.get('conflicting') for example in parties):
			customers.update(example['confirmed'] for example in parties)
	result = []
	for example in examples:
		kind = example.get('kind')
		if kind in {'item', 'godown'} and (len(customers) != 1 or example.get('customer') not in customers):
			continue
		if any(_score(kind, example.get('wording'), text) for text in texts):
			result.append(example)
	return result
