"""Durable AI claims and fenced draft publication; no actual Order conversion."""
import hashlib
import json
from functools import partial
from uuid import uuid4

import frappe
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from kunal_enterprises.integrations import order_intake_queue as preparation
from kunal_enterprises.integrations.order_intake_ai_models import AIProblem, InputTooLarge, RequestBudget, group, extract
from kunal_enterprises.integrations.order_intake_ai_state import TRANSFER_NOTE
from kunal_enterprises.integrations.order_intake_ai_input import model_messages
from kunal_enterprises.integrations.order_intake_business_context import business_context
from kunal_enterprises.integrations.order_intake_learning_context import confirmed_learning, relevant_examples
from kunal_enterprises.integrations.order_intake_ai_logging import RunRecorder, LoggingFailure, LoggingAlreadyStarted

DT = "WhatsApp Message"
MAX_HISTORY_MESSAGES = 100
FIELDS = ("name", "type", "whatsapp_account", "from", "profile_name", "message", "message_id", "attach", "content_type",
	"reply_to_message_id", "intake_received_at", "intake_sender_key", "intake_media_filename", "intake_media_id",
	"intake_original_type", "intake_has_location", "intake_latitude", "intake_longitude", "intake_location_address",
	"intake_location_name", "intake_raw_payload", "intake_legacy_evidence", "intake_ai_coverage",
	"intake_sent_at", "intake_media_mime", "intake_identity_type")


def _json(value):
	return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _digest(value):
	return hashlib.sha256(_json(value).encode()).hexdigest()


def _terminal_source_ids(names):
	"""Explicit recovery may inspect completed evidence without reclaiming it."""
	if not names:
		return []
	rows = frappe.db.sql("""SELECT DISTINCT s.message FROM `tabOrder Intake Source Message` s
		JOIN `tabOrder Intake Request` r ON r.name=s.parent
		WHERE s.parenttype='Order Intake Request' AND s.message IN %(names)s
		AND r.status IN ('Converted to Order','Resolved','Dismissed')
		AND NOT EXISTS (SELECT 1 FROM `tabOrder Intake Source Message` other
		 JOIN `tabOrder Intake Request` active ON active.name=other.parent
		 WHERE other.parenttype='Order Intake Request' AND other.message=s.message
		 AND COALESCE(active.status,'') NOT IN ('Converted to Order','Resolved','Dismissed'))""",
		{"names": tuple(names)})
	return sorted(row[0] for row in rows)


