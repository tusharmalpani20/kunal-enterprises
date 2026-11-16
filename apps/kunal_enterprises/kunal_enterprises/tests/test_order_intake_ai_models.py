"""Exercise PydanticAI history/validation and retry boundaries without network calls."""
import json
import httpx
from openai import AsyncOpenAI
from time import monotonic
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage
from pydantic_ai.profiles import ModelProfile

from kunal_enterprises.integrations import order_intake_ai_models as models


class TestOrderIntakeAIModels(TestCase):
	def setUp(self):
		self.config = SimpleNamespace(max_input_tokens=20000, max_output_tokens=4000,
			request_timeout_seconds=60, output_retries=2, transport_retries=2, reasoning_effort="medium")
		self.payload = dict(messages=[dict(name="MSG-1", message="2 sheets please")], open_requests=[])
		self.budget = models.RequestBudget(4)

	def run_group(self, callback, budget=None, client=None):
		budget = budget or self.budget
		model = models.BoundedModel(FunctionModel(callback,
			profile=ModelProfile(supports_json_schema_output=True)), budget, self.config.transport_retries, client)
		with patch.object(models, "make_model", return_value=model):
			return models.group(self.config, self.payload, {}, budget)

	async def invalid_response(self, messages, info):
		return self.response(["OTHER-CHAT"])

	async def valid_response(self, messages, info):
		return self.response()

	def response(self, names=None):
		return ModelResponse(parts=[TextPart(json.dumps(dict(groups=[dict(message_ids=names or ["MSG-1"], target_request=None, request_hint="Single request")],
			unresolved_message_ids=[])))])

	def test_invalid_references_are_corrected_in_the_same_history(self):
		calls = []
		async def provider(messages, info):
			calls.append(list(messages))
			return self.response(["OTHER-CHAT"] if len(calls) == 1 else None)
		result = self.run_group(provider)
		self.assertEqual(result.groups[0].message_ids, ["MSG-1"])
		self.assertEqual(self.budget.used, 2)
		self.assertGreater(len(calls[1]), len(calls[0]))
		self.assertTrue(any(isinstance(part, RetryPromptPart) for message in calls[1] for part in message.parts))

	def test_token_limits_apply_per_response_not_across_validation_retries(self):
		calls = []
		async def provider(messages, info):
			calls.append(messages)
			response = self.response(['OTHER-CHAT'] if len(calls) == 1 else None)
			response.usage = RequestUsage(input_tokens=12000, output_tokens=3000)
			return response
		result = self.run_group(provider)
		self.assertEqual(result.groups[0].message_ids, ['MSG-1'])
		self.assertEqual(self.budget.used, 2)

	def test_single_oversize_usage_is_logged_and_stops_without_retry(self):
		for usage in (RequestUsage(input_tokens=20001, output_tokens=10),
			RequestUsage(input_tokens=100, output_tokens=4001)):
			budget = models.RequestBudget(4, recorder=Mock())
			async def provider(messages, info):
				response = self.response()
				response.usage = usage
				return response
			with self.assertRaisesRegex(models.AIProblem, 'per-request token limit'):
				self.run_group(provider, budget)
			self.assertEqual(budget.used, 1)
			budget.recorder.finish_call.assert_called_once()
			self.assertEqual(budget.recorder.finish_call.call_args.kwargs['response'].usage, usage)
			self.assertIn('per-request token limit', budget.recorder.finish_call.call_args.kwargs['error_note'])
			budget.recorder.stage_failure.assert_called_once()

	def test_retry_history_is_preflighted_before_another_provider_call(self):
		async def provider(messages, info):
			return ModelResponse(parts=[TextPart('unparseable ' * 30000)],
				usage=RequestUsage(input_tokens=1000, output_tokens=1000))
		with self.assertRaises(models.InputTooLarge):
			self.run_group(provider)
		self.assertEqual(self.budget.used, 1)

	def test_transport_retries_share_the_request_budget_and_authentication_does_not_retry(self):
		for status, expected, retry in ((429, 3, True), (503, 3, True), (401, 1, False), (402, 1, False)):
			budget = models.RequestBudget(4)
			async def provider(messages, info):
				raise ModelHTTPError(status, "synthetic", body="private provider response")
			with patch.object(models.asyncio, "sleep", new=AsyncMock()), self.assertRaises(models.AIProblem) as raised:
				self.run_group(provider, budget)
			self.assertEqual(budget.used, expected)
			self.assertEqual(raised.exception.retry, retry)
			self.assertNotIn("private", raised.exception.note)

	def test_billing_quota_429_errors_stop_after_one_attempt(self):
		for code in ("insufficient_quota", "credit_balance_exhausted", "project_spend_limit_exceeded",
			"organization_spend_limit_exceeded", "organization_usage_limit_exceeded"):
			budget = models.RequestBudget(4)
			async def provider(messages, info):
				raise ModelHTTPError(429, "synthetic", body={"error": {"code": code, "message": "private billing response"}})
			with patch.object(models.asyncio, "sleep", new=AsyncMock()), self.assertRaises(models.AIProblem) as raised:
				self.run_group(provider, budget)
			self.assertEqual(budget.used, 1, code)
			self.assertFalse(raised.exception.retry)
			self.assertNotIn("private", raised.exception.note)

	def test_two_requests_with_same_source_require_distinct_extraction_scope(self):
		calls = []
		async def provider(messages, info):
			calls.append(messages)
			groups = [{"message_ids": ["MSG-1"], "target_request": None, "request_hint": hint}
				for hint in (["", ""] if len(calls) == 1 else ["Customer A laminate order", "Customer B adhesive order"])]
			return ModelResponse(parts=[TextPart(json.dumps(dict(groups=groups, unresolved_message_ids=[])))])
		result = self.run_group(provider)
		self.assertEqual(self.budget.used, 2)
		self.assertEqual(result.groups[0].request_hint, "Customer A laminate order")
		self.assertEqual(result.groups[1].request_hint, "Customer B adhesive order")

	def test_output_corrections_cannot_exceed_shared_budget(self):
		budget = models.RequestBudget(1)
		with self.assertRaises(models.AIProblem):
			self.run_group(self.invalid_response, budget)
		self.assertEqual(budget.used, 1)

	def test_owned_provider_client_is_closed_even_when_validation_fails(self):
		client = SimpleNamespace(close=AsyncMock())
		with self.assertRaises(models.AIProblem):
			self.run_group(self.invalid_response, models.RequestBudget(1), client)
		client.close.assert_awaited_once()

	def test_expired_deadline_and_full_text_limit_prevent_provider_requests(self):
		budget = models.RequestBudget(4, deadline=monotonic() - 1)
		with self.assertRaises(models.AIProblem):
			self.run_group(self.valid_response, budget)
		self.assertEqual(budget.used, 0)
		self.config.max_input_tokens = 100
		with patch.object(models, "make_model") as make:
			result = models.group(self.config, self.payload, {}, self.budget)
		self.assertEqual(result.unresolved_message_ids, ["MSG-1"])
		make.assert_not_called()

	def test_duplicate_existing_request_targets_are_corrected_before_publication(self):
		self.payload["open_requests"] = [dict(name="OIR-1")]
		calls = []
		async def provider(messages, info):
			calls.append(messages)
			groups = [dict(message_ids=["MSG-1"], target_request="OIR-1", request_hint="Existing request")]
			return ModelResponse(parts=[TextPart(json.dumps(dict(groups=groups * (2 if len(calls) == 1 else 1), unresolved_message_ids=[])))])
		self.assertEqual(len(self.run_group(provider).groups), 1)
		self.assertEqual(self.budget.used, 2)

	def test_real_provider_adapters_send_native_schema_and_correct_reasoning_settings(self):
		for provider, expected_host, model in (("OpenAI", "api.openai.com", "gpt-6-luna"),
			("OpenRouter", "openrouter.ai", "openai/gpt-6-luna")):
			self.payload["business_context"] = dict(receiving_company="Harbor Supplies",
				company_aliases=["Harbor Supply"], warehouses=[dict(name="Dock", godown_name="Dock Warehouse")],
				warehouses_truncated=False)
			self.config.provider = provider
			self.config.grouping_model = model
			self.config.get = lambda key: getattr(self.config, key)
			self.config._intake_api_key = "synthetic-provider-key"
			requests, clients = [], []
			def handler(request):
				requests.append(request)
				return httpx.Response(200, json={"id": "synthetic-completion", "object": "chat.completion", "created": 1,
					"model": model, "provider": "OpenAI", "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps({
						"groups": [{"message_ids": ["MSG-1"], "target_request": None, "request_hint": "Single request"}], "unresolved_message_ids": []})}, "finish_reason": "stop"}],
					"usage": {"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40}})
			def factory(**kwargs):
				client = AsyncOpenAI(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
				clients.append(client)
				return client
			with patch("openai.AsyncOpenAI", side_effect=factory):
				result = models.group(self.config, self.payload, {}, models.RequestBudget(2))
			self.assertEqual(result.groups[0].message_ids, ["MSG-1"])
			self.assertEqual(len(requests), 1)
			self.assertEqual(requests[0].url.host, expected_host)
			body = json.loads(requests[0].content)
			self.assertEqual(body["model"], model)
			wire_prompt = json.dumps(body["messages"])
			self.assertIn("Harbor Supplies", wire_prompt)
			self.assertIn("Dock Warehouse", wire_prompt)
			self.assertIn("not a customer merely because its name appears", wire_prompt)
			self.assertIn("without asking what its abbreviation stands for", wire_prompt)
			self.assertIn("relationship_note=null", wire_prompt)
			self.assertEqual(body["response_format"]["type"], "json_schema")
			self.assertTrue(body["response_format"]["json_schema"]["strict"])
			if provider == "OpenAI":
				self.assertEqual(body["reasoning_effort"], "medium")
			else:
				self.assertEqual(body["reasoning"]["effort"], "medium")
				self.assertFalse(body["provider"]["allow_fallbacks"])
			self.assertTrue(all(client.is_closed() for client in clients))

	def test_manual_evidence_cannot_be_silently_marked_resolved(self):
		self.payload['messages'][0]['manual_review_reason'] = 'Unsupported format'
		calls = []
		async def provider(messages, info):
			calls.append(messages)
			return ModelResponse(parts=[TextPart(json.dumps(dict(groups=[],
				unresolved_message_ids=[] if len(calls) == 1 else ['MSG-1'])))])
		result = self.run_group(provider)
		self.assertEqual(result.unresolved_message_ids, ['MSG-1'])
		self.assertEqual(len(calls), 2)

	def test_unique_provider_message_aliases_normalize_to_local_names_without_repair(self):
		self.payload['messages'][0]['message_id'] = 'wamid-provider-1'
		async def provider(messages, info):
			return self.response(['wamid-provider-1'])
		result = self.run_group(provider)
		self.assertEqual(result.groups[0].message_ids, ['MSG-1'])
		self.assertEqual(self.budget.used, 1)

	def test_provider_aliases_normalize_unresolved_and_extraction_evidence_references(self):
		self.payload['messages'][0].update(message_id='wamid-provider-1', manual_review_reason='Unreadable image')
		async def grouping(messages, info):
			return ModelResponse(parts=[TextPart(json.dumps(dict(groups=[], unresolved_message_ids=['wamid-provider-1'])))])
		self.assertEqual(self.run_group(grouping).unresolved_message_ids, ['MSG-1'])
		async def extracted(messages, info):
			return ModelResponse(parts=[TextPart(json.dumps(dict(request_type='Order', summary='Four sheets', customer_text=None,
				salesperson_text=None, delivery_address=None, delivery_contact_name=None, delivery_contact_number=None,
				items=[dict(original_text='21317 MR', source_message='wamid-provider-1', quantity=4, unit='SHEET',
					warehouse_text='Goshamahal', warehouse_source_message='wamid-provider-1', notes=None)],
				unresolved_questions=['Review image'], unresolved_message_ids=['wamid-provider-1'])))])
		model = models.BoundedModel(FunctionModel(extracted, profile=ModelProfile(supports_json_schema_output=True)), self.budget, 0)
		with patch.object(models, 'make_model', return_value=model):
			result = models.extract(self.config, self.payload, {}, self.budget)
		self.assertEqual(result.items[0].source_message, 'MSG-1')
		self.assertEqual(result.items[0].warehouse_source_message, 'MSG-1')
		self.assertEqual(result.unresolved_message_ids, ['MSG-1'])

	def test_ambiguous_provider_aliases_name_collisions_and_invented_ids_require_repair(self):
		for messages, reference in [
			([dict(name='MSG-1', message_id='shared'), dict(name='MSG-2', message_id='shared')], 'shared'),
			([dict(name='MSG-1', message_id='MSG-2'), dict(name='MSG-2', message_id='wire-2')], 'MSG-2'),
			([dict(name='MSG-1', message_id='wire-1')], 'invented'),
		]:
			self.payload['messages'] = messages
			async def provider(history, info):
				return ModelResponse(parts=[TextPart(json.dumps(dict(groups=[], unresolved_message_ids=[reference])))])
			with self.assertRaises(models.AIProblem):
				self.run_group(provider, models.RequestBudget(1))

	def test_shared_product_heading_is_not_an_extra_ordered_item(self):
		self.payload['messages'][0]['message'] = ('Harbor fibreboard\nboth sides\n\n'
			'8. - 2no - 45%\n2200. - 2no\nR 12 - 2no - 440/-\nNavrang plywood nizampet please')
		calls = []
		async def extracted(history, info):
			calls.append(history)
			labels = ['Harbor fibreboard both sides', '8.', '2200.', 'R12'] if len(calls) == 1 else [
				'Harbor fibreboard both sides 8.', 'Harbor fibreboard both sides 2200.', 'Harbor fibreboard both sides R12']
			items = [dict(original_text=label, source_message='MSG-1', quantity=None if label == 'Harbor fibreboard both sides' else 2,
				unit='no', warehouse_text=None, warehouse_source_message=None, notes=None) for label in labels]
			return ModelResponse(parts=[TextPart(json.dumps(dict(request_type='Order', summary='Three variants',
				customer_text='Navrang plywood nizampet', salesperson_text=None, delivery_address=None,
				delivery_contact_name=None, delivery_contact_number=None, items=items,
				unresolved_questions=[], unresolved_message_ids=[])))])
		model = models.BoundedModel(FunctionModel(extracted, profile=ModelProfile(supports_json_schema_output=True)), self.budget, 0)
		with patch.object(models, 'make_model', return_value=model):
			result = models.extract(self.config, self.payload, {}, self.budget)
		self.assertEqual(len(result.items), 3)
		self.assertTrue(all(item.original_text.startswith('Harbor fibreboard both sides ') for item in result.items))
		self.assertEqual(self.budget.used, 2)
		self.assertTrue(any(isinstance(part, RetryPromptPart) for message in calls[1] for part in message.parts))

	def test_customer_heading_is_not_prepended_to_variant_lookup_words(self):
		result = models.Extraction(request_type='Order', summary='Two products', customer_text='Harbor Supplies',
			salesperson_text=None, delivery_address=None, delivery_contact_name=None, delivery_contact_number=None,
			items=[models.Item(original_text=label, source_message='M1', quantity=quantity,
				unit=None, warehouse_text=None, warehouse_source_message=None, notes=None)
				for label, quantity in [('Harbor Supplies', None), ('A8', 2), ('A12', 3)]],
			unresolved_questions=[], unresolved_message_ids=[])
		messages = [dict(name='M1', message='Harbor Supplies\nA8 - 2no\nA12 - 3no')]
		self.assertIsNone(models._shared_product_heading(result, messages))

	def test_dropped_customer_branch_is_repaired_in_same_mocked_extraction_history(self):
		self.payload['messages'][0]['message'] = '2. APARNA ENTERPRISES LTD - JUBILEE HILLS\n21022 SF - 2 sheets\nDispatch from Kukatpally.'
		calls = []
		async def extracted(history, info):
			calls.append(history)
			customer = 'APARNA ENTERPRISES LTD' if len(calls) == 1 else 'APARNA ENTERPRISES LTD - JUBILEE HILLS'
			return ModelResponse(parts=[TextPart(json.dumps(dict(request_type='Order', summary='Two sheets', customer_text=customer,
				salesperson_text=None, delivery_address=None, delivery_contact_name=None, delivery_contact_number=None,
				items=[], unresolved_questions=[], unresolved_message_ids=[])))])
		model = models.BoundedModel(FunctionModel(extracted, profile=ModelProfile(supports_json_schema_output=True)), self.budget, 0)
		with patch.object(models, 'make_model', return_value=model):
			result = models.extract(self.config, self.payload, {}, self.budget)
		self.assertEqual(result.customer_text, 'APARNA ENTERPRISES LTD - JUBILEE HILLS')
		self.assertEqual(self.budget.used, 2)
		self.assertTrue(any(isinstance(part, RetryPromptPart) for message in calls[1] for part in message.parts))

	def test_model_grouping_softens_unsupported_target_without_a_provider_retry(self):
		self.payload = dict(messages=[dict(name='OLD', message='21317 MR 4'),
			dict(name='NEW', message='21317 MR 2\nMaa Annapurna')],
			open_requests=[dict(name='OIR-1', source_messages=['OLD'])])
		async def grouping(history, info):
			return ModelResponse(parts=[TextPart(json.dumps(dict(groups=[dict(message_ids=['OLD', 'NEW'],
				target_request='OIR-1', request_hint='Same SKU, changed quantity', relationship='correction',
				relationship_evidence=[dict(source_message='NEW', quote='21317 MR 2')])], unresolved_message_ids=[])))])
		result = self.run_group(grouping)
		self.assertEqual(self.budget.used, 1)
		self.assertEqual([g.message_ids for g in result.groups], [['OLD'], ['NEW']])
		self.assertIsNone(result.groups[1].target_request)
		self.assertTrue(result.groups[1].relationship_note)

	def test_separate_complete_bookings_for_same_customer_need_no_relationship_warning(self):
		self.payload['messages'] = [
			dict(name='FIRST', message='Order for Shyam Plywood\n21317 MR 4\nDispatch Goshamahal'),
			dict(name='SECOND', message='Order for Shyam Plywood\n21317 MR 5\nDispatch KP godown'),
		]
		async def grouping(history, info):
			return ModelResponse(parts=[TextPart(json.dumps(dict(groups=[
				dict(message_ids=[name], target_request=None, relationship='new', relationship_note=None,
					request_hint='Separate booking ' + name)
				for name in ['FIRST', 'SECOND']], unresolved_message_ids=[])))])
		result = self.run_group(grouping)
		self.assertEqual([g.message_ids for g in result.groups], [['FIRST'], ['SECOND']])
		self.assertTrue(all(g.relationship_note is None for g in result.groups))
		self.assertEqual(result.unresolved_message_ids, [])


class TestIntakeTokenBudget(TestCase):
	def test_text_tokens_are_not_utf8_bytes_and_special_text_is_safe(self):
		from kunal_enterprises.integrations.order_intake_ai_budget import estimate_input_tokens
		payload = {"messages": [{"name": "M1", "message": "order sheets warehouse " * 1000 + "<|endoftext|>"}]}
		estimated = estimate_input_tokens("", "", models.Grouping, payload, {})
		self.assertLess(estimated, len(json.dumps(payload).encode()))
		self.assertGreater(estimated, 3000)

	def test_oversized_extraction_is_typed_and_makes_no_provider_request(self):
		config = SimpleNamespace(max_input_tokens=100)
		with patch.object(models, "make_model") as make, self.assertRaises(models.InputTooLarge) as raised:
			models.extract(config, {"messages": [{"name": "M1", "message": "order"}]}, {}, models.RequestBudget(4))
		make.assert_not_called()
		self.assertFalse(raised.exception.retry)
		self.assertGreater(raised.exception.estimated_tokens, raised.exception.limit)

	def test_oversized_independent_reply_threads_split_without_losing_sources(self):
		from kunal_enterprises.integrations.order_intake_ai_budget import grouping_batches, estimate_input_tokens
		rows = [{"name": f"M{i}", "message_id": f"W{i}", "message": "laminate order " * 500} for i in range(4)]
		rows[1]["reply_to_message_id"] = "W0"
		rows[3]["reply_to_message_id"] = "W2"
		payload = {"messages": rows, "open_requests": []}
		limit = estimate_input_tokens("", "", models.Grouping, dict(payload, messages=rows[:2]), {}) + 10
		batches, unresolved = grouping_batches(SimpleNamespace(max_input_tokens=limit), payload, {}, "", "", models.Grouping)
		self.assertEqual([[row["name"] for row in batch["messages"]] for batch, _ in batches], [["M0", "M1"], ["M2", "M3"]])
		self.assertEqual(unresolved, [])
		# A bare warehouse/customer continuation makes splitting unsafe.
		payload["messages"] = rows + [{"name": "M4", "message": "Dispatch from Kukatpally"}]
		batches, unresolved = grouping_batches(SimpleNamespace(max_input_tokens=limit), payload, {}, "", "", models.Grouping)
		self.assertEqual(batches, [])
		self.assertEqual(set(unresolved), {"M0", "M1", "M2", "M3", "M4"})

	def test_budgeted_text_above_old_byte_limit_is_processed(self):
		test = TestOrderIntakeAIModels()
		test.setUp()
		test.payload["messages"][0]["message"] = "order sheets warehouse " * 1200
		self.assertGreater(len(json.dumps(test.payload).encode()), 20000)
		result = test.run_group(test.valid_response)
		self.assertEqual(result.groups[0].message_ids, ["MSG-1"])
		self.assertEqual(test.budget.used, 1)

	def test_split_calls_do_not_publish_two_updates_to_one_existing_request(self):
		payloads = [(dict(messages=[dict(name=name)], open_requests=[dict(name="OIR-1")]), {}) for name in ("M1", "M2")]
		responses = [models.Grouping(groups=[models.Group(message_ids=[name], target_request="OIR-1", request_hint="Correction")], unresolved_message_ids=[]) for name in ("M1", "M2")]
		with patch("kunal_enterprises.integrations.order_intake_ai_budget.grouping_batches", return_value=(payloads, [])), patch.object(models, "_group_once", side_effect=responses):
			result = models.group(SimpleNamespace(), {}, {}, models.RequestBudget(4))
		self.assertEqual(result.groups, [])
		self.assertEqual(result.unresolved_message_ids, ["M1", "M2"])

	def test_oversized_combined_fresh_and_reference_context_retains_every_source(self):
		# Preparation accepts100 fresh sources plus20 manual and20 reply refs.
		# None may disappear when the indivisible context exceeds its token cap.
		rows = [dict(name=f'MSG-{index}', message='21317 mr 4') for index in range(140)]
		config = SimpleNamespace(max_input_tokens=100)
		with patch.object(models, 'make_model') as provider:
			result = models.group(config, dict(messages=rows, open_requests=[]), {}, models.RequestBudget(4))
		provider.assert_not_called()
		self.assertEqual(result.groups, [])
		self.assertEqual(result.unresolved_message_ids, [row['name'] for row in rows])
