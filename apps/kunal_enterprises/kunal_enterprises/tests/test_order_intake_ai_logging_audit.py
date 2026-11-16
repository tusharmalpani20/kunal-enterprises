"""Independent audit of usage accounting and rates, without live provider calls."""
from decimal import Decimal
import base64
import hashlib
import json
from unittest import TestCase

from kunal_enterprises.integrations.order_intake_ai_costs import estimate_cost, parse_usage
from kunal_enterprises.integrations.order_intake_ai_logging import _json, sanitized, RunRecorder


class TestAILoggingCostAudit(TestCase):
	def pricing(self, **changes):
		return dict(rates_confirmed=1, cached_rate_confirmed=1, cache_write_rate_confirmed=1,
			input_per_million="0.10", cached_input_per_million="0.01", output_per_million="0.50",
			cache_write_per_million="0.125", max_context_tokens=272000, service_tier="default", **changes)

	def usage(self, reasoning=250):
		return parse_usage(dict(prompt_tokens=1000, completion_tokens=300,
			prompt_tokens_details=dict(cached_tokens=200, cache_write_tokens=100),
			completion_tokens_details=dict(reasoning_tokens=reasoning)))

	def test_cached_writes_reads_and_reasoning_are_not_double_charged(self):
		known, amount = estimate_cost(self.usage(), self.pricing())
		# 700 ordinary input + 200 cache reads + 100 writes + 300 output.
		self.assertTrue(known)
		self.assertEqual(amount, Decimal("0.0002345"))
		self.assertEqual(estimate_cost(self.usage(reasoning=0), self.pricing())[1], amount)

	def test_missing_usage_or_unconfirmed_rates_are_not_claimed_free(self):
		for raw in (None, {}, dict(prompt_tokens=10), dict(completion_tokens=10)):
			usage = parse_usage(raw)
			self.assertFalse(usage["usage_known"])
			self.assertFalse(estimate_cost(usage, self.pricing())[0])
		for field in ("rates_confirmed", "cached_rate_confirmed", "cache_write_rate_confirmed"):
			pricing = self.pricing(); pricing[field] = 0
			self.assertFalse(estimate_cost(self.usage(), pricing)[0])

	def test_unmatched_service_or_context_tier_is_unknown(self):
		self.assertFalse(estimate_cost(self.usage(), self.pricing(), service_tier="priority")[0])
		usage = self.usage(); usage["input_tokens"] = 272001
		self.assertFalse(estimate_cost(usage, self.pricing())[0])

	def test_invalid_usage_never_crashes_or_produces_a_known_estimate(self):
		for value in (-1, True, 1.25, float("nan"), float("inf"), 10 ** 500):
			with self.subTest(value_type=type(value).__name__):
				usage = parse_usage(dict(prompt_tokens=value, completion_tokens=10))
				self.assertFalse(usage["usage_known"])
				self.assertFalse(estimate_cost(usage, self.pricing())[0])
		self.assertFalse(parse_usage(dict(prompt_tokens=10, completion_tokens=2,
			prompt_tokens_details=dict(cached_tokens=8, cache_write_tokens=4)))["usage_known"])
		self.assertFalse(parse_usage(dict(prompt_tokens=10, completion_tokens=2,
			completion_tokens_details=dict(reasoning_tokens=3)))["usage_known"])

	def test_provider_reported_zero_and_missing_cost_remain_distinct(self):
		self.assertTrue(parse_usage(dict(cost=0))["provider_cost_known"])
		self.assertFalse(parse_usage({})["provider_cost_known"])
		for cost in ("NaN", "-1", "private invalid provider value"):
			self.assertFalse(parse_usage(dict(cost=cost))["provider_cost_known"])

	def test_invalid_pricing_snapshot_is_unknown_without_breaking_logging(self):
		for field, value in (("max_context_tokens", "invalid"), ("input_per_million", "NaN"),
			("input_per_million", "-0.1"), ("output_per_million", "invalid")):
			pricing = self.pricing(); pricing[field] = value
			self.assertFalse(estimate_cost(self.usage(), pricing)[0])

	def test_unstorable_provider_cost_is_unknown_but_raw_usage_is_preserved(self):
		for value in ("1E1000", "1E1000000", 10 ** 500):
			with self.subTest(value_type=type(value).__name__):
				raw = dict(cost=value, prompt_tokens=10, completion_tokens=2)
				usage = parse_usage(raw)
				self.assertTrue(usage["usage_known"])
				self.assertFalse(usage["provider_cost_known"])
				self.assertEqual(usage["provider_cost_usd"], Decimal(0))
				self.assertEqual(json.loads(_json(raw))["cost"], value)

	def test_unstorable_estimate_or_overflowing_rates_remain_unknown(self):
		for value in ("1E1000000", "1E20"):
			pricing = self.pricing(); pricing["input_per_million"] = value
			self.assertFalse(estimate_cost(self.usage(), pricing)[0])

	def test_valid_partial_token_counts_are_kept_in_run_totals(self):
		recorder = object.__new__(RunRecorder)
		recorder.calls = [parse_usage(dict(prompt_tokens=100, completion_tokens=None)),
			parse_usage(dict(prompt_tokens=None, completion_tokens=30))]
		totals = recorder._totals()
		self.assertEqual(totals["input_tokens"], 100)
		self.assertEqual(totals["output_tokens"], 30)
		self.assertEqual(totals["unknown_usage_calls"], 2)
		self.assertFalse(totals["cost_complete"])


class TestAILoggingPayloadAudit(TestCase):
	def test_text_is_preserved_but_configured_credentials_and_headers_are_redacted(self):
		key = "synthetic-provider-secret-123"
		text = "Customer: श्री Example. 21317 MR 4 NOS; Fevicol 20kg pack 1 NOS."
		payload = dict(messages=[dict(content=text)], error="Unexpected " + key,
			Authorization="Bearer " + key, nested=dict(api_key=key))
		result = sanitized(payload, secrets=(key,))
		self.assertEqual(result["messages"][0]["content"], text)
		self.assertNotIn(key, json.dumps(result))
		self.assertEqual(result["Authorization"], "[REDACTED]")

	def test_binary_payload_is_hashed_instead_of_copied_into_the_database(self):
		content = b"synthetic private PDF bytes"
		encoded = base64.b64encode(content).decode()
		value = sanitized(dict(file_data="data:application/pdf;base64," + encoded))
		self.assertNotIn(encoded, json.dumps(value))
		self.assertEqual(value["file_data"]["sha256"], hashlib.sha256(content).hexdigest())
		self.assertEqual(value["file_data"]["size_bytes"], len(content))
		self.assertEqual(value["file_data"]["media_type"], "application/pdf")

	def test_nonfinite_provider_values_cannot_discard_the_entire_response_log(self):
		value = _json(dict(usage=dict(cost=float("nan")), response="Keep this provider response"))
		parsed = json.loads(value)
		self.assertEqual(parsed["response"], "Keep this provider response")
		self.assertIsInstance(parsed["usage"]["cost"], (str, dict))