def _snapshot(anchor):
	doc = frappe.get_doc(DT, anchor)
	context = frappe.parse_json(doc.intake_context_ids or "null")
	if doc.intake_prepare_state != preparation.READY or not context or doc.intake_context_anchor != anchor:
		raise AIProblem("Prepare this sender's context before creating drafts.")
	names = context["message_ids"]
	all_names = list(dict.fromkeys(names + context.get("reply_message_ids", []) + context.get("manual_review_message_ids", [])))
	messages = []
	for name in all_names:
		row = frappe.get_doc(DT, name)
		if row.type != "Incoming" or row.whatsapp_account != doc.whatsapp_account or (row.intake_sender_key or preparation._sender_key(row.get("from"))) != doc.intake_sender_key or row.intake_status == "Duplicate":
			raise AIProblem("The source chat changed; prepare its context again.")
		if name in names and (row.intake_context_anchor != anchor or row.intake_context_digest != doc.intake_context_digest or row.intake_prepare_state != preparation.READY):
			raise AIProblem("The prepared context changed; prepare the sender again.")
		data = {field: row.get(field) for field in FIELDS}
		if row.attach:
			data["file_evidence"] = frappe.get_all("File", filters={"file_url": row.attach},
				fields=["name", "content_hash", "modified", "is_private", "file_size"], order_by="name", limit_page_length=20)
		messages.append(data)
	requests = []
	# Preparation can predate drafts from an earlier AI run. Rebuild current
	# related requests from the source ledger, not stale context hints.
	related, overflow = preparation._open_requests(doc.whatsapp_account, doc.intake_sender_key, all_names)
	recent, recent_overflow = preparation.recent_open_requests(doc.whatsapp_account, doc.intake_sender_key, doc.intake_prepared_at)
	related = list({entry["name"]: entry for entry in related + recent}.values())
	overflow = overflow or recent_overflow or len(related) > preparation.MAX_REFERENCES
	if overflow:
		raise AIProblem("Too many related drafts need review; narrow this context before processing.")
	for entry in related:
		request = frappe.get_doc("Order Intake Request", entry["name"])
		if request.whatsapp_account != doc.whatsapp_account or preparation._sender_key(request.sender_number) != doc.intake_sender_key:
			raise AIProblem("A related request no longer belongs to this chat; prepare context again.")
		if request.status not in ("Pending Review", "In Review", "Awaiting Confirmation"):
			continue
		requests.append(dict(name=request.name, modified=str(request.modified), request_type=request.request_type,
			status=request.status, customer=request.customer, customer_name=request.customer_name,
			sales_employee=request.sales_employee, summary=request.estimated_interpretation,
			items=[{key: item.get(key) for key in ("original_text", "item", "quantity", "unit", "godown", "warehouse_text")} for item in request.items],
			source_messages=[row.message for row in request.source_messages]))
	# Keep original evidence available for an identified continuation, but do not
	# send every open draft's message history to the grouping model.
	grouping_ids = [message['name'] for message in messages]
	related_ids = []
	for request in requests:
		extra = set(request['source_messages']) - set(grouping_ids) - set(related_ids)
		if len(set(related_ids) | extra) > MAX_HISTORY_MESSAGES:
			# A large old draft must not prevent preserving a fresh independent
			# order. Updating that draft remains an explicit manual-review case.
			request['evidence_needs_manual_review'] = True
			continue
		related_ids.extend(sorted(extra))
	for name in related_ids:
		if name in grouping_ids:
			continue
		row = frappe.get_doc(DT, name)
		if row.type != 'Incoming' or row.whatsapp_account != doc.whatsapp_account or preparation._sender_key(row.get('from')) != doc.intake_sender_key:
			raise AIProblem("Related draft evidence no longer belongs to this chat; prepare it again.")
		data = {field: row.get(field) for field in FIELDS}
		if row.attach:
			data['file_evidence'] = frappe.get_all('File', filters={'file_url': row.attach},
				fields=['name', 'content_hash', 'modified', 'is_private', 'file_size'], order_by='name', limit_page_length=20)
		messages.append(data)
	snapshot = dict(anchor=anchor, whatsapp_account=doc.whatsapp_account, sender=doc.intake_sender_key,
		context_digest=doc.intake_context_digest, message_ids=names, messages=messages, open_requests=requests,
		grouping_message_ids=grouping_ids,
		context_only_ids=list(dict.fromkeys(_terminal_source_ids(grouping_ids) + [name for name in context.get("reply_message_ids", []) if name not in names and name not in context.get("manual_review_message_ids", [])] + [name for name in related_ids if name not in grouping_ids])),
		business_context=business_context())
	try:
		snapshot['confirmed_learning'] = confirmed_learning(snapshot)
	except Exception as error:
		# Optional history cannot prevent preserving a new possible order.
		frappe.log_error(title='Confirmed intake learning unavailable', message=type(error).__name__)
		snapshot['confirmed_learning'] = []
	return snapshot


def _set(anchor, values):
	frappe.db.set_value(DT, anchor, values, update_modified=False)


