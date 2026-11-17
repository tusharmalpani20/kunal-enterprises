"""Bounded identity-only master searches for editable intake drafts.

Scores describe textual evidence, not calibrated probabilities. A clear closest match may fill a
draft; scores never establish customer authorization or final Order eligibility.
The caller is responsible for reviewer/source access before using this service.
"""
from difflib import SequenceMatcher
from decimal import Decimal
import re
import unicodedata

import frappe
from frappe.utils import cint


MASTERS = {
	"customer": ("Customer", "customer_name", ("customer_name", "business_legal_name", "client_code")),
	"sales_employee": ("Sales Employee", "sales_employee_name", ("sales_employee_name", "employee_code")),
	"item": ("Tally Item", "item_name", ("item_name",)),
	"godown": ("Tally Godown", "godown_name", ("godown_name",)),
}
POOL_LIMIT = 200


def normalized(text):
	text = unicodedata.normalize("NFKC", str(text or "")).casefold()
	# Preserve punctuation and Unicode combining marks as identity evidence.
	# A/B and A-B, MR and MR+, and Indic vowel marks must stay distinct.
	text = "".join(" " if unicodedata.category(char).startswith("C") else char for char in text)
	text = re.sub(r"(?<=\d)(?=[^\W\d_])|(?<=[^\W\d_])(?=\d)", " ", text)
	return " ".join(text.split())


def _numbers(text):
	# Leading zeroes are candidate evidence only, never an exact-name alias.
	return {Decimal(value)
		for value in re.findall(r"(?<!\d)\d+(?:\.\d+)?", text)}


def _measurements(text):
	# Keep a number attached to its explicit unit. A design/code elsewhere in
	# the name cannot make 120 kg compatible with a request for 20 kg.
	return {(Decimal(number), unit) for number, unit in re.findall(
		r"(?<![\d.])(\d+(?:\.\d+)?)\s*(kg|mm|cm|ml|ltr|litre|inch|feet|ft|in|g|m|l)\b", text)}


def _like(token):
	return "%" + token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _pool(doctype, fields, query):
	"""Retrieve bounded candidates without requiring literal word spacing."""
	tokens = [token for token in query.split() if any(char.isalnum() for char in token)]
	if not tokens:
		return [], False
	# Keep item retrieval anchored to a design number when one was supplied;
	# broader customer names must not introduce unrelated product codes.
	numeric = [match[1].lstrip("0") or "0" for token in tokens
		if (match := re.fullmatch(r"(\d{3,})[.,;:]?", token))] if doctype == "Tally Item" else []
	anchor = max(numeric or tokens, key=len)
	columns = tuple(dict.fromkeys(("name", *fields)))
	selected_columns = (*columns, 'root_stock_group') if doctype == 'Tally Item' else columns
	select = ",".join("`" + field + "`" for field in selected_columns)
	where = " OR ".join("`" + field + "` LIKE %s" for field in columns)
	params = [_like(anchor)] * len(columns)
	rows = []
	if doctype == "Customer" and len(tokens) > 1:
		# Customer branches often join/split words or omit a separator. This
		# broadens retrieval only; ranking still sees the original master label.
		compact = " OR ".join("REPLACE(REPLACE(`" + field + "`,' ',''),'-','') LIKE %s" for field in columns)
		conditions, token_params = [], []
		for token in tokens:
			conditions.append(f"(({where}) OR ({compact}))")
			token_params.extend([_like(token)] * len(columns))
			token_params.extend([_like(token.replace('-', ''))] * len(columns))
		all_tokens = " AND ".join(conditions)
		rows = frappe.db.sql(f"SELECT {select} FROM `tab{doctype}` WHERE {all_tokens} ORDER BY name LIMIT %s",
			(*token_params, POOL_LIMIT + 1), as_dict=True)
		if not rows:
			# A misspelled longest word (often a location) must not hide a party
			# whose trading-name words match. Prefer the most matching tokens,
			# preserving a 201st row to expose an incomplete candidate pool.
			any_token = " OR ".join(conditions)
			rank = " + ".join(f"COALESCE({condition},0)" for condition in conditions)
			rows = frappe.db.sql(f"SELECT {select} FROM `tab{doctype}` WHERE {any_token} ORDER BY ({rank}) DESC,name LIMIT %s",
				(*token_params, *token_params, POOL_LIMIT + 1), as_dict=True)
	if doctype == "Tally Item" and len(tokens) > 1:
		# A large brand catalogue can fill the bounded pool before its MDF or
		# other requested family appears alphabetically. Rank the anchored
		# candidates by all wording before applying the limit. This broadens
		# retrieval only; numeric/specification checks still control selection.
		rank = " + ".join(f"COALESCE(({where}),0)" for _ in tokens)
		rank_params = [value for token in tokens for value in [_like(token)] * len(columns)]
		rows = frappe.db.sql(f"SELECT {select} FROM `tab{doctype}` WHERE {where} ORDER BY ({rank}) DESC,name LIMIT %s",
			(*params, *rank_params, POOL_LIMIT + 1), as_dict=True)
	if not rows:
		rows = frappe.db.sql(f"SELECT {select} FROM `tab{doctype}` WHERE {where} ORDER BY name LIMIT %s",
			(*params, POOL_LIMIT + 1), as_dict=True)
	if not rows and len(anchor) >= 4 and not numeric:
		rows = frappe.db.sql(f"SELECT {select} FROM `tab{doctype}` WHERE {where} ORDER BY name LIMIT %s",
			(*([_like(anchor[:3])] * len(columns)), POOL_LIMIT + 1), as_dict=True)
	return rows[:POOL_LIMIT], len(rows) > POOL_LIMIT


