"""Durable, bounded context preparation. No model calls or order classification."""
import hashlib
import json
from functools import partial
from uuid import uuid4

import frappe
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from kunal_enterprises.kunal_enterprises.doctype.order_intake_request.order_intake_request import _sender_key

DT = "WhatsApp Message"
SETTINGS = "Order Intake Settings"
MAX_CHATS = 20
MAX_MESSAGES = 100
MAX_REFERENCES = 20
LEASE_MINUTES = 10
READY = "Context Ready"
TERMINAL = "Needs Attention"
BASE = "type='Incoming' AND intake_received_at IS NOT NULL AND COALESCE(intake_status,'') != 'Duplicate'"


def settings():
	# Read only scheduling fields, never the provider key or an entire settings document.
	fields = ("preparation_enabled", "interval_minutes", "lookback_minutes", "deferred_retry_minutes", "preparation_last_tick")
	return frappe._dict({field: frappe.db.get_single_value(SETTINGS, field, cache=False) for field in fields})


def _json(value):
	return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _set(names, values):
	for name in names:
		frappe.db.set_value(DT, name, values, update_modified=False)


def _lock_settings():
	# setup seeds this Single row, giving concurrent ticks one persistent lock.
	return frappe.db.sql("SELECT value FROM `tabSingles` WHERE doctype=%s AND field='preparation_enabled' FOR UPDATE", SETTINGS)


def _lock_account(account):
	if not account or not frappe.db.get_value("WhatsApp Account", account, "name", for_update=True):
		frappe.throw("The receiving WhatsApp account is unavailable")


def _cutoff(config, now):
	return add_to_date(now, minutes=-cint(config.lookback_minutes or 120), as_datetime=True)


def _due(row, now):
	state = row.intake_prepare_state
	return not state or state == "Pending" or (state == "Retry" and (not row.intake_retry_at or get_datetime(row.intake_retry_at) <= now))


def _chat_rows(account, sender, now, config):
	return frappe.db.sql(f"""SELECT name, intake_prepare_state, intake_retry_at, intake_job_token,
		intake_lease_until, intake_attempts, intake_received_at FROM `tabWhatsApp Message`
		WHERE {BASE} AND whatsapp_account=%s AND intake_sender_key=%s AND intake_received_at >= %s
		ORDER BY intake_received_at, name LIMIT %s""", (account, sender, _cutoff(config, now), MAX_MESSAGES + 1), as_dict=True)


def _fail(token, reason, now=None):
	"""A token fences a failed/late worker from a newer batch. Reasons are fixed text."""
	now = get_datetime(now or now_datetime())
	first = frappe.db.get_value(DT, {"intake_job_token": token, "intake_prepare_state": "Queued"}, ["name", "whatsapp_account"], as_dict=True)
	if not first:
		return
	# Match the worker lock order, then re-read the fenced claim before writes.
	if first.whatsapp_account and frappe.db.exists("WhatsApp Account", first.whatsapp_account):
		_lock_account(first.whatsapp_account)
	rows = frappe.db.sql("SELECT name, intake_attempts FROM `tabWhatsApp Message` WHERE intake_job_token=%s AND intake_prepare_state='Queued' LIMIT %s FOR UPDATE", (token, MAX_MESSAGES), as_dict=True)
	if not rows:
		return
	delays = [int(value) for value in (settings().deferred_retry_minutes or "5,15,60").split(",")]
	attempt = max(cint(row.intake_attempts) for row in rows)
	exhausted = attempt > len(delays)
	values = dict(intake_prepare_state=TERMINAL if exhausted else "Retry", intake_job_token=None,
		intake_lease_until=None, intake_retry_at=None if exhausted else add_to_date(now, minutes=delays[max(attempt - 1, 0)], as_datetime=True),
		intake_prepare_note=("Preparation retries exhausted. " if exhausted else "") + reason)
	if exhausted:
		values["intake_status"] = TERMINAL
	_set([row.name for row in rows], values)


def _publish(token):
	"""Runs only after the claiming transaction commits; publication has its own retry path."""
	try:
		frappe.enqueue("kunal_enterprises.integrations.order_intake_queue.prepare_context", queue="short",
			job_id="order-intake-" + token, timeout=120, token=token)
	except Exception:
		_fail(token, "The background queue is unavailable; the messages are retained for retry.")
		# This is a post-commit callback. Persist only this callback's retry updates.
		frappe.db.commit()