def _claim(anchor, force=False):
	doc = frappe.get_doc(DT, anchor)
	preparation._lock_account(doc.whatsapp_account)
	doc.reload()
	now = now_datetime()
	active = frappe.db.sql("SELECT name FROM `tabWhatsApp Message` WHERE whatsapp_account=%s AND intake_sender_key=%s AND intake_ai_state='Queued' AND intake_ai_lease_until > %s LIMIT 1 FOR UPDATE", (doc.whatsapp_account, doc.intake_sender_key, now))
	if active:
		return dict(state="Busy", anchor=active[0][0])
	if not force:
		waiting = frappe.db.sql("""SELECT name FROM `tabWhatsApp Message`
			WHERE whatsapp_account=%s AND intake_sender_key=%s AND intake_ai_state='Retry'
			AND intake_ai_retry_at > %s ORDER BY intake_ai_retry_at DESC LIMIT 1 FOR UPDATE""",
			(doc.whatsapp_account, doc.intake_sender_key, now))
		if waiting:
			# New messages and a changed context anchor must respect the chat's
			# provider backoff, rather than restarting it on every arrival.
			return dict(state="Retry", anchor=waiting[0][0])
	snapshot = _snapshot(anchor)
	digest = _digest(snapshot)
	if doc.intake_ai_prepared_digest == doc.intake_context_digest:
		if doc.intake_ai_state in ("Drafted", "Unresolved") or (doc.intake_ai_state == "Needs Attention" and not force):
			return dict(state="Unchanged", anchor=anchor)
		if not force and doc.intake_ai_state == "Retry" and doc.intake_ai_retry_at and get_datetime(doc.intake_ai_retry_at) > now:
			return dict(state="Retry", anchor=anchor)
	# New arrivals do not reset an ongoing provider outage's retry progression.
	# Transfer it to the current anchor so a successful new batch can reset it.
	prior_attempts = frappe.db.sql("""SELECT COALESCE(MAX(intake_ai_attempts),0)
		FROM `tabWhatsApp Message` WHERE whatsapp_account=%s AND intake_sender_key=%s
		AND intake_ai_state='Retry'""", (doc.whatsapp_account, doc.intake_sender_key))[0][0]
	attempts = max(cint(prior_attempts), cint(doc.intake_ai_attempts) if doc.intake_ai_digest == digest else 0)
	frappe.db.sql("""UPDATE `tabWhatsApp Message` SET intake_ai_state='Needs Attention',
		intake_ai_retry_at=NULL, intake_ai_note=%s
		WHERE whatsapp_account=%s AND intake_sender_key=%s AND name!=%s AND intake_ai_state='Retry'""",
		(TRANSFER_NOTE, doc.whatsapp_account, doc.intake_sender_key, anchor))
	token = uuid4().hex
	_set(anchor, dict(intake_ai_state="Queued", intake_ai_token=token, intake_ai_digest=digest,
		intake_ai_attempts=attempts + 1, intake_ai_retry_at=None, intake_ai_prepared_digest=doc.intake_context_digest,
		intake_ai_lease_until=add_to_date(now, minutes=20, as_datetime=True),
		intake_ai_note="AI processing queued; original messages remain available."))
	return dict(state="Queued", anchor=anchor, token=token)


def _fail(anchor, token, note, retry=False):
	row = frappe.db.get_value(DT, anchor, ["whatsapp_account", "intake_ai_token"], as_dict=True)
	if not row:
		return
	if row.whatsapp_account and frappe.db.exists("WhatsApp Account", row.whatsapp_account):
		preparation._lock_account(row.whatsapp_account)
	else:
		retry = False
		note = "The receiving account is unavailable; original messages are retained for manual review."
	doc = frappe.get_doc(DT, anchor, for_update=True)
	if doc.intake_ai_token != token or doc.intake_ai_state != "Queued":
		return
	config = frappe.get_single("Order Intake Settings")
	delays = [int(value) for value in config.deferred_retry_minutes.split(",")]
	attempt = cint(doc.intake_ai_attempts)
	retry = retry and attempt <= len(delays)
	if not retry:
		attention = doc.intake_attention or ""
		warning = "AI: Processing needs attention; original messages are retained."
		_set(anchor, dict(intake_status="Needs Attention", intake_attention=attention if warning in attention else "\n".join(filter(None, (attention, warning)))))
	_set(anchor, dict(intake_ai_state="Retry" if retry else "Needs Attention", intake_ai_token=None,
		intake_ai_lease_until=None, intake_ai_note=note,
		intake_ai_retry_at=add_to_date(now_datetime(), minutes=delays[max(0, attempt-1)], as_datetime=True) if retry else None))


def _publish(anchor, token):
	try:
		frappe.enqueue("kunal_enterprises.integrations.order_intake_ai.process", queue="long", timeout=1100,
			job_id="order-intake-ai-" + token, anchor=anchor, token=token)
	except Exception:
		_fail(anchor, token, "The background queue is unavailable; retained for AI retry.", True)
		frappe.db.commit()