def _core(kind, text):
	value = normalized(text)
	if kind == 'item':
		value = re.sub(r"\b(?:design|code|item|sku)\b", " ", value)
		# A separated order count is not a pack specification. Keep KG/MM/etc.
		# and literal catalogue names intact through the exact-name check below.
		value = re.sub(r'(?:\s+[-–—]\s+|\s*[:=]\s*)\d+(?:\.\d+)?\s*(?:sheets?|nos\.?|pcs\.?|pieces?|units?|boxes?)\s*$', '', value)
	elif kind == 'godown':
		# WhatsApp tags often prefix a dispatch place with @; it is not part of the master name.
		value = value.lstrip('@').strip()
		value = re.sub(r"\b(?:godown|warehouse)\b", " ", value)
	if kind in ('customer', 'godown'):
		value = re.sub(r'\s+[–—]\s+', ' - ', value)
	return " ".join(value.split())


def _customer_short_name(query, label):
	"""Recognize a complete trading name with a branch or legal suffix omitted.

	Only common business nouns fold singular/plural in this stronger-name check.
	Other wording differences use similarity scores; tied branches remain
	separate reviewable candidates rather than becoming exact aliases.
	"""
	plurals = {'plywoods': 'plywood', 'laminates': 'laminate', 'interiors': 'interior',
		'enterprises': 'enterprise', 'traders': 'trader'}
	def fold(value):
		value = re.sub(r'\s+[–—]\s+', ' - ', value)
		return re.sub(r'\b(?:' + '|'.join(plurals) + r')\b', lambda match: plurals[match[0]], value)
	query = fold(query)
	if len(query.split()) < 2:
		return False
	label = fold(label)
	parts = re.split(r'\s+-\s*', label, maxsplit=1)
	base = parts[0]
	# WhatsApp senders often include the branch without the catalogue dash.
	# Compare the entire ordered name, retaining proper-name prefixes such as
	# Jai/Ram; substring overlap must not turn those into the same party.
	full_without_separator = ' '.join(parts)
	without_legal = re.sub(r'(?:\s+(?:private|pvt\.?|limited|ltd\.?|llp|inc\.?))+$', '', base)
	return query in (label, base, without_legal, full_without_separator)


def _customer_name_prefix(query, label):
	"""A misspelled short trading name can precede legal and branch details.

	Compare every query word in order with the beginning of the master label.
	This prevents a shorter unrelated party sharing only 'interior' from beating
	'Step in Interiors India Pvt Ltd - Hyderabad' for 'Step in Interiore'.
	"""
	words, target = query.split(), label.split()
	if len(words) < 2 or len(target) < len(words):
		return False
	return all(word == option or (len(word) >= 4 and len(option) >= 4
		and SequenceMatcher(None, word, option).ratio() >= .85)
		for word, option in zip(words, target))