def _expire_and_recover(now, config, account=None, sender=None):
	scope = ""
	args = []
	if account:
		scope += " AND whatsapp_account=%s"
		args.append(account)
	if sender:
		scope += " AND intake_sender_key=%s"
		args.append(sender)
	stale = frappe.db.sql(f"""SELECT DISTINCT intake_job_token FROM `tabWhatsApp Message`
		WHERE {BASE} AND intake_prepare_state='Queued' AND intake_lease_until <= %s {scope} LIMIT %s""", (now, *args, MAX_CHATS), as_dict=True)
	for row in stale:
		if row.intake_job_token:
			_fail(row.intake_job_token, "The preparation worker did not finish before its lease expired.", now)
	old = frappe.db.sql(f"""SELECT name FROM `tabWhatsApp Message` WHERE {BASE}
		AND intake_received_at < %s AND COALESCE(intake_prepare_state,'') NOT IN ('Queued','Needs Attention')
		AND NOT (intake_prepare_state='Context Ready' AND COALESCE(intake_manual_context,0)=1)
		{scope} ORDER BY intake_received_at, name LIMIT %s""", (_cutoff(config, now), *args, MAX_MESSAGES), as_dict=True)
	_set([row.name for row in old], dict(intake_prepare_state=TERMINAL, intake_status=TERMINAL,
		intake_prepare_note="Outside the automatic context window; retained for manual review.", intake_retry_at=None))


def candidate_chats(now, config, account=None, sender=None):
	where, values = [BASE, "intake_received_at >= %s", "(COALESCE(intake_prepare_state,'') IN ('','Pending') OR (intake_prepare_state='Retry' AND (intake_retry_at IS NULL OR intake_retry_at <= %s)))"], [_cutoff(config, now), now]
	if account:
		where.append("whatsapp_account=%s")
		values.append(account)
	if sender:
		where.append("intake_sender_key=%s")
		values.append(_sender_key(sender))
	where.append("NOT EXISTS (SELECT 1 FROM `tabWhatsApp Message` busy WHERE busy.type='Incoming' AND busy.whatsapp_account <=> `tabWhatsApp Message`.whatsapp_account AND busy.intake_sender_key <=> `tabWhatsApp Message`.intake_sender_key AND (busy.intake_prepare_state='Queued' OR (busy.intake_prepare_state='Retry' AND busy.intake_retry_at > %s)))")
	values.append(now)
	return frappe.db.sql("SELECT whatsapp_account, intake_sender_key, MIN(intake_received_at) AS oldest FROM `tabWhatsApp Message` WHERE " + " AND ".join(where)
		+ " GROUP BY whatsapp_account, intake_sender_key ORDER BY oldest LIMIT %s", (*values, MAX_CHATS), as_dict=True)


def _claim(account, sender, now, config, check_permissions=False):
	if not account or not frappe.db.exists("WhatsApp Account", account):
		rows = frappe.db.sql(f"SELECT name FROM `tabWhatsApp Message` WHERE {BASE} AND COALESCE(whatsapp_account,'')=%s AND COALESCE(intake_prepare_state,'') != 'Needs Attention' LIMIT %s FOR UPDATE", (account or "", MAX_MESSAGES), as_dict=True)
		_set([row.name for row in rows], dict(intake_prepare_state=TERMINAL, intake_status=TERMINAL,
			intake_prepare_note="The receiving account is missing; review the original message and account mapping."))
		return None
	_lock_account(account)
	if not sender:
		rows = frappe.db.sql(f"SELECT name FROM `tabWhatsApp Message` WHERE {BASE} AND whatsapp_account=%s AND COALESCE(intake_sender_key,'')='' AND COALESCE(intake_prepare_state,'') != 'Needs Attention' LIMIT %s FOR UPDATE", (account, MAX_MESSAGES), as_dict=True)
		_set([row.name for row in rows], dict(intake_prepare_state=TERMINAL, intake_status=TERMINAL,
			intake_prepare_note="The message has no sender identity; review it manually."))
		return None
	# A new message must wait for a live job for this chat, even if that older
	# batch has aged past the context window since it was queued.
	active = frappe.db.sql(f"SELECT name FROM `tabWhatsApp Message` WHERE {BASE} AND whatsapp_account=%s AND intake_sender_key=%s AND intake_prepare_state='Queued' LIMIT 1 FOR UPDATE", (account, sender))
	if active:
		return None
	rows = _chat_rows(account, sender, now, config)
	if check_permissions:
		for row in rows:
			doc = frappe.get_doc(DT, row.name)
			doc.check_permission("read")
			doc.check_permission("write")
	# Never truncate a busy chat into an apparently complete context.
	if len(rows) > MAX_MESSAGES:
		# Keep overflow chats manual, but advance through bounded unflagged rows
		# so later messages do not hide behind the first already-flagged page.
		remaining = frappe.db.sql(f"SELECT name FROM `tabWhatsApp Message` WHERE {BASE} AND whatsapp_account=%s AND intake_sender_key=%s AND intake_received_at >= %s AND COALESCE(intake_prepare_state,'') != 'Needs Attention' ORDER BY intake_received_at, name LIMIT %s FOR UPDATE", (account, sender, _cutoff(config, now), MAX_MESSAGES), as_dict=True)
		_set([row.name for row in remaining], dict(intake_prepare_state=TERMINAL, intake_status=TERMINAL,
			intake_prepare_note="This chat exceeds the automatic message limit; review the complete sender history."))
		return None
	if not any(_due(row, now) for row in rows):
		return None
	# Retry delays apply to the chat, so a new message cannot bypass its backoff.
	if any(row.intake_prepare_state == "Retry" and row.intake_retry_at and get_datetime(row.intake_retry_at) > now for row in rows):
		return None
	eligible = [row for row in rows if row.intake_prepare_state != TERMINAL]
	if not eligible:
		return None
	token = uuid4().hex
	for row in eligible:
		_set([row.name], dict(intake_prepare_state="Queued", intake_job_token=token,
			intake_attempts=cint(row.intake_attempts) + 1, intake_batch_size=len(eligible), intake_manual_context=0, intake_lease_until=add_to_date(now, minutes=LEASE_MINUTES, as_datetime=True),
			intake_retry_at=None, intake_context_anchor=None, intake_context_ids=None, intake_context_digest=None,
			intake_prepared_at=None, intake_prepare_note=""))
	return token