def dispatch(anchor=None, force=False):
	config = frappe.get_single("Order Intake Settings")
	if not force and not config.processing_enabled:
		return dict(state="Disabled", queued=0)
	# Recover expired claims even when the original ready context aged out.
	stale = frappe.get_all(DT, filters={"intake_ai_state": "Queued", "intake_ai_lease_until": ("<=", now_datetime())},
		fields=["name", "intake_ai_token"], limit_page_length=20)
	for row in stale:
		_fail(row.name, row.intake_ai_token, "The AI worker lease expired; retained for retry.", True)
	now = now_datetime()
	anchors = [anchor] if anchor else [row.name for row in frappe.db.sql(f"""SELECT candidate.name FROM `tabWhatsApp Message` candidate
		WHERE candidate.type='Incoming' AND {preparation.pending_source_sql('candidate')} AND candidate.intake_prepare_state='Context Ready' AND COALESCE(candidate.intake_context_ids,'') != ''
		AND (COALESCE(candidate.intake_ai_prepared_digest,'') != COALESCE(candidate.intake_context_digest,'')
		OR COALESCE(candidate.intake_ai_state,'') IN ('','Pending')
		OR (candidate.intake_ai_state='Retry' AND (candidate.intake_ai_retry_at IS NULL OR candidate.intake_ai_retry_at <= %s)))
		AND NOT EXISTS (SELECT 1 FROM `tabWhatsApp Message` busy
			WHERE busy.whatsapp_account <=> candidate.whatsapp_account AND busy.intake_sender_key <=> candidate.intake_sender_key
			AND ((busy.intake_ai_state='Queued' AND busy.intake_ai_lease_until > %s)
			OR (busy.intake_ai_state='Retry' AND busy.intake_ai_retry_at > %s)))
		ORDER BY candidate.intake_prepared_at, candidate.name LIMIT 20""", (now, now, now), as_dict=True)]
	results = []
	for name in anchors:
		point = "ai_claim_" + uuid4().hex[:12]
		frappe.db.savepoint(point)
		try:
			result = _claim(name, force=force)
			if result.get("token"):
				frappe.db.after_commit.add(partial(_publish, name, result["token"]))
			results.append(result)
		except Exception:
			frappe.db.rollback(save_point=point)
			attention = frappe.db.get_value(DT, name, "intake_attention") or ""
			warning = "AI: This context could not be queued; review and prepare this sender again."
			_set(name, dict(intake_ai_state="Needs Attention", intake_ai_prepared_digest=frappe.db.get_value(DT, name, "intake_context_digest"),
				intake_status="Needs Attention", intake_attention=attention if warning in attention else "\n".join(filter(None, (attention, warning))),
				intake_ai_note="This context could not be queued; review and prepare this sender again."))
			frappe.local.message_log = []
			results.append(dict(state="Needs Attention", anchor=name, note="This context could not be queued; review it manually."))
		finally:
			frappe.db.release_savepoint(point)
	return dict(state="Queued" if any(r["state"] == "Queued" for r in results) else "Idle",
		queued=sum(r["state"] == "Queued" for r in results), results=results)


def tick():
	return dispatch()