def _compatible_words(query, alias):
	"""Short variants/units must agree; longer words may have small typos.

	A trailing plus is similarity evidence (MR/MR+), not an exact alias.
	Numbers are checked separately, including design codes and pack sizes.
	"""
	words = [word for word in query.split() if not _numbers(word)]
	options = [word.rstrip('+') for word in alias.split()]
	return all(any(word.rstrip('+') == option or
		(len(word) >= 4 and len(option) >= 4 and SequenceMatcher(None, word, option).ratio() >= .85)
		for option in options) for word in words)


def _item_code_variant(query, label, root_group):
	"""Strong catalogue evidence for brand/design/variant shorthand.

	Only descriptive sheet wording may be absent from the catalogue name.
	Unknown brands or variant words are never discarded, and equal matches still
	need the normal uniqueness margin before filling an editable draft.
	"""
	words, label_words = set(query.split()), set(label.split())
	designs = {word.lstrip('0') or '0' for word in words if word.isdigit() and len(word) >= 3}
	label_designs = {word.lstrip('0') or '0' for word in label_words if word.isdigit() and len(word) >= 3}
	variants = {word for word in words if re.fullmatch(r'[a-z]{1,3}\+?', word)}
	if not designs or not designs <= label_designs or not variants or not variants <= label_words:
		return False
	context = label_words | set(normalized(root_group).split())
	brand_words = {word for word in words & context if len(word) >= 4 and word.isalpha()}
	descriptive = {'liner', 'laminate', 'laminates', 'sheet', 'sheets'}
	if not brand_words - descriptive:
		return False
	return all(word in context or word in descriptive or word.isdigit() for word in words)


def _partial_catalogue_identity(query, label, root_group):
	"""Retain brand/code/finish candidates when colour prose is absent in Tally.

	A complete root-group brand and explicit finish must be supported. Missing
	wording is never an alias; equal candidates from different families remain
	unselected so the reviewer can decide from the original attachment.
	"""
	words, target = set(query.split()), set(label.split())
	brand = {word for word in normalized(root_group).split() if word.isalpha() and len(word) >= 4}
	codes = {word.lstrip('0') or '0' for word in words if word.isdigit() and len(word) >= 3}
	target_codes = {word.lstrip('0') or '0' for word in target if word.isdigit() and len(word) >= 3}
	variants = {word for word in words if re.fullmatch(r'[a-z]{1,3}\+?', word)}
	return bool(len(brand) >= 2 and brand <= words and codes and codes <= target_codes
		and variants and variants <= target)


def _best(candidates, truncated, kind):
	if not candidates:
		return None
	top = candidates[0]
	# Intake fields are editable suggestions, not identity decisions. A close
	# tie or bounded search is a reason to review, rather than leave work blank.
	if kind == 'item' and top.get('incomplete_wording') and any(row.get('reasonable') and row['score'] >= top['score'] for row in candidates[1:]):
		return None
	if kind in {'customer', 'item', 'godown'}:
		return top['name'] if top.get('reasonable') and top['score'] >= 60 else None
	if truncated:
		return None
	margin = top['score'] - candidates[1]['score'] if len(candidates) > 1 else 100
	if top['score'] == 100:
		return top['name'] if margin > 0 else None
	return top['name'] if top.get('reasonable') and top['score'] >= 85 and margin >= 6 else None


def _warehouse_options(text, limit):
	"""A slash lists alternatives, not quantities to distribute between godowns."""
	if '/' not in text:
		return None
	# A literal master name containing a slash remains one warehouse.
	if any(frappe.db.exists('Tally Godown', value) for value in (text, _core('godown', text))):
		return None
	options = [part.strip() for part in text.split('/') if part.strip()]
	if len(options) < 2:
		return None
	results = [(option, search_candidates('godown', option, limit=limit)) for option in options[:20]]
	selected = next((result['selected'] for _, result in results if result['selected']), None)
	# Put each option's best match first, then retain the other suggestions.
	candidates = {}
	for _, result in results:
		for row in result['candidates']:
			if row['name'] == result['selected']:
				candidates.setdefault(row['name'], row.copy())
	for _, result in results:
		for row in result['candidates']:
			candidates.setdefault(row['name'], row.copy())
	if selected:
		candidates[selected]['reason'] = 'First matching warehouse option; please review'
	return dict(candidates=list(candidates.values())[:limit], selected=selected,
		review_required=bool(selected), overflow=len(options) > 20 or len(candidates) > limit or any(result['overflow'] for _, result in results),
		warehouse_options=[dict(wording=option, selected=result['selected']) for option, result in results])


