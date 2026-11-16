"""Step 3 prepares bounded context without model calls, orders or silent message loss."""
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, get_datetime, now_datetime
from kunal_enterprises.api import order_intake_queue as api
from kunal_enterprises.integrations import order_intake_queue as queue
from kunal_enterprises.tests import test_foundation as foundation


class TestOrderIntakeQueue(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.now = now_datetime()
		self.sender = "919000000049"
		self.account = self.account_doc()
		for field, value in {"preparation_enabled": 0, "preparation_last_tick": None, "interval_minutes": 5,
			"lookback_minutes": 120, "deferred_retry_minutes": "5,15,60"}.items():
			frappe.db.set_single_value("Order Intake Settings", field, value)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def account_doc(self):
		return frappe.get_doc({"doctype": "WhatsApp Account", "account_name": "Queue test " + uuid4().hex,
			"phone_id": uuid4().hex, "status": "Active"}).insert(ignore_permissions=True)

	def source(self, minutes=-1, sender=None, account=None, **values):
		doc = frappe.get_doc({"doctype": "WhatsApp Message", "type": "Incoming", "whatsapp_account": account or self.account.name,
			"from": sender or self.sender, "message": "Two sheets", "message_id": uuid4().hex, "content_type": "text", **values}).insert(ignore_permissions=True)
		frappe.db.set_value("WhatsApp Message", doc.name, "intake_received_at", add_to_date(self.now, minutes=minutes, as_datetime=True))
		return doc.reload()

	def dispatch(self, **kwargs):
		return queue.dispatch_pending(force=True, account=self.account.name, sender=self.sender, now=self.now, **kwargs)

	def claim(self):
		return queue._claim(self.account.name, self.sender, self.now, queue.settings())

	def test_disabled_tick_changes_nothing(self):
		doc = self.source()
		self.assertEqual(queue.tick()["state"], "Disabled")
		self.assertEqual(doc.reload().intake_prepare_state, "Pending")

	def test_cadence_is_persisted_and_does_not_duplicate_dispatch(self):
		self.source()
		frappe.db.set_single_value("Order Intake Settings", "preparation_enabled", 1)
		first = queue.dispatch_pending(account=self.account.name, sender=self.sender, now=self.now)
		second = queue.dispatch_pending(account=self.account.name, sender=self.sender, now=self.now)
		self.assertEqual(first["queued"], 1)
		self.assertEqual(second["state"], "Not Due")

	def test_context_is_chronological_and_not_processed_or_an_order(self):
		before = frappe.db.count("Order Intake Request")
		first, second = self.source(minutes=-5), self.source(minutes=-1)
		result = self.dispatch(inline=True)
		self.assertEqual(result["queued"], 1)
		first.reload(); second.reload()
		self.assertEqual(first.intake_prepare_state, "Context Ready")
		self.assertEqual(first.intake_status, "New")
		self.assertEqual(frappe.parse_json(first.intake_context_ids)["message_ids"], [first.name, second.name])
		self.assertEqual(frappe.db.count("Order Intake Request"), before)

	def test_unchanged_context_is_not_dispatched_again_but_new_input_includes_it(self):
		first = self.source(minutes=-2)
		self.dispatch(inline=True)
		self.assertEqual(self.dispatch(inline=True)["queued"], 0)
		second = self.source()
		self.assertEqual(self.dispatch(inline=True)["queued"], 1)
		first.reload()
		self.assertEqual(frappe.parse_json(first.intake_context_ids)["message_ids"], [first.name, second.name])

	def test_new_arrival_waits_for_queued_chat(self):
		first = self.source(minutes=-2)
		token = self.claim()
		second = self.source()
		self.assertEqual(self.dispatch()["queued"], 0)
		queue.prepare_context(token, now=self.now)
		self.assertEqual(self.dispatch(inline=True)["queued"], 1)
		self.assertEqual(second.reload().intake_prepare_state, "Context Ready")

	def test_expired_unresolved_message_stays_visible_and_newly_received_late_message_is_eligible(self):
		old = self.source(minutes=-121)
		late = self.source()
		frappe.db.set_value("WhatsApp Message", late.name, "intake_sent_at", "2000-01-01 00:00:00")
		self.dispatch(inline=True)
		self.assertEqual(old.reload().intake_prepare_state, "Needs Attention")
		self.assertTrue(frappe.db.exists("WhatsApp Message", old.name))
		self.assertEqual(late.reload().intake_prepare_state, "Context Ready")

	def test_unknown_sender_is_preserved_but_missing_sender_needs_attention(self):
		doc = self.source()
		self.assertEqual(doc.intake_identity_type, "Unknown")
		self.dispatch(inline=True)
		self.assertEqual(doc.reload().intake_prepare_state, "Context Ready")
		missing = self.source(sender="919000000099")
		frappe.db.set_value("WhatsApp Message", missing.name, "intake_sender_key", "")
		queue.dispatch_pending(force=True, account=self.account.name, now=self.now, inline=True)
		self.assertEqual(missing.reload().intake_prepare_state, "Needs Attention")

	def test_unprepared_and_duplicate_messages_are_not_selected(self):
		a, b = self.source(), self.source()
		frappe.db.set_value("WhatsApp Message", a.name, "intake_received_at", None)
		frappe.db.set_value("WhatsApp Message", b.name, "intake_status", "Duplicate")
		self.assertEqual(self.dispatch(inline=True)["queued"], 0)

	def test_publish_failure_records_backoff_without_exposing_exception(self):
		doc = self.source(); token = self.claim()
		with patch.object(frappe, "enqueue", side_effect=RuntimeError("secret-provider-key")), patch.object(frappe.db, "commit"):
			queue._publish(token)
		doc.reload()
		self.assertEqual(doc.intake_prepare_state, "Retry")
		self.assertGreater(get_datetime(doc.intake_retry_at), self.now)
		self.assertNotIn("secret", doc.intake_prepare_note)
		self.assertEqual(self.dispatch()["queued"], 0)

	def test_stale_lease_recovers_and_old_worker_cannot_overwrite_new_claim(self):
		doc = self.source(); old = self.claim()
		frappe.db.set_value("WhatsApp Message", doc.name, "intake_lease_until", add_to_date(self.now, minutes=-1, as_datetime=True))
		queue._expire_and_recover(self.now, queue.settings(), self.account.name, self.sender)
		self.assertEqual(doc.reload().intake_prepare_state, "Retry")
		frappe.db.set_value("WhatsApp Message", doc.name, "intake_retry_at", self.now)
		new = self.claim()
		self.assertNotEqual(old, new)
		self.assertEqual(queue.prepare_context(old, now=self.now)["state"], "Stale")
		queue._fail(old, "Old worker", self.now)
		self.assertEqual(doc.reload().intake_job_token, new)

	def test_retries_are_bounded_then_require_manual_attention(self):
		doc = self.source()
		for attempt, delay in enumerate((5, 15, 60, None), start=1):
			token = self.claim()
			self.assertTrue(token)
			queue._fail(token, "Safe failure", self.now)
			doc.reload()
			self.assertEqual(doc.intake_attempts, attempt)
			if delay:
				self.assertEqual(get_datetime(doc.intake_retry_at), add_to_date(self.now, minutes=delay, as_datetime=True))
				frappe.db.set_value("WhatsApp Message", doc.name, "intake_retry_at", self.now)
			else:
				self.assertEqual(doc.intake_prepare_state, "Needs Attention")
				self.assertEqual(doc.intake_status, "Needs Attention")

	def test_overflow_progressively_flags_tail_without_partial_context(self):
		with patch.object(queue, "MAX_MESSAGES", 2):
			docs = [self.source(minutes=-i-1) for i in range(5)]
			for _ in range(3):
				self.assertEqual(self.dispatch(inline=True)["queued"], 0)
			self.assertTrue(all(doc.reload().intake_prepare_state == "Needs Attention" for doc in docs))

	def test_replies_and_open_requests_never_cross_account_or_sender(self):
		original = self.source(minutes=-180)
		other_account = self.account_doc()
		self.source(account=other_account.name, message_id=original.message_id)
		self.source(sender="919000000059", message_id=original.message_id)
		current = self.source(reply_to_message_id=original.message_id)
		request = frappe.get_doc({"doctype": "Order Intake Request", "request_type": "Unclear", "status": "Pending Review",
			"source_messages": [{"message": current.name}]}).insert(ignore_permissions=True)
		context = queue.build_context([current])
		self.assertEqual(context["reply_message_ids"], [original.name])
		self.assertEqual([row["name"] for row in context["open_requests"]], [request.name])

	def test_missing_claimed_source_retries_remaining_batch(self):
		first, second = self.source(minutes=-2), self.source()
		token = self.claim()
		frappe.db.delete("WhatsApp Message", {"name": second.name})
		self.assertEqual(queue.prepare_context(token, now=self.now)["state"], "Retry")
		self.assertEqual(first.reload().intake_prepare_state, "Retry")

	def test_worker_failure_does_not_prevent_another_chat(self):
		bad, good = self.source(), self.source(sender="919000000059")
		original = queue.build_context
		def build(rows, **kwargs):
			if rows[0].intake_sender_key == self.sender:
				raise ValueError("sensitive body")
			return original(rows, **kwargs)
		with patch.object(queue, "build_context", side_effect=build):
			queue.dispatch_pending(force=True, account=self.account.name, now=self.now, inline=True)
		self.assertEqual(bad.reload().intake_prepare_state, "Retry")
		self.assertEqual(good.reload().intake_prepare_state, "Context Ready")

	def test_preview_is_read_only_and_manual_preparation_does_not_expire_other_history(self):
		old = self.source(minutes=-180)
		current = self.source()
		result = api.preview(self.account.name, self.sender)
		self.assertEqual(result["state"], "Preview")
		self.assertEqual(current.reload().intake_prepare_state, "Pending")
		api.prepare_now(self.account.name, self.sender)
		self.assertEqual(old.reload().intake_prepare_state, "Pending")
		self.assertEqual(current.reload().intake_prepare_state, "Context Ready")

	def test_coordinator_cannot_prepare_or_preview_settings_job(self):
		user = foundation.TestOrderSubmission._create_role_user(self, "queue-" + uuid4().hex + "@example.com", "Order Coordinator")
		frappe.set_user(user.name)
		with self.assertRaises(frappe.PermissionError):
			api.preview(self.account.name, self.sender)

	def test_new_continuation_includes_recent_manual_review_evidence_without_resetting_it(self):
		old = self.source(minutes=-10)
		frappe.db.set_value("WhatsApp Message", old.name, {"intake_prepare_state": "Needs Attention", "intake_status": "Needs Attention"})
		new = self.source()
		self.dispatch(inline=True)
		new.reload()
		context = frappe.parse_json(new.intake_context_ids)
		self.assertEqual(context["manual_review_message_ids"], [old.name])
		self.assertEqual(old.reload().intake_prepare_state, "Needs Attention")

	def test_mobile_approval_and_disabled_master_status_do_not_block_whatsapp_context(self):
		customer = foundation.TestOrderSubmission._create_active_customer(self, self.sender, "Queue " + uuid4().hex)
		frappe.db.set_value("Customer", customer.name, {"status": "Disabled", "admin_approved": 0, "mobile_verified": 0})
		doc = self.source()
		self.assertEqual(doc.intake_customer, customer.name)
		self.assertEqual(doc.intake_identity_status, "Disabled")
		self.dispatch(inline=True)
		self.assertEqual(doc.reload().intake_prepare_state, "Context Ready")

	def test_changed_source_is_reprepared_with_a_new_context_digest(self):
		doc = self.source()
		self.dispatch(inline=True)
		doc.reload()
		old_digest = doc.intake_context_digest
		doc.attach = "/private/files/late-order-attachment.pdf"
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.intake_prepare_state, "Pending")
		self.dispatch(inline=True)
		self.assertNotEqual(doc.reload().intake_context_digest, old_digest)

	def test_manual_recovery_prepares_old_terminal_evidence_without_changing_timestamps(self):
		doc = self.source(minutes=-180)
		frappe.db.set_value("WhatsApp Message", doc.name, {"intake_prepare_state": "Needs Attention", "intake_status": "Needs Attention",
			"intake_sent_at": "2000-01-01 00:00:00"})
		doc.reload()
		received, sent = doc.intake_received_at, doc.intake_sent_at
		result = api.retry_selected(self.account.name, "+91 90000 00049", [doc.name])
		self.assertEqual(result["state"], "Context Ready")
		doc.reload()
		self.assertEqual(doc.intake_received_at, received)
		self.assertEqual(doc.intake_sent_at, sent)
		self.assertTrue(doc.intake_manual_context)
		queue._expire_and_recover(add_to_date(self.now, minutes=10, as_datetime=True), queue.settings(), self.account.name, self.sender)
		self.assertEqual(doc.reload().intake_prepare_state, "Context Ready")

	def test_manual_recovery_refuses_live_work_for_the_sender(self):
		queued = self.source(minutes=-2)
		token = self.claim()
		other = self.source()
		frappe.db.set_value("WhatsApp Message", other.name, "intake_prepare_state", "Needs Attention")
		with self.assertRaises(frappe.ValidationError):
			api.retry_selected(self.account.name, self.sender, [other.name])
		self.assertEqual(queued.reload().intake_job_token, token)
		self.assertEqual(other.reload().intake_prepare_state, "Needs Attention")

	def test_manual_recovery_requires_all_expired_batch_messages_and_fences_late_worker(self):
		first, second = self.source(minutes=-2), self.source()
		old = self.claim()
		for doc in (first, second):
			frappe.db.set_value("WhatsApp Message", doc.name, "intake_lease_until", add_to_date(self.now, minutes=-1, as_datetime=True))
		with self.assertRaises(frappe.ValidationError):
			api.retry_selected(self.account.name, self.sender, [first.name])
		self.assertEqual(first.reload().intake_job_token, old)
		result = api.retry_selected(self.account.name, self.sender, [second.name, first.name])
		self.assertEqual(result["state"], "Context Ready")
		self.assertEqual(queue.prepare_context(old, now=self.now)["state"], "Stale")

	def test_manual_recovery_requires_explicit_bounded_same_chat_selection(self):
		doc = self.source()
		other = self.source(sender="919000000059")
		for messages in ([], [doc.name, doc.name], [doc.name] * 101):
			with self.assertRaises(frappe.ValidationError):
				api.retry_selected(self.account.name, self.sender, messages)
		with self.assertRaises(frappe.ValidationError):
			api.retry_selected(self.account.name, self.sender, [other.name])
		self.assertEqual(other.reload().intake_prepare_state, "Pending")

	def test_manual_recovery_does_not_repeat_already_ready_work(self):
		doc = self.source()
		result = api.retry_selected(self.account.name, self.sender, [doc.name])
		self.assertEqual(result["ready"], 1)
		prepared_at = doc.reload().intake_prepared_at
		result = api.retry_selected(self.account.name, self.sender, [doc.name])
		self.assertEqual(result["ready"], 0)
		self.assertEqual(doc.reload().intake_prepared_at, prepared_at)

	def test_coordinator_cannot_manually_recover_preparation(self):
		doc = self.source()
		user = foundation.TestOrderSubmission._create_role_user(self, "queue-retry-" + uuid4().hex + "@example.com", "Order Coordinator")
		frappe.set_user(user.name)
		with self.assertRaises(frappe.PermissionError):
			api.retry_selected(self.account.name, self.sender, [doc.name])

	def test_recovery_combines_separate_ready_batches_into_one_persisted_context(self):
		first, second = self.source(minutes=-3), self.source(minutes=-1)
		api.retry_selected(self.account.name, self.sender, [first.name])
		api.retry_selected(self.account.name, self.sender, [second.name])
		self.assertNotEqual(first.reload().intake_context_anchor, second.reload().intake_context_anchor)
		result = api.retry_selected(self.account.name, self.sender, [second.name, first.name])
		self.assertEqual(result["ready"], 1)
		first.reload(); second.reload()
		self.assertEqual(first.intake_context_anchor, second.intake_context_anchor)
		self.assertEqual(frappe.parse_json(first.intake_context_ids)["message_ids"], [first.name, second.name])
		prepared_at = first.intake_prepared_at
		result = api.retry_selected(self.account.name, self.sender, [first.name, second.name])
		self.assertEqual(result["ready"], 0)
		self.assertEqual(first.reload().intake_prepared_at, prepared_at)

	def test_recovery_subset_of_ready_batch_persists_the_requested_selection(self):
		first, second = self.source(minutes=-3), self.source(minutes=-1)
		api.retry_selected(self.account.name, self.sender, [first.name, second.name])
		result = api.retry_selected(self.account.name, self.sender, [second.name])
		self.assertEqual(result["ready"], 1)
		second.reload()
		self.assertEqual(second.intake_context_anchor, second.name)
		self.assertEqual(frappe.parse_json(second.intake_context_ids)["message_ids"], [second.name])

	def linked_request(self, source, status='Pending Review'):
		doc = frappe.get_doc(dict(doctype='Order Intake Request',whatsapp_account=self.account.name,
			sender_number=self.sender,source_messages=[dict(message=source.name)])).insert()
		if status!='Pending Review':
			frappe.db.set_value('Order Intake Request',doc.name,'status',status)
		return doc

	def test_completed_open_request_sources_are_summaries_not_repeated_raw_work(self):
		old=self.source(minutes=-5);self.dispatch(inline=True)
		request=self.linked_request(old)
		frappe.db.set_value('WhatsApp Message',old.name,dict(intake_ai_state='Drafted',intake_ai_coverage=frappe.as_json(dict(requests=[request.name],unresolved=False))))
		fresh=self.source()
		rows=queue._chat_rows(self.account.name,self.sender,self.now,queue.settings())
		self.assertEqual([row.name for row in rows],[fresh.name])
		self.dispatch(inline=True);fresh.reload()
		context=frappe.parse_json(fresh.intake_context_ids)
		self.assertEqual(context['message_ids'],[fresh.name])
		self.assertIn(request.name,[row['name'] for row in context['open_requests']])
		self.assertEqual(old.reload().intake_context_anchor,old.name)

	def test_closed_sources_with_stale_unresolved_flags_do_not_return_as_new_work(self):
		old=self.source(minutes=-5);self.dispatch(inline=True)
		request=self.linked_request(old,'Converted to Order')
		frappe.db.set_value('WhatsApp Message',old.name,dict(intake_ai_state='Unresolved',intake_ai_coverage=frappe.as_json(dict(requests=[request.name],unresolved=True))))
		fresh=self.source()
		self.dispatch(inline=True);fresh.reload()
		self.assertEqual(frappe.parse_json(fresh.intake_context_ids)['message_ids'],[fresh.name])
		self.assertNotIn(request.name,[row['name'] for row in frappe.parse_json(fresh.intake_context_ids)['open_requests']])
		self.assertTrue(frappe.db.exists('WhatsApp Message',old.name))

	def test_explicit_reply_can_include_closed_history_without_reclaiming_it(self):
		old=self.source(minutes=-5);self.dispatch(inline=True)
		request=self.linked_request(old,'Converted to Order')
		frappe.db.set_value('WhatsApp Message',old.name,dict(intake_ai_state='Drafted',intake_ai_coverage=frappe.as_json(dict(requests=[request.name],unresolved=False))))
		fresh=self.source(reply_to_message_id=old.message_id)
		self.dispatch(inline=True);fresh.reload()
		context=frappe.parse_json(fresh.intake_context_ids)
		self.assertEqual(context['message_ids'],[fresh.name])
		self.assertEqual(context['reply_message_ids'],[old.name])
		self.assertEqual(old.reload().intake_context_anchor,old.name)

	def test_unresolved_open_sources_and_changed_closed_sources_are_not_lost(self):
		old=self.source(minutes=-5);self.dispatch(inline=True)
		request=self.linked_request(old)
		frappe.db.set_value('WhatsApp Message',old.name,dict(intake_ai_coverage=frappe.as_json(dict(requests=[request.name],unresolved=True))))
		self.assertIn(old.name,[row.name for row in queue._chat_rows(self.account.name,self.sender,self.now,queue.settings())])
		frappe.db.set_value('Order Intake Request',request.name,'status','Resolved')
		frappe.db.set_value('WhatsApp Message',old.name,'intake_prepare_state','Pending')
		self.assertIn(old.name,[row.name for row in queue._chat_rows(self.account.name,self.sender,self.now,queue.settings())])

	def test_explicit_manual_recovery_can_select_already_covered_evidence(self):
		old=self.source();self.dispatch(inline=True)
		request=self.linked_request(old)
		frappe.db.set_value('WhatsApp Message',old.name,dict(intake_ai_coverage=frappe.as_json(dict(requests=[request.name],unresolved=False))))
		result=queue.recover_selected(self.account.name,self.sender,[old.name],now=self.now)
		self.assertEqual(result['state'],'Context Ready')
		self.assertEqual(result['context']['message_ids'],[old.name])