def process(anchor, token, release_transaction=True):
	"""No locks/DB transaction are held across provider I/O in production workers."""
	row = frappe.db.get_value(DT, anchor, ["intake_ai_state", "intake_ai_token", "intake_ai_digest", "intake_ai_lease_until", "whatsapp_account", "intake_sender_key"], as_dict=True)
	if not row or row.intake_ai_state != "Queued" or row.intake_ai_token != token:
		return dict(state="Stale")
	recorder = None
	try:
		config = frappe.get_single("Order Intake Settings")
		config._intake_api_key = config.get_password("api_key", raise_exception=False)
		recorder = RunRecorder.start(dict(anchor=anchor, whatsapp_account=row.whatsapp_account, sender=row.intake_sender_key),
			config, token, independent=release_transaction and not frappe.flags.in_test)
		if not row.intake_ai_lease_until or get_datetime(row.intake_ai_lease_until) <= now_datetime():
			raise AIProblem("The AI worker lease expired; retained for retry.", True)
		snapshot = _snapshot(anchor)
		recorder.capture_snapshot(snapshot)
		if _digest(snapshot) != row.intake_ai_digest:
			raise AIProblem("Source evidence changed before AI processing; prepare context again.", True)
		budget = RequestBudget(config.max_requests_per_job, recorder=recorder)
		if release_transaction:
			frappe.db.commit()
		from kunal_enterprises.integrations.order_intake_ai_media import build_media
		# Inspection metadata travels separately: mutating the fenced snapshot
		# would make every correctly parsed PDF appear stale at publication.
		media_metadata = {}
		grouping_sources = [message for message in snapshot["messages"] if message["name"] in snapshot["grouping_message_ids"]]
		media, warnings = build_media(grouping_sources, config, deadline=budget.deadline, metadata=media_metadata)
		if release_transaction:
			frappe.db.commit()
		semantic_messages = model_messages(snapshot["messages"])
		payload = dict(messages=[message for message in semantic_messages if message["name"] in snapshot["grouping_message_ids"]], open_requests=snapshot["open_requests"],
			business_context=snapshot["business_context"], confirmed_learning=snapshot["confirmed_learning"])
		if set(snapshot["grouping_message_ids"]) <= set(snapshot.get("context_only_ids") or []):
			from kunal_enterprises.integrations.order_intake_ai_models import Grouping
			grouping = Grouping(groups=[], unresolved_message_ids=[])
		else:
			grouping = group(config, payload, media, budget)
		# Covered-only groups cannot recreate existing orders on later windows.
		# Reuse a single still-open draft, otherwise leave a visible ambiguity.
		known = {m["name"]: frappe.parse_json(m.get("intake_ai_coverage") or "{}") for m in snapshot["messages"]}
		open_ids = {r["name"] for r in snapshot["open_requests"]}
		context_only = set(snapshot.get("context_only_ids") or [])
		grouping.unresolved_message_ids = [name for name in grouping.unresolved_message_ids if name not in context_only]
		kept = []
		for entry in grouping.groups:
			if set(entry.message_ids) <= context_only:
				continue
			if not entry.target_request and all(known[name].get("requests") for name in entry.message_ids):
				prior = set().union(*(set(known[name]["requests"]) for name in entry.message_ids))
				if len(prior) == 1 and prior <= open_ids:
					entry.target_request = next(iter(prior))
				else:
					grouping.unresolved_message_ids.extend(entry.message_ids)
					continue
			kept.append(entry)
		merged = []
		by_target = {}
		target_scopes = {}
		for entry in kept:
			if entry.target_request and entry.target_request in by_target:
				previous = by_target[entry.target_request]
				previous.message_ids = list(dict.fromkeys(previous.message_ids + entry.message_ids))
				scopes = target_scopes[entry.target_request]
				if entry.request_hint not in scopes:
					scopes.append(entry.request_hint)
				# Preserve every scope; the normal input budget rejects oversized
				# combined evidence rather than silently truncating a correction.
				previous.request_hint = "\n".join(scopes)
			else:
				merged.append(entry)
				if entry.target_request:
					by_target[entry.target_request] = entry
					target_scopes[entry.target_request] = [entry.request_hint]
		grouping.groups = merged
		extractions = []
		extracted_groups = []
		for entry in grouping.groups:
			target = next((r for r in snapshot["open_requests"] if r["name"] == entry.target_request), {})
			if target.get('evidence_needs_manual_review'):
				for name in entry.message_ids:
					if name not in context_only:
						grouping.unresolved_message_ids.append(name)
						warnings.setdefault(name, []).append("The related draft has too much historical evidence; review this continuation manually.")
				continue
			# Extract from the targeted request's original evidence as well as the
			# new correction. Historical sources remain context-only at publication.
			entry.message_ids = list(dict.fromkeys(entry.message_ids + target.get('source_messages', [])))
			subset = [m for m in semantic_messages if m["name"] in entry.message_ids]
			missing_media = [message for message in snapshot['messages'] if message['name'] in entry.message_ids and message['name'] not in media]
			if missing_media:
				extra_media, extra_warnings = build_media(missing_media, config, deadline=budget.deadline, metadata=media_metadata)
				media.update(extra_media)
				warnings.update(extra_warnings)
			try:
				value = extract(config, dict(messages=subset, request_scope=entry.request_hint, business_context=snapshot["business_context"],
					confirmed_learning=relevant_examples(snapshot["confirmed_learning"], subset, target.get("customer")),
					open_requests=[r for r in snapshot["open_requests"] if r["name"] == entry.target_request]),
					{k: v for k, v in media.items() if k in entry.message_ids}, budget)
			except InputTooLarge:
				for name in entry.message_ids:
					if name not in context_only:
						grouping.unresolved_message_ids.append(name)
						warnings.setdefault(name, []).append("This request exceeds the configured input token estimate; review it manually or process a smaller related context.")
				continue
			extractions.append(value)
			extracted_groups.append(entry)
		grouping.groups = extracted_groups
		# End the read transaction before reacquiring locks so repeatable-read
		# cannot hide source changes committed during the provider request.
		if release_transaction:
			frappe.db.commit()
		preparation._lock_account(snapshot["whatsapp_account"])
		current = frappe.get_doc(DT, anchor, for_update=True)
		if current.intake_ai_token != token or current.intake_ai_state != "Queued":
			recorder.finish("Stale", note="The claim was replaced; spent calls were not published.")
			return dict(state="Stale")
		if not current.intake_ai_lease_until or get_datetime(current.intake_ai_lease_until) <= now_datetime():
			raise AIProblem("The AI worker lease expired before publishing; retained for retry.", True)
		for source in sorted(snapshot["messages"], key=lambda row: row["name"]):
			frappe.get_doc(DT, source["name"], for_update=True)
			for file in sorted(source.get("file_evidence", []), key=lambda row: row["name"]):
				frappe.get_doc("File", file["name"], for_update=True)
		for request in sorted(snapshot["open_requests"], key=lambda row: row["name"]):
			frappe.get_doc("Order Intake Request", request["name"], for_update=True)
		if _digest(_snapshot(anchor)) != row.intake_ai_digest:
			raise AIProblem("Source evidence or a reviewed draft changed during AI processing; prepare context again.", True)
		point = "ai_apply_" + uuid4().hex[:12]
		frappe.db.savepoint(point)
		try:
			from kunal_enterprises.integrations.order_intake_ai_drafts import publish
			previous = frappe.flags.intake_ai_write
			try:
				frappe.flags.intake_ai_write = True
				result = publish(snapshot, grouping, extractions, warnings, media_metadata=media_metadata)
			finally:
				frappe.flags.intake_ai_write = previous
			_set(anchor, dict(intake_ai_state="Unresolved" if anchor in result["unresolved"] else "Drafted", intake_ai_token=None,
				intake_ai_lease_until=None, intake_ai_retry_at=None, intake_ai_attempts=0,
				intake_ai_result=_json(result), intake_ai_note="Editable drafts and suggestions are ready for review; no Order was created."))
			recorder.finish("Unresolved" if result["unresolved"] else "Drafted", result=result, publication_pending=True)
			return dict(state="Unresolved" if result["unresolved"] else "Drafted", **result)
		except Exception:
			frappe.db.rollback(save_point=point)
			raise
		finally:
			frappe.db.release_savepoint(point)
	except LoggingAlreadyStarted:
		return dict(state="Stale", note="This processing attempt already has a run log.")
	except LoggingFailure:
		note = "AI run logging is unavailable; processing stopped before further provider calls. Original messages are retained."
		_fail(anchor, token, note)
		if recorder:
			try:
				recorder.finish("Needs Attention", note=note)
			except LoggingFailure:
				pass  # The retained started log identifies the incomplete attempt.
		frappe.local.message_log = []
		return dict(state="Needs Attention", note=note)
	except AIProblem as exc:
		_fail(anchor, token, exc.note, exc.retry)
		if recorder:
			try:
				recorder.finish(frappe.db.get_value(DT, anchor, "intake_ai_state") or "Needs Attention", note=exc.note)
			except LoggingFailure:
				_set(anchor, dict(intake_ai_note="AI logging is incomplete; retained started calls need administrator review."))
		return dict(state=frappe.db.get_value(DT, anchor, "intake_ai_state") or "Needs Attention", note=exc.note)
	except Exception:
		# Provider exceptions may embed keys, raw messages or response bodies.
		# Persist a fixed explanation rather than logging the exception itself.
		note = "AI output could not be validated or published; original messages are retained for manual review."
		_fail(anchor, token, note)
		if recorder:
			try:
				recorder.finish("Needs Attention", note=note)
			except LoggingFailure:
				note = "AI logging is incomplete; retained started calls need administrator review."
				_set(anchor, dict(intake_ai_note=note))
		frappe.local.message_log = []
		return dict(state="Needs Attention", note=note)
