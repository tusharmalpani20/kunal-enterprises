"""Paid-call evidence, repair histories, usage and permissions through real adapters."""
import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime
import httpx
from openai import AsyncOpenAI

from kunal_enterprises.integrations import order_intake_ai_models as models
from kunal_enterprises.integrations.order_intake_ai_logging import RunRecorder, RUN, CALL
from kunal_enterprises.integrations.order_intake_ai_log_retention import cleanup
from kunal_enterprises.tests import test_foundation as foundation


class TestOrderIntakeAILogging(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.config = frappe.get_single("Order Intake Settings")
		self.config._intake_api_key = "sk-synthetic-key-for-logging-tests"
		self.config.set("pricing", [dict(provider="OpenAI", model="gpt-6-luna", rates_confirmed=1,
			cached_rate_confirmed=1, cache_write_rate_confirmed=1, input_per_million=.1,
			cached_input_per_million=.01, output_per_million=.5, cache_write_per_million=.125,
			service_tier="default", max_context_tokens=272000)])
		self.config.provider = "OpenAI"
		self.config.grouping_model = self.config.extraction_model = "gpt-6-luna"
		self.config.transport_retries = 2; self.config.output_retries = 2
		self.payload = dict(messages=[dict(name="SYNTHETIC-1", message="Four sheets for synthetic review")], open_requests=[])
		self.log = RunRecorder.start(dict(anchor="SYNTHETIC-1", messages=self.payload["messages"], sender="synthetic-sender"), self.config, uuid4().hex, independent=False)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def completion(self, content, usage=True):
		body = dict(id="synthetic-response", object="chat.completion", created=1, model="gpt-6-luna",
			choices=[dict(index=0, message=dict(role="assistant", content=content), finish_reason="stop")])
		if usage:
			body["usage"] = dict(prompt_tokens=1000, completion_tokens=300, total_tokens=1300,
				prompt_tokens_details=dict(cached_tokens=200, cache_write_tokens=100), completion_tokens_details=dict(reasoning_tokens=250))
		return body

	def valid(self):
		return json.dumps(dict(groups=[dict(message_ids=["SYNTHETIC-1"], target_request=None, request_hint="One synthetic order")], unresolved_message_ids=[]))

	def model_call(self, responses):
		requests = []
		def handler(request):
			requests.append(json.loads(request.content))
			response = responses[len(requests) - 1]
			return httpx.Response(response[0], json=response[1], headers={"x-request-id": "synthetic-request-id"})
		def factory(**kwargs):
			client = kwargs["http_client"]
			# Keep the production HTTP hooks while replacing all network routing.
			client._transport = httpx.MockTransport(handler)
			client._mounts = {}
			return AsyncOpenAI(**kwargs)
		with patch("openai.AsyncOpenAI", side_effect=factory), patch.object(models.asyncio, "sleep", new=AsyncMock()):
			result = models.group(self.config, self.payload, {}, models.RequestBudget(8, recorder=self.log))
		return result, requests

	def test_invalid_output_and_repair_keep_exact_inputs_outputs_and_usage(self):
		result, requests = self.model_call([(200, self.completion("not-json")), (200, self.completion(self.valid()))])
		self.log.finish("Drafted", result={"created": ["SYNTHETIC-REQUEST"]})
		doc = frappe.get_doc(RUN, self.log.name)
		self.assertEqual(len(doc.calls), 2)
		self.assertEqual(json.loads(doc.calls[0].request_json), requests[0])
		self.assertEqual(json.loads(doc.calls[0].response_json)["choices"][0]["message"]["content"], "not-json")
		self.assertGreater(len(requests[1]["messages"]), len(requests[0]["messages"]))
		self.assertEqual(doc.input_tokens, 2000); self.assertEqual(doc.output_tokens, 600)
		self.assertEqual(doc.reasoning_tokens, 500); self.assertEqual(doc.cached_input_tokens, 400)
		self.assertAlmostEqual(doc.estimated_cost_usd, .000469, places=9)
		self.assertTrue(doc.cost_complete)
		self.assertIn("grouping", doc.stages_json)
		self.assertNotIn(self.config._intake_api_key, json.dumps(doc.as_dict(), default=str))

	def test_oversized_provider_cost_does_not_lose_response_evidence(self):
		body = self.completion(self.valid())
		body["usage"]["cost"] = "1E1000"
		self.model_call([(200, body)])
		self.log.finish("Drafted")
		doc = frappe.get_doc(RUN, self.log.name)
		self.assertEqual(doc.status, "Drafted")
		self.assertFalse(doc.calls[0].provider_cost_known)
		self.assertTrue(doc.calls[0].cost_known)
		self.assertEqual(json.loads(doc.calls[0].response_json)["usage"]["cost"], "1E1000")
		self.assertEqual(json.loads(doc.calls[0].usage_json)["cost"], "1E1000")

	def test_retry_errors_and_missing_usage_are_not_free_calls(self):
		self.model_call([(503, {"error": {"message": "Temporarily unavailable"}}), (200, self.completion(self.valid(), usage=False))])
		self.log.finish("Drafted")
		doc = frappe.get_doc(RUN, self.log.name)
		self.assertEqual(doc.wire_attempts, 2)
		self.assertEqual(doc.calls[0].state, "Error")
		self.assertEqual(doc.calls[0].http_status, 503)
		self.assertEqual(doc.unknown_usage_calls, 2)
		self.assertEqual(doc.unknown_cost_calls, 2)
		self.assertFalse(doc.cost_complete)

	def test_malformed_provider_response_is_retained_before_sdk_validation(self):
		with self.assertRaises(Exception):
			self.model_call([(200, {"id": "malformed", "usage": {"prompt_tokens": 10, "completion_tokens": 5}})])
		self.log.finish("Needs Attention")
		doc = frappe.get_doc(RUN, self.log.name)
		self.assertIn("malformed", doc.calls[0].response_json)
		self.assertTrue(doc.calls[0].usage_known)
		self.assertIn("UnexpectedModelBehavior", doc.stages_json)

	def test_completed_payloads_expire_but_metrics_remain_and_active_runs_are_kept(self):
		self.model_call([(200, self.completion(self.valid()))]); self.log.finish("Drafted")
		old = add_to_date(now_datetime(), days=-40, as_datetime=True)
		frappe.db.set_value(RUN, self.log.name, "started_at", old)
		active = RunRecorder.start(dict(anchor="SYNTHETIC-2"), self.config, uuid4().hex, independent=False)
		cleanup()
		doc = frappe.get_doc(RUN, self.log.name)
		self.assertTrue(doc.payloads_purged_at); self.assertFalse(doc.input_snapshot)
		self.assertFalse(doc.calls[0].request_json); self.assertFalse(doc.calls[0].response_json)
		self.assertEqual(doc.input_tokens, 1000); self.assertTrue(doc.cost_complete)
		self.assertEqual(frappe.db.get_value(RUN, active.name, "status"), "Running")

	def test_crashed_runs_are_marked_interrupted_without_claiming_order_creation(self):
		self.log.start_call("grouping", "gpt-6-luna", [], {}, {})
		frappe.db.set_value(RUN, self.log.name, "started_at", add_to_date(now_datetime(), days=-2, as_datetime=True))
		cleanup()
		doc = frappe.get_doc(RUN, self.log.name)
		self.assertEqual(doc.status, "Interrupted"); self.assertEqual(doc.calls[0].state, "Interrupted")
		self.assertEqual(doc.unknown_usage_calls, 1); self.assertEqual(doc.created_request_count, 0)

	def test_log_permissions_and_server_managed_rows(self):
		from frappe.client import get
		from kunal_enterprises.api.order_intake_ai_logs import summary
		self.log.start_call("grouping", "gpt-6-luna", [], {}, {})
		for role in ("Owner", "Admin", "Order Coordinator"):
			frappe.set_user("Administrator")
			user = foundation.TestOrderSubmission._create_role_user(self, "ai-log-" + uuid4().hex + "@example.com", role)
			frappe.set_user(user.name)
			if role == "Order Coordinator":
				with self.assertRaises(frappe.PermissionError): get(RUN, self.log.name)
				with self.assertRaises(frappe.PermissionError): get(CALL, self.log.calls[0]["name"], parent=RUN)
				with self.assertRaises(frappe.PermissionError): summary()
			else:
				self.assertEqual(get(RUN, self.log.name)["name"], self.log.name)
				self.assertGreaterEqual(summary()["runs"], 1)
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.PermissionError): frappe.get_doc(dict(doctype=RUN, status="Fake")).insert(ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError): frappe.get_doc(RUN, self.log.name).save(ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError): frappe.delete_doc(RUN, self.log.name, ignore_permissions=True)