def dispatch_pending(force=False, account=None, sender=None, inline=False, now=None, maintain=True, check_permissions=False):
	"""Internal coordinator. Manual callers are authorized by the API wrapper."""
	now = get_datetime(now or now_datetime())
	_lock_settings()
	config = settings()
	if not force:
		if not cint(config.preparation_enabled):
			return dict(state="Disabled", queued=0)
		if config.preparation_last_tick and get_datetime(config.preparation_last_tick) > add_to_date(now, minutes=-cint(config.interval_minutes or 5), as_datetime=True):
			return dict(state="Not Due", queued=0)
		frappe.db.set_single_value(SETTINGS, "preparation_last_tick", now)
	if maintain:
		_expire_and_recover(now, config, account, sender)
	queued, failed, ready, retrying, stale = [], 0, 0, 0, 0
	for chat in candidate_chats(now, config, account, sender):
		point = "intake_chat_" + uuid4().hex[:12]
		frappe.db.savepoint(point)
		try:
			token = _claim(chat.whatsapp_account, chat.intake_sender_key, now, config, check_permissions)
			if token:
				if inline:
					result = prepare_context(token, now=now)
					ready += int(result["state"] == READY)
					retrying += int(result["state"] == "Retry")
					stale += int(result["state"] == "Stale")
				else:
					frappe.db.after_commit.add(partial(_publish, token))
				queued.append(token)
		except Exception:
			frappe.db.rollback(save_point=point)
			failed += 1
			frappe.local.message_log = []
		finally:
			frappe.db.release_savepoint(point)
	state = (READY if ready else "Retry" if retrying else "Idle") if inline else "Queued"
	return dict(state=state, queued=len(queued), tokens=queued, failed_chats=failed,
		ready=ready, retrying=retrying, stale=stale)