def search_candidates(kind, text, limit=5):
	if kind not in MASTERS:
		frappe.throw("Unsupported intake master lookup")
	limit = min(max(cint(limit), 1), 20)
	text = str(text or "").strip()
	if len(text) > 300:
		frappe.throw("Use at most 300 characters for an intake master lookup")
	if kind == 'godown':
		options = _warehouse_options(text, limit)
		if options is not None:
			return options
	literal_query = normalized(text)
	query = _core(kind, text) or literal_query
	if not re.search(r"\w", query, re.UNICODE):
		return dict(candidates=[], selected=None, overflow=False)
	doctype, label_field, fields = MASTERS[kind]
	rows, truncated = _pool(doctype, fields, query)
	candidates = []
	for row in rows:
		aliases = [normalized(row.get(field)) for field in ("name", *fields) if row.get(field)]
		is_exact = literal_query in aliases
		# An internal document ID may coincidentally contain the requested
		# number. For non-exact wording, identity numbers must belong to the
		# displayed master name; exact customer/employee code lookups still work.
		if not is_exact and not _numbers(query) <= _numbers(normalized(row.get(label_field))):
			continue
		if kind == 'item' and not is_exact and _measurements(query) - _measurements(normalized(row.get(label_field))):
			continue
		short_customer = kind == 'customer' and _customer_short_name(query, normalized(row.get(label_field)))
		prefix_customer = kind == 'customer' and _customer_name_prefix(query, normalized(row.get(label_field)))
		code_variant = kind == 'item' and _item_code_variant(query, normalized(row.get(label_field)), row.get('root_stock_group'))
		partial_catalogue = kind == 'item' and _partial_catalogue_identity(query, normalized(row.get(label_field)), row.get('root_stock_group'))
		if is_exact:
			score, reason = 100, "Exact name or code"
		elif query in aliases:
			score, reason = 99, "Closest wording; please review"
		elif short_customer:
			score, reason = 95, "Short trading name; please review the party and branch"
		elif prefix_customer:
			score, reason = 93, "Short trading name with minor spelling difference; please review the party and branch"
		elif code_variant:
			score, reason = 90, "Brand, design and variant match; please review the item"
		elif partial_catalogue:
			score, reason = 80, "Brand, code and finish match; remaining wording needs review"
		else:
			similarity = max(SequenceMatcher(None, query, alias).ratio() for alias in aliases)
			if kind in {'customer', 'godown'}:
				# Spacing differences are similarity evidence, never exact aliases.
				compact = lambda value: re.sub(r'[\s&–—-]+', '', value)
				similarity = max(similarity, max(SequenceMatcher(None, compact(query), compact(alias)).ratio() for alias in aliases))
			query_words = set(query.split())
			overlap = max(len(query_words & set(alias.split())) / len(query_words) for alias in aliases)
			score = min(99, round(100 * max(similarity, overlap * .85)))
			if score < 35:
				continue
			reason = "Closest wording; please review"
		compatible = is_exact or short_customer or prefix_customer or code_variant or partial_catalogue or any(_numbers(query) <= _numbers(alias) and _compatible_words(query, alias) for alias in aliases)
		if kind == 'customer' and score >= 60:
			compatible = True
		if kind == 'godown' and any(re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', query) for alias in aliases):
			compatible = True
		if not compatible:
			score = min(score, 74)
			reason = "Some wording or variant differs; please check"
		candidates.append(dict(name=row.name, label=row.get(label_field) or row.name, score=score, reason=reason,
			reasonable=compatible, incomplete_wording=bool(partial_catalogue and not code_variant and not is_exact)))
	candidates.sort(key=lambda row: (not row["reasonable"] if kind != "sales_employee" else False, -row["score"], row["label"].casefold(), row["name"]))
	selected = _best(candidates, truncated, kind)
	return dict(candidates=candidates[:limit], selected=selected,
		review_required=bool(selected and (truncated or candidates[0]['score'] < 100 or
			(len(candidates) > 1 and candidates[0]['score'] == candidates[1]['score']))),
		overflow=truncated or len(candidates) > limit)
