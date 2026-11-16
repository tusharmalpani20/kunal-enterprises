"""Audit the production recorder connection across caller rollbacks and retention."""
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from kunal_enterprises.integrations.order_intake_ai_logging import RunRecorder, Writer, RUN, CALL, LoggingAlreadyStarted
from kunal_enterprises.integrations.order_intake_ai_log_retention import cleanup


class TestAILoggingDurability(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.names = []

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		if self.names:
			with Writer(True).transaction() as cursor:
				cursor.execute(f"DELETE FROM `tab{CALL}` WHERE parent IN %s", (tuple(self.names),))
				cursor.execute(f"DELETE FROM `tab{RUN}` WHERE name IN %s", (tuple(self.names),))
		frappe.db.rollback()

	def recorder(self):
		config = frappe._dict(provider="OpenAI", grouping_model="gpt-6-luna", extraction_model="gpt-6-luna",
			reasoning_effort="medium", _intake_api_key="synthetic-logging-audit-secret", pricing=[dict(provider="OpenAI",
				model="gpt-6-luna", rates_confirmed=1, cached_rate_confirmed=1, cache_write_rate_confirmed=1,
				input_per_million="0.10", cached_input_per_million="0.01", output_per_million="0.50",
				cache_write_per_million="0.125", max_context_tokens=272000, service_tier="default")])
		recorder = RunRecorder.start(dict(messages=[], anchor=None), config, "audit-" + uuid4().hex, independent=True)
		self.names.append(recorder.name)
		return recorder

	def paid_call(self, recorder):
		index = recorder.start_call("grouping", "gpt-6-luna", [dict(content="Synthetic complete input")], {}, {})
		recorder.wire_request(index, dict(messages=[dict(content="Synthetic complete input")]))
		recorder.wire_response(index, dict(id="synthetic-response", service_tier="default", choices=[dict(
			message=dict(content="Synthetic invalid model output"))], usage=dict(prompt_tokens=1000, completion_tokens=300,
				prompt_tokens_details=dict(cached_tokens=200, cache_write_tokens=100),
				completion_tokens_details=dict(reasoning_tokens=250))), 200, "synthetic-response")
		recorder.finish_call(index, error_note="Synthetic schema failure")
		return index

	def test_paid_call_survives_caller_rollback_without_committing_the_draft(self):
		marker = frappe.get_doc(dict(doctype="Order Intake Request", sender_name="Uncommitted logging audit")).insert()
		recorder = self.recorder(); self.paid_call(recorder)
		recorder.finish("Needs Attention", note="Synthetic validation failure")
		frappe.db.rollback()
		self.assertFalse(frappe.db.exists("Order Intake Request", marker.name))
		log = frappe.get_doc(RUN, recorder.name)
		self.assertEqual(log.wire_attempts, 1)
		self.assertEqual(log.input_tokens, 1000)
		self.assertEqual(log.output_tokens, 300)
		self.assertEqual(Decimal(str(log.estimated_cost_usd)), Decimal("0.0002345"))
		self.assertIn("Synthetic complete input", log.calls[0].request_json)
		self.assertIn("Synthetic invalid model output", log.calls[0].response_json)

	def test_publication_rollback_is_not_counted_as_a_created_request(self):
		recorder = self.recorder(); self.paid_call(recorder)
		recorder.finish("Drafted", result=dict(created=["synthetic-uncommitted-request"], proposed=[]), publication_pending=True)
		frappe.db.rollback()
		log = frappe.get_doc(RUN, recorder.name)
		self.assertEqual(log.status, "Rolled Back")
		self.assertEqual(log.created_request_count, 0)
		self.assertEqual(log.wire_attempts, 1)
		self.assertEqual(log.input_tokens, 1000)

	def test_payload_retention_keeps_numeric_usage_and_does_not_commit_caller_work(self):
		recorder = self.recorder(); self.paid_call(recorder); recorder.finish("Needs Attention")
		old = add_days(now_datetime(), -31)
		with Writer(True).transaction() as cursor:
			Writer(True).update(cursor, RUN, recorder.name, dict(started_at=old, finished_at=old))
		marker = frappe.get_doc(dict(doctype="Order Intake Request", sender_name="Uncommitted retention audit")).insert()
		# Exercise the production separate-connection path, not the fixture adapter.
		previous = frappe.flags.in_test
		try:
			frappe.flags.in_test = False
			cleanup(max_runs=100)
		finally:
			frappe.flags.in_test = previous
		frappe.db.rollback()
		self.assertFalse(frappe.db.exists("Order Intake Request", marker.name))
		log = frappe.get_doc(RUN, recorder.name)
		self.assertTrue(log.payloads_purged_at)
		self.assertFalse(log.input_snapshot)
		self.assertFalse(log.calls[0].request_json)
		self.assertFalse(log.calls[0].response_json)
		self.assertEqual(log.input_tokens, 1000)
		self.assertEqual(Decimal(str(log.estimated_cost_usd)), Decimal("0.0002345"))
		self.assertIn('"prompt_tokens": 1000', log.calls[0].usage_json)

	def test_duplicate_run_key_is_fenced_on_the_production_connection(self):
		recorder = self.recorder()
		frappe.db.rollback()
		key = frappe.db.get_value(RUN, recorder.name, "run_key")
		with self.assertRaises(LoggingAlreadyStarted):
			RunRecorder.start(dict(messages=[]), recorder.config, key, independent=True)
		self.assertEqual(frappe.db.count(RUN, {"run_key": key}), 1)

	def test_a_failed_log_start_prevents_model_calls(self):
		from kunal_enterprises.integrations import order_intake_ai as ai, order_intake_queue as queue
		account = frappe.get_doc(dict(doctype="WhatsApp Account", account_name="Log failure " + uuid4().hex,
			phone_id=uuid4().hex, status="Active")).insert(ignore_permissions=True)
		source = frappe.get_doc(dict(doctype="WhatsApp Message", type="Incoming", whatsapp_account=account.name,
			**{"from": "919000000085"}, message="Synthetic audit order", message_id=uuid4().hex, content_type="text")).insert(ignore_permissions=True)
		queue.dispatch_pending(force=True, account=account.name, sender="919000000085", inline=True, maintain=False)
		anchor = source.reload().intake_context_anchor; claim = ai._claim(anchor)
		with patch.object(Writer, "insert", side_effect=OSError("synthetic logging database failure")), patch.object(ai, "group") as group:
			result = ai.process(anchor, claim["token"], release_transaction=False)
		self.assertEqual(result["state"], "Needs Attention")
		group.assert_not_called()

	def test_unfinished_runs_are_not_in_the_finished_run_average(self):
		from kunal_enterprises.api.order_intake_ai_logs import summary
		provider = "Audit-" + uuid4().hex
		name = "audit-summary-" + uuid4().hex; self.names.append(name)
		with Writer(False).transaction() as cursor:
			Writer(False).insert(cursor, RUN, dict(name=name, owner="Administrator", creation=now_datetime(),
				modified=now_datetime(), status="Running", started_at=now_datetime(), provider=provider,
				cost_complete=1, estimated_cost_usd=Decimal("0.0002345"), created_request_count=1))
		for status in ("Running", "Awaiting Commit"):
			frappe.db.set_value(RUN, name, "status", status)
			result = summary(provider=provider)
			self.assertEqual(result["complete_cost_runs"], 0)
			self.assertEqual(result["requests_created"], 0)
		frappe.db.set_value(RUN, name, "status", "Drafted")
		self.assertEqual(summary(provider=provider)["complete_cost_runs"], 1)

	def test_default_summary_covers_thirty_calendar_days_and_cache_writes(self):
		from kunal_enterprises.api.order_intake_ai_logs import summary
		from frappe.utils import getdate
		provider = "Audit-" + uuid4().hex
		for days, tokens in ((0, 3), (-29, 7), (-30, 100)):
			name = "audit-summary-" + uuid4().hex; self.names.append(name)
			with Writer(False).transaction() as cursor:
				Writer(False).insert(cursor, RUN, dict(name=name, owner="Administrator", creation=now_datetime(),
					modified=now_datetime(), status="Drafted", started_at=add_days(getdate(), days), provider=provider,
					cache_write_tokens=tokens))
		result = summary(provider=provider)
		self.assertEqual(result["runs"], 2)
		self.assertEqual(result["cache_write_tokens"], 10)