def recover_selected(account, sender, names, now=None):
	"""Explicit manual recovery can include old evidence without changing receipt time."""
	now = get_datetime(now or now_datetime())
	_lock_settings()
	_lock_account(account)
	# Live work always wins. Expired batches may only be replaced in their
	# entirety so a late worker cannot operate on a half-reset context.
	queued = frappe.db.sql(f"""SELECT name, intake_job_token, intake_lease_until FROM `tabWhatsApp Message`
		WHERE type='Incoming' AND whatsapp_account=%s AND intake_sender_key=%s
		AND intake_prepare_state='Queued' ORDER BY name LIMIT %s FOR UPDATE""",
		(account, sender, MAX_MESSAGES + 1), as_dict=True)
	if len(queued) > MAX_MESSAGES:
		frappe.throw("This sender has too many queued messages; wait for recovery before retrying")
	if any(not row.intake_lease_until or get_datetime(row.intake_lease_until) > now for row in queued):
		frappe.throw("This sender already has a live preparation job; wait for it to finish")
	if queued and not {row.name for row in queued}.issubset(set(names)):
		frappe.throw("Select every message in the expired preparation batch before retrying it")
	docs = [frappe.get_doc(DT, name, for_update=True) for name in names]
	for doc in docs:
		doc.check_permission("read")
		doc.check_permission("write")
		if doc.type != "Incoming" or doc.whatsapp_account != account or doc.intake_sender_key != sender:
			frappe.throw("Select incoming messages from the chosen account and sender only")
		if not doc.intake_received_at or doc.intake_status == "Duplicate":
			frappe.throw("Select captured canonical messages; duplicates and unprepared records cannot be retried")
	docs.sort(key=lambda doc: (get_datetime(doc.intake_received_at), doc.name))
	# Ready messages can belong to different batches, or be only a subset of
	# one. Reuse work only when this exact selection is already persisted.
	anchor_name = docs[0].intake_context_anchor
	if all(doc.intake_prepare_state == READY and doc.intake_context_anchor == anchor_name for doc in docs):
		anchor = next((doc for doc in docs if doc.name == anchor_name), None)
		try:
			stored = json.loads(anchor.intake_context_ids or "{}") if anchor else {}
		except (ValueError, TypeError):
			stored = {}
		if isinstance(stored, dict) and stored.get("message_ids") == [doc.name for doc in docs]:
			current = build_context(docs, now=now)
			evidence = [[doc.name, doc.message, doc.attach, doc.reply_to_message_id,
				doc.intake_raw_payload, doc.intake_legacy_evidence] for doc in docs]
			digest = hashlib.sha256(_json([current, evidence]).encode()).hexdigest()
			if stored == current and all(doc.intake_context_digest == digest for doc in docs):
				_set([doc.name for doc in docs], {"intake_manual_context": 1})
				return dict(state=READY, ready=0, retrying=0, stale=0, failed_chats=0,
					context=stored, note="These messages already have a prepared context; no duplicate work was created.")
	token = uuid4().hex
	names = [doc.name for doc in docs]
	_set(names, dict(intake_prepare_state="Queued", intake_job_token=token, intake_attempts=1,
		intake_batch_size=len(names), intake_manual_context=1,
		intake_lease_until=add_to_date(now, minutes=LEASE_MINUTES, as_datetime=True), intake_retry_at=None,
		intake_context_anchor=None, intake_context_ids=None, intake_context_digest=None, intake_prepared_at=None,
		intake_prepare_note="Manual retry requested for these selected messages."))
	result = prepare_context(token, now=now)
	return {**result, "ready": int(result["state"] == READY), "retrying": int(result["state"] == "Retry"),
		"stale": int(result["state"] == "Stale"), "failed_chats": 0}

def tick():
	return dispatch_pending()


def _open_requests(account, sender, source_ids):
	# Include only requests with an explicit matching message association. A
	# customer/name/time guess alone must not pull another sender's request.
	placeholders = ",".join(["%s"] * len(source_ids))
	rows = frappe.db.sql(f"""SELECT DISTINCT r.name, r.status, r.request_type FROM `tabOrder Intake Request` r
		JOIN `tabOrder Intake Source Message` s ON s.parent=r.name AND s.parenttype='Order Intake Request'
		WHERE r.whatsapp_account=%s AND s.message IN ({placeholders})
		AND r.status IN ('Pending Review','In Review','Awaiting Confirmation') ORDER BY r.name LIMIT %s""",
		(account, *source_ids, MAX_REFERENCES + 1), as_dict=True)
	# Parent validation normally enforces one chat; verify every source again
	# in case an external import bypassed validation.
	valid = []
	for row in rows[:MAX_REFERENCES]:
		refs = frappe.get_all("Order Intake Source Message", filters={"parent": row.name, "parenttype": "Order Intake Request"}, pluck="message", limit_page_length=MAX_MESSAGES + 1)
		if not refs or len(refs) > MAX_MESSAGES:
			continue
		# Historical sources may not have intake metadata yet. Validate their
		# original sender without silently importing them into the job queue.
		sources = frappe.get_all(DT, filters={"name": ("in", refs)}, fields=["whatsapp_account", "intake_sender_key", "from", "type"], limit_page_length=MAX_MESSAGES)
		if len(sources) == len(refs) and all(m.type == "Incoming" and m.whatsapp_account == account
			and _sender_key(m.get("from")) == sender
			and (not m.intake_sender_key or m.intake_sender_key == sender) for m in sources):
			valid.append(dict(row))
	return valid, len(rows) > MAX_REFERENCES


