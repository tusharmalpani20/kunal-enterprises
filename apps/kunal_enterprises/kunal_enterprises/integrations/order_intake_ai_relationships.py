"""Conservative, source-backed boundaries between orders in the same chat.

These checks do not infer an order relationship from SKU similarity or elapsed
minutes. They retain uncertain item lists separately for staff to connect later.
The model still handles ordinary multipart text/media and non-English wording.
"""
import re


REVIEW_NOTE = 'These messages may be separate orders or a continuation. Kept separately; confirm their relationship before processing.'
TARGET_NOTE = 'The connection to an earlier request was not supported by source evidence. Kept as a separate request for review.'
SEPARATE_SCOPE = 'Interpret only this message as its own possible request. Do not borrow customer, warehouse, quantities or urgency from other messages. If it contains multiple explicit orders, preserve their separate scopes.'
CORRECTION = re.compile(r'\b(?:change|correct|correction|instead|revise|revised|replace|remove|cancel|update|reduce|increase|amend|reassign|make (?:it|that|the quantity)|not \d)\b', re.I)
CONTINUATION = re.compile(r'\b(?:same order|this order|that order|previous|earlier|above|remaining|also add|add to|for the order|for that|for this|continuation)\b', re.I)
CONFIRMATION = re.compile(r'\b(?:confirm|confirmed|confirmation|go ahead|proceed|book it)\b', re.I)
NEW_ORDER = re.compile(r'\b(?:new|another|separate|additional)\s+orders?\b', re.I)


def _normal(value):
	return ' '.join(str(value or '').split()).casefold()


def _item_line(line):
	# Product-like identifier followed by an order count. Do not treat bare
	# customer/dispatch fragments or an explicit correction as another item list.
	if any(char.isalpha() and not char.isascii() for char in line):
		return False
	return bool(re.search(r'\d{3,}', line) and re.search(r'\s\d+(?:\.\d+)?\s*(?:nos\.?|pcs\.?|sheets?|pieces?|units?|boxes?)?\s*$', line, re.I)
		and not CORRECTION.search(line) and not CONFIRMATION.search(line) and not CONTINUATION.search(line))


def _itemized(message):
	return any(_item_line(line) for line in str(message.get('message') or '').splitlines())


def _new_order(message):
	text = str(message.get('message') or '')
	return bool(NEW_ORDER.search(text) and not re.search(r'\b(?:not|isn.t|is not)\s+(?:a\s+)?(?:new|another|separate|additional)\s+order', text, re.I))


def _usable_evidence(entry, by_name):
	result = []
	for evidence in entry.relationship_evidence:
		message = by_name.get(evidence.source_message)
		quote = _normal(evidence.quote)
		if not message or evidence.source_message not in entry.message_ids or quote not in _normal(message.get('message')):
			continue
		lines = [line for line in evidence.quote.splitlines() if line.strip()]
		if sum(char.isalpha() for char in quote) < 6 or (lines and all(_item_line(line) for line in lines)):
			continue  # A repeated SKU/count cannot establish a correction.
		result.append(evidence)
	return result


def _reply_connected(names, related, by_name):
	for name in names:
		others = set(related) - {name}
		references = others | {str(by_name[n]['message_id']) for n in others if n in by_name and by_name[n].get('message_id')}
		message = by_name.get(name, {})
		if (message.get('reply_to_message_id') or (message.get('reply_context') or {}).get('message_id')) in references:
			return True
	return False


def _supported(entry, fresh, related, by_name, item_lists):
	if entry.relationship not in {'continuation', 'correction', 'confirmation'}:
		return False
	if _reply_connected(fresh, related, by_name):
		return True
	for evidence in entry.relationship_evidence:
		if entry.target_request and evidence.source_message not in fresh:
			continue  # Old instructions do not establish a new message's relationship.
		quote = evidence.quote
		# Preserve grounded non-English model judgments; the English safeguards
		# below must not turn English keywords into a universal language gate.
		if any(char.isalpha() and not char.isascii() for char in quote):
			return True
		if entry.relationship == 'correction' and CORRECTION.search(quote):
			return True
		if entry.relationship == 'confirmation' and CONFIRMATION.search(quote):
			return True
		if entry.relationship == 'continuation' and (CONTINUATION.search(quote) or CORRECTION.search(quote)):
			return True
		if entry.relationship == 'continuation' and item_lists < 2 and not any(_itemized(by_name[n]) for n in fresh):
			return True  # For example an item list followed by its party/warehouse.
	return False


def _copy(entry, names, target=None, relationship='uncertain', note=None, scope=None):
	return entry.model_copy(update=dict(message_ids=names, target_request=target, relationship=relationship,
		relationship_note=note, request_hint=scope or entry.request_hint,
		relationship_evidence=[e for e in entry.relationship_evidence if e.source_message in names]))


def constrain_relationships(result, messages, requests):
	"""Retain unsupported associations as independent, visible review requests."""
	by_name = {message['name']: message for message in messages}
	requests = {request['name']: request for request in requests}
	groups, unresolved = [], set(result.unresolved_message_ids)
	for entry in result.groups:
		entry.relationship_evidence = _usable_evidence(entry, by_name)
		previous = set(requests.get(entry.target_request, {}).get('source_messages') or [])
		fresh = [name for name in entry.message_ids if name not in previous]
		covered = [name for name in entry.message_ids if name in previous]
		if entry.target_request and not fresh:
			groups.append(entry)  # A covered-only group cannot duplicate its draft.
			continue
		item_lists = sum(_itemized(by_name[name]) for name in set(entry.message_ids) | (previous & by_name.keys()))
		supported = _supported(entry, fresh, previous if entry.target_request else set(entry.message_ids), by_name, item_lists)
		new = any(_new_order(by_name[name]) for name in fresh)
		explicit_correction = entry.relationship == 'correction' and supported and any(e.source_message in fresh and CORRECTION.search(e.quote) for e in entry.relationship_evidence)
		invalid_target = entry.target_request and (not supported or (new and not explicit_correction))
		unsafe_merge = sum(_itemized(by_name[name]) for name in fresh) > 1 and (not supported or (new and not explicit_correction))
		if invalid_target:
			if covered:
				groups.append(_copy(entry, covered, target=entry.target_request, relationship='continuation', note=None))
			for names in ([[name] for name in fresh] if unsafe_merge else [fresh]):
				note = None if new else TARGET_NOTE
				groups.append(_copy(entry, names, relationship='new' if new else 'uncertain', note=note,
					scope=SEPARATE_SCOPE if len(names) == 1 else entry.request_hint))
				if note:
					unresolved.update(names)
		elif unsafe_merge:
			for name in fresh:
				groups.append(_copy(entry, [name], note=REVIEW_NOTE, scope=SEPARATE_SCOPE))
			unresolved.update(fresh)
		else:
			groups.append(entry)
	# A bounded model schema cannot become an unbounded extraction job after
	# defensive splitting. Overflow messages stay explicit manual evidence.
	for entry in groups[20:]:
		unresolved.update(entry.message_ids)
	result.groups = groups[:20]
	result.unresolved_message_ids = [message['name'] for message in messages if message['name'] in unresolved]
	return result


def omitted_customer_qualifier(customer_text, messages):
	"""Detect a dropped qualifier on the same explicit party-name line.

	This checks source text, not master names. Free-form delivery/site lines and
	item quantities are not appended to a party merely because they follow it.
	"""
	base = _normal(customer_text)
	if not base:
		return False
	for message in messages:
		for line in str(message.get('message') or '').splitlines():
			line = re.sub(r'^\s*\d+[.)]\s*', '', line)
			line = re.sub(r'^\s*(?:order for|customer|party)\s*:?\s*', '', line, flags=re.I).strip()
			parts = re.split(r'\s+[-–—]\s+', line, maxsplit=1)
			if len(parts) != 2 or _normal(parts[0]) != base:
				continue
			qualifier = parts[1].strip()
			if not qualifier or re.match(r'\d|(?:dispatch|send|required|deliver|qty|quantity)\b', qualifier, re.I):
				continue
			return True
	return False