def build_context(rows, now=None):
	now = get_datetime(now or now_datetime())
	account, sender = rows[0].whatsapp_account, rows[0].intake_sender_key
	if not account or not sender or any(row.type != "Incoming" or row.whatsapp_account != account or row.intake_sender_key != sender for row in rows):
		frappe.throw("Context must contain one incoming sender and receiving account")
	names = [row.name for row in rows]
	replies, warnings = [], []
	for row in rows:
		if not row.reply_to_message_id:
			continue
		refs = frappe.get_all(DT, filters={"type": "Incoming", "whatsapp_account": account,
			"intake_sender_key": sender, "message_id": row.reply_to_message_id, "intake_status": ("!=", "Duplicate")},
			fields=["name"], limit_page_length=2)
		if len(refs) == 1 and refs[0].name not in names and refs[0].name not in replies and len(replies) < MAX_REFERENCES:
			replies.append(refs[0].name)
		elif len(refs) != 1 or len(replies) >= MAX_REFERENCES:
			warnings.append("Some reply references need manual review or exceed the context limit.")
	manual = frappe.db.sql(f"""SELECT name FROM `tabWhatsApp Message` WHERE {BASE}
		AND whatsapp_account=%s AND intake_sender_key=%s AND intake_prepare_state='Needs Attention'
		AND intake_received_at >= %s ORDER BY intake_received_at, name LIMIT %s""",
		(account, sender, _cutoff(settings(), now), MAX_REFERENCES + 1), as_dict=True)
	manual_ids = [row.name for row in manual[:MAX_REFERENCES] if row.name not in names]
	if len(manual) > MAX_REFERENCES:
		warnings.append("Additional unresolved manual-review messages exceed the context limit; review the sender history.")
	requests, truncated = _open_requests(account, sender, names + manual_ids)
	if truncated:
		warnings.append("Additional related requests exceed the context limit; review the sender history.")
	return dict(whatsapp_account=account, sender=sender, message_ids=names, reply_message_ids=replies,
		manual_review_message_ids=manual_ids, open_requests=requests, warnings=sorted(set(warnings)))


def prepare_context(token, now=None):
	"""A stale queue delivery cannot release or overwrite another job's claim."""
	now = get_datetime(now or now_datetime())
	rows = frappe.get_all(DT, filters={"intake_job_token": token, "intake_prepare_state": "Queued"},
		fields=["name", "whatsapp_account"], order_by="intake_received_at asc, name asc", limit_page_length=MAX_MESSAGES + 1)
	if not rows:
		return dict(state="Stale")
	point = "intake_worker_" + uuid4().hex[:12]
	frappe.db.savepoint(point)
	try:
		_lock_account(rows[0].whatsapp_account)
		names = [row.name for row in rows]
		locked = [frappe.get_doc(DT, row.name, for_update=True) for row in rows]
		if len(locked) > MAX_MESSAGES or any(row.intake_job_token != token or row.intake_prepare_state != "Queued" for row in locked):
			return dict(state="Stale")
		if any(cint(row.intake_batch_size) != len(locked) for row in locked):
			frappe.throw("A claimed source message was removed; review the remaining source evidence")
		if any(not row.intake_lease_until or get_datetime(row.intake_lease_until) <= now for row in locked):
			_fail(token, "The preparation lease expired before this worker started.", now)
			return dict(state="Retry")
		context = build_context(locked, now=now)
		# A changed attachment/body/raw event must not reuse the digest of an
		# earlier context with the same source IDs.
		evidence = [[row.name, row.message, row.attach, row.reply_to_message_id,
			row.intake_raw_payload, row.intake_legacy_evidence] for row in locked]
		digest = hashlib.sha256(_json([context, evidence]).encode()).hexdigest()
		anchor = names[0]
		_set(names, dict(intake_prepare_state=READY, intake_job_token=None, intake_lease_until=None,
			intake_retry_at=None, intake_attempts=0, intake_context_anchor=anchor, intake_context_digest=digest,
			intake_prepared_at=now, intake_prepare_note="Context prepared; AI grouping and extraction are not enabled."))
		_set([anchor], {"intake_context_ids": _json(context)})
		return dict(state=READY, anchor=anchor, context=context)
	except Exception:
		frappe.db.rollback(save_point=point)
		_fail(token, "Context preparation failed; original messages are retained for retry.", now)
		frappe.local.message_log = []
		return dict(state="Retry")
	finally:
		frappe.db.release_savepoint(point)


def invalidate_changed_message(doc, method=None):
	"""Late attachments/text corrections are new input, not unchanged ready context."""
	if doc.type != "Incoming" or doc.get("intake_prepare_state") != READY or doc.is_new():
		return
	if any(doc.has_value_changed(field) for field in ("message", "attach", "reply_to_message_id", "from", "whatsapp_account")):
		doc.intake_prepare_state = "Pending"
