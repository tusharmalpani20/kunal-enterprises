"""AI drafts account for evidence without duplicating or replacing human work."""
import json
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from kunal_enterprises.integrations import order_intake_ai as ai
from kunal_enterprises.integrations import order_intake_queue as queue
from kunal_enterprises.integrations.order_intake_ai_models import AIProblem, Extraction, Group, Grouping, Item


def extraction(source, **values):
	return Extraction(request_type="Order", summary="Possible laminate order", customer_text="Maa Annapurna",
		salesperson_text=None, delivery_address=None, delivery_contact_name=None, delivery_contact_number=None,
		items=[Item(original_text="21317 mr 4", source_message=source, quantity=4, unit="NOS",
			warehouse_text=None, warehouse_source_message=None, notes=None)], unresolved_questions=[], unresolved_message_ids=[], **values)


class TestOrderIntakeAI(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.account = frappe.get_doc(dict(doctype="WhatsApp Account", account_name="AI test " + uuid4().hex,
			phone_id=uuid4().hex, status="Active")).insert(ignore_permissions=True)
		self.sender = "919000000099"
		for field, value in dict(preparation_enabled=0, processing_enabled=0, lookback_minutes=120,
			deferred_retry_minutes="5,15,60", max_requests_per_job=10).items():
			frappe.db.set_single_value("Order Intake Settings", field, value)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def source(self, **values):
		return frappe.get_doc(dict(doctype="WhatsApp Message", type="Incoming", whatsapp_account=self.account.name,
			**{"from": self.sender}, message="21317 mr 4", message_id=uuid4().hex, content_type="text", **values)).insert(ignore_permissions=True)

	def prepare(self):
		result = queue.dispatch_pending(force=True, account=self.account.name, sender=self.sender, inline=True, maintain=False)
		self.assertEqual(result["ready"], 1)
		return frappe.get_all("WhatsApp Message", filters={"whatsapp_account": self.account.name, "intake_sender_key": self.sender, "intake_context_ids": ("is", "set")}, pluck="name", order_by="creation desc", limit_page_length=1)[0]

	def run_ai(self, anchor, grouping, extracted, side_effect=None):
		claim = ai._claim(anchor)
		self.assertEqual(claim["state"], "Queued")
		with patch.object(ai, "group", return_value=grouping, side_effect=side_effect), patch.object(ai, "extract", side_effect=extracted):
			return ai.process(anchor, claim["token"], release_transaction=False)

	def test_many_messages_one_draft_preserves_words_and_leaves_master_links_blank(self):
		first, second = self.source(), self.source()
		anchor = self.prepare()
		result = self.run_ai(anchor, Grouping(groups=[Group(request_hint="Test request", message_ids=[first.name, second.name], target_request=None)], unresolved_message_ids=[]), [extraction(first.name)])
		self.assertEqual(result["state"], "Drafted")
		doc = frappe.get_doc("Order Intake Request", result["created"][0])
		self.assertEqual({r.message for r in doc.source_messages}, {first.name, second.name})
		self.assertFalse(doc.customer); self.assertFalse(doc.items[0].item); self.assertFalse(doc.items[0].godown)
		self.assertEqual(doc.items[0].quantity, 4)
		self.assertIn("Maa Annapurna", doc.unresolved_questions)
		self.assertEqual(first.reload().intake_status, "New")
		self.assertEqual(first.intake_prepare_state, "Context Ready")
		self.assertEqual(second.reload().intake_ai_state, "Drafted")
		self.assertIn("ready for review", second.intake_ai_note)
		self.assertEqual(ai._claim(anchor, force=True)["state"], "Unchanged")

	def test_one_message_supports_two_orders_and_partial_coverage_stays_visible(self):
		source = self.source()
		result = self.run_ai(self.prepare(), Grouping(groups=[Group(request_hint="Test request", message_ids=[source.name], target_request=None), Group(request_hint="Test request", message_ids=[source.name], target_request=None)], unresolved_message_ids=[source.name]), [extraction(source.name), extraction(source.name)])
		self.assertEqual(len(result["created"]), 2)
		self.assertEqual(result["state"], "Unresolved")
		coverage = json.loads(source.reload().intake_ai_coverage)
		self.assertEqual(len(coverage["requests"]), 2)
		self.assertTrue(coverage["unresolved"])

	def test_ambiguous_only_messages_are_not_discarded_or_marked_processed(self):
		source = self.source()
		result = self.run_ai(self.prepare(), Grouping(groups=[], unresolved_message_ids=[source.name]), [])
		self.assertEqual(result["state"], "Unresolved")
		self.assertEqual(result["created"], [])
		self.assertTrue(json.loads(source.reload().intake_ai_coverage)["unresolved"])
		self.assertEqual(source.intake_status, "Needs Attention")

	def test_secondary_sources_get_their_own_coverage_state(self):
		first, second = self.source(), self.source()
		anchor = self.prepare()
		result = self.run_ai(anchor, Grouping(groups=[Group(request_hint="One order", message_ids=[first.name, second.name], target_request=None)], unresolved_message_ids=[first.name]), [extraction(first.name)])
		self.assertEqual(result['state'], 'Unresolved')
		self.assertEqual(second.reload().intake_ai_state, 'Drafted')
		self.assertFalse(json.loads(second.intake_ai_coverage)['unresolved'])

	def test_configured_company_and_godowns_reach_both_model_stages(self):
		frappe.db.set_single_value('Order Intake Settings', 'company_name', 'Receiving Company')
		frappe.db.set_single_value('Order Intake Settings', 'company_aliases', 'Receiving Co')
		source = self.source(); anchor = self.prepare(); claim = ai._claim(anchor)
		with patch.object(ai, 'group', return_value=Grouping(groups=[Group(request_hint='One order', message_ids=[source.name], target_request=None)], unresolved_message_ids=[])) as group_call, patch.object(ai, 'extract', return_value=extraction(source.name)) as extract_call:
			result = ai.process(anchor, claim['token'], release_transaction=False)
		self.assertEqual(result['state'], 'Drafted')
		context = group_call.call_args.args[1]['business_context']
		self.assertEqual(context['receiving_company'], 'Receiving Company')
		self.assertEqual(context['company_aliases'], ['Receiving Co'])
		self.assertEqual(extract_call.call_args.args[1]['business_context'], context)

	def test_company_context_changes_during_processing_do_not_publish_stale_drafts(self):
		source = self.source(); anchor = self.prepare()
		def changed_context(*args, **kwargs):
			frappe.db.set_single_value('Order Intake Settings', 'company_name', 'Changed Receiving Company')
			return Grouping(groups=[Group(request_hint='One order', message_ids=[source.name], target_request=None)], unresolved_message_ids=[])
		before = frappe.db.count('Order Intake Request')
		result = self.run_ai(anchor, None, [extraction(source.name)], side_effect=changed_context)
		self.assertEqual(result['state'], 'Retry')
		self.assertEqual(frappe.db.count('Order Intake Request'), before)

	def test_initial_suggestions_are_preserved_and_cannot_be_forged(self):
		source = self.source(); anchor = self.prepare()
		result = self.run_ai(anchor, Grouping(groups=[Group(request_hint='One order', message_ids=[source.name], target_request=None)], unresolved_message_ids=[]), [extraction(source.name)])
		doc = frappe.get_doc('Order Intake Request', result['created'][0])
		baseline = json.loads(doc.ai_initial_values)
		self.assertEqual(baseline['request_type'], 'Order')
		self.assertEqual(baseline['items'][0]['row_key'], doc.items[0].row_key)
		doc.request_type = 'Stock Inquiry'; doc.correction_reason = 'Availability question, not a booking'
		doc.save()
		self.assertEqual(json.loads(doc.ai_initial_values)['request_type'], 'Order')
		doc.ai_initial_values = '{}'
		with self.assertRaises(frappe.PermissionError):
			doc.save()

	def test_bounded_confirmed_learning_reaches_both_model_stages(self):
		source = self.source()
		frappe.db.set_value('WhatsApp Message', source.name, 'message', 'Please book 21317 MR 4')
		anchor = self.prepare()
		examples = [dict(kind='request_type', wording='Please book 21317 MR 4', confirmed='Order', previous='Stock Inquiry', reason='Explicit booking')]
		with patch.object(ai, 'confirmed_learning', return_value=examples):
			claim = ai._claim(anchor)
			with patch.object(ai, 'group', return_value=Grouping(groups=[Group(request_hint='One order', message_ids=[source.name], target_request=None)], unresolved_message_ids=[])) as group_call, patch.object(ai, 'extract', return_value=extraction(source.name)) as extract_call:
				result = ai.process(anchor, claim['token'], release_transaction=False)
		self.assertEqual(result['state'], 'Drafted')
		self.assertEqual(group_call.call_args.args[1]['confirmed_learning'], examples)
		self.assertEqual(extract_call.call_args.args[1]['confirmed_learning'], examples)

	def test_new_messages_create_proposals_without_overwriting_reviewed_fields(self):
		first = self.source()
		anchor = self.prepare()
		result = self.run_ai(anchor, Grouping(groups=[Group(request_hint="Test request", message_ids=[first.name], target_request=None)], unresolved_message_ids=[]), [extraction(first.name)])
		doc = frappe.get_doc("Order Intake Request", result["created"][0])
		doc.items[0].quantity = 7
		doc.review_notes = "Human checked seven"
		doc.save()
		second = self.source()
		anchor = self.prepare()
		result = self.run_ai(anchor, Grouping(groups=[Group(request_hint="Test request", message_ids=[second.name], target_request=doc.name)], unresolved_message_ids=[]), [extraction(second.name)])
		doc.reload()
		self.assertEqual(result["proposed"], [doc.name])
		self.assertEqual(doc.items[0].quantity, 7)
		self.assertEqual(doc.review_notes, "Human checked seven")
		self.assertTrue(json.loads(doc.proposed_updates)[0]["source_messages"])
		self.assertEqual(ai._claim(anchor, force=True)["state"], "Unchanged")

	def test_old_covered_source_is_replaced_by_open_request_context(self):
		first = self.source(); anchor = self.prepare()
		initial = self.run_ai(anchor, Grouping(groups=[Group(request_hint="Order", message_ids=[first.name], target_request=None)], unresolved_message_ids=[]), [extraction(first.name)])
		second = self.source(); anchor = self.prepare()
		snapshot = ai._snapshot(anchor)
		self.assertNotIn(first.name, snapshot['grouping_message_ids'])
		self.assertIn(first.name, snapshot['context_only_ids'])
		self.assertEqual([row['name'] for row in snapshot['open_requests']], initial['created'])
		result = self.run_ai(anchor, Grouping(groups=[Group(request_hint="Separate order", message_ids=[second.name], target_request=None)], unresolved_message_ids=[]), [extraction(second.name)])
		self.assertEqual(len(result["created"]), 1)
		self.assertEqual(result["proposed"], [])
		self.assertEqual(json.loads(first.reload().intake_ai_coverage)["requests"], initial["created"])

	def test_manual_terminal_source_recovery_does_not_reclaim_coverage_or_call_ai(self):
		first = self.source(); anchor = self.prepare()
		initial = self.run_ai(anchor, Grouping(groups=[Group(request_hint="Order", message_ids=[first.name], target_request=None)], unresolved_message_ids=[]), [extraction(first.name)])
		frappe.db.set_value('Order Intake Request', initial['created'][0], 'status', 'Resolved')
		before = frappe.db.get_value('WhatsApp Message', first.name, ['intake_ai_coverage', 'intake_status', 'intake_attention'], as_dict=True)
		# Recovering an explicit selection must retain access to its evidence,
		# but completing it earlier is not undone by the review action.
		queue.recover_selected(self.account.name, self.sender, [first.name])
		self.assertIn(first.name, ai._snapshot(first.name)['context_only_ids'])
		frappe.db.set_value('WhatsApp Message', first.name, 'intake_ai_prepared_digest', None)
		claim = ai._claim(first.name, force=True)
		self.assertEqual(claim['state'], 'Queued')
		with patch.object(ai, 'group') as group_call, patch.object(ai, 'extract') as extract_call:
			result = ai.process(first.name, claim['token'], release_transaction=False)
		group_call.assert_not_called(); extract_call.assert_not_called()
		self.assertEqual(result['created'], [])
		self.assertEqual(result['unresolved'], [])
		after = frappe.db.get_value('WhatsApp Message', first.name, ['intake_ai_coverage', 'intake_status', 'intake_attention'], as_dict=True)
		self.assertEqual(before, after)


	def test_provider_outage_defers_and_credentials_stop_without_exposing_error(self):
		for transient, expected in ((True, "Retry"), (False, "Needs Attention")):
			source = self.source(); anchor = self.prepare()
			claim = ai._claim(anchor, force=True)
			with patch.object(ai, "group", side_effect=AIProblem("Fixed safe explanation", transient)):
				result = ai.process(anchor, claim["token"], release_transaction=False)
			self.assertEqual(result["state"], expected)
			self.assertFalse(json.loads(source.reload().intake_ai_coverage or "{}"))
			frappe.db.set_value("WhatsApp Message", anchor, "intake_ai_retry_at", None)

	def test_changed_source_during_provider_call_cannot_publish(self):
		source = self.source(); anchor = self.prepare()
		def changed(*args):
			frappe.db.set_value("WhatsApp Message", source.name, "message", "Changed source text")
			return Grouping(groups=[Group(request_hint="Test request", message_ids=[source.name], target_request=None)], unresolved_message_ids=[])
		result = self.run_ai(anchor, None, [extraction(source.name)], changed)
		self.assertEqual(result["state"], "Retry")
		self.assertIn("changed", result["note"])

	def test_stale_delivery_and_expired_lease_create_no_drafts(self):
		source = self.source(); anchor = self.prepare(); claim = ai._claim(anchor)
		self.assertEqual(ai.process(anchor, "wrong-token", release_transaction=False)["state"], "Stale")
		frappe.db.set_value("WhatsApp Message", anchor, "intake_ai_lease_until", add_to_date(now_datetime(), minutes=-1))
		self.assertEqual(ai.process(anchor, claim["token"], release_transaction=False)["state"], "Retry")
		self.assertFalse(source.reload().intake_ai_coverage)

	def test_public_save_cannot_forge_proposed_updates(self):
		doc = frappe.get_doc(dict(doctype="Order Intake Request", request_type="Unclear", status="Pending Review", proposed_updates='[{"fake":true}]'))
		with self.assertRaises(frappe.PermissionError):
			doc.insert()

	def test_original_attention_notes_survive_ai_publication(self):
		source = self.source(); frappe.db.set_value("WhatsApp Message", source.name, "intake_attention", "Original download problem")
		self.run_ai(self.prepare(), Grouping(groups=[Group(request_hint="Test request", message_ids=[source.name], target_request=None)], unresolved_message_ids=[]), [extraction(source.name)])
		self.assertEqual(source.reload().intake_attention, "Original download problem")

	def test_processing_switch_off_does_not_queue_automatic_work(self):
		self.source(); self.prepare()
		self.assertEqual(ai.dispatch()["state"], "Disabled")


	def test_publication_failure_rolls_back_all_drafts_and_coverage(self):
		from kunal_enterprises.kunal_enterprises.doctype.order_intake_request.order_intake_request import OrderIntakeRequest
		source = self.source(); anchor = self.prepare(); claim = ai._claim(anchor)
		before = frappe.db.count("Order Intake Request")
		original = OrderIntakeRequest.insert
		calls = []
		def insert(doc, *args, **kwargs):
			calls.append(doc)
			if len(calls) == 2:
				raise ValueError("synthetic second-draft failure")
			return original(doc, *args, **kwargs)
		grouping = Grouping(groups=[Group(request_hint="Test request", message_ids=[source.name], target_request=None), Group(request_hint="Test request", message_ids=[source.name], target_request=None)], unresolved_message_ids=[])
		with patch.object(ai, "group", return_value=grouping), patch.object(ai, "extract", side_effect=[extraction(source.name), extraction(source.name)]), patch.object(OrderIntakeRequest, "insert", insert):
			result = ai.process(anchor, claim["token"], release_transaction=False)
		self.assertEqual(result["state"], "Needs Attention")
		self.assertEqual(frappe.db.count("Order Intake Request"), before)
		self.assertFalse(source.reload().intake_ai_coverage)

	def test_dispatch_isolates_a_broken_context_from_another_chat(self):
		self.source(); first = self.prepare()
		self.sender = "919000000098"
		self.source(); second = self.prepare()
		frappe.db.set_single_value("Order Intake Settings", "processing_enabled", 1)
		original = ai._claim
		def claim(name, **kwargs):
			if name == first:
				raise AIProblem("Synthetic bad context")
			return original(name, **kwargs)
		with patch.object(ai, "_claim", side_effect=claim):
			result = ai.dispatch()
		self.assertGreaterEqual(result["queued"], 1)
		self.assertEqual(frappe.db.get_value("WhatsApp Message", second, "intake_ai_state"), "Queued")
		self.assertEqual(frappe.db.get_value("WhatsApp Message", first, "intake_ai_state"), "Needs Attention")

	def test_completed_contexts_do_not_starve_pending_work(self):
		for _ in range(21):
			old = self.source()
			frappe.db.set_value("WhatsApp Message", old.name, dict(intake_prepare_state="Context Ready", intake_context_ids='{"complete": true}',
				intake_context_digest="already-done", intake_ai_prepared_digest="already-done", intake_ai_state="Drafted", intake_prepared_at=add_to_date(now_datetime(), minutes=-10)))
		self.sender = "919000000097"
		self.source(); anchor = self.prepare()
		frappe.db.set_single_value("Order Intake Settings", "processing_enabled", 1)
		result = ai.dispatch()
		self.assertGreaterEqual(result["queued"], 1)
		self.assertIn(anchor, [row["anchor"] for row in result["results"]])
		self.assertFalse(any(row.get("state") == "Unchanged" for row in result["results"]))


	def test_identical_values_do_not_create_proposed_updates_on_later_windows(self):
		first = self.source(); anchor = self.prepare()
		created = self.run_ai(anchor, Grouping(groups=[Group(request_hint="Test request", message_ids=[first.name], target_request=None)], unresolved_message_ids=[]), [extraction(first.name)])["created"][0]
		late_ids = []
		for _ in range(2):
			late = self.source(); late_ids.append(late.name); anchor = self.prepare()
			self.run_ai(anchor, Grouping(groups=[Group(request_hint="Test request", message_ids=[late.name], target_request=created)], unresolved_message_ids=[]), [extraction(late.name)])
		updates = json.loads(frappe.get_doc("Order Intake Request", created).proposed_updates or "[]")
		self.assertEqual(updates, [])

	def test_manual_review_context_references_receive_their_own_coverage(self):
		older = self.source()
		frappe.db.set_value("WhatsApp Message", older.name, dict(intake_prepare_state="Needs Attention", intake_status="Needs Attention"))
		current = self.source(); anchor = self.prepare()
		result = self.run_ai(anchor, Grouping(groups=[Group(request_hint="Test request", message_ids=[older.name, current.name], target_request=None)],
			unresolved_message_ids=[]), [extraction(older.name)])
		coverage = json.loads(older.reload().intake_ai_coverage or "{}")
		self.assertEqual(coverage.get("requests"), result["created"])

	def test_deferred_provider_retries_eventually_require_manual_attention(self):
		source = self.source(); anchor = self.prepare()
		for attempt in range(4):
			claim = ai._claim(anchor, force=True)
			with patch.object(ai, "group", side_effect=AIProblem("Provider unavailable", retry=True)):
				result = ai.process(anchor, claim["token"], release_transaction=False)
			self.assertEqual(result["state"], "Needs Attention" if attempt == 3 else "Retry")
		self.assertEqual(source.reload().intake_ai_attempts, 4)
		self.assertFalse(source.intake_ai_retry_at)
		self.assertEqual(source.intake_status, "Needs Attention")

	def test_coordinator_cannot_start_provider_calls(self):
		from kunal_enterprises.api.order_intake_ai import process_sender
		from kunal_enterprises.tests.test_foundation import TestOrderSubmission as Helpers
		user = Helpers._create_role_user(self, "ai-coordinator-" + uuid4().hex + "@example.com", "Order Coordinator")
		frappe.set_user(user.name)
		with self.assertRaises(frappe.PermissionError), patch.object(ai, "dispatch") as dispatch:
			process_sender(self.account.name, self.sender)
		dispatch.assert_not_called()

	def test_provider_payloads_omit_raw_media_credentials_but_keep_local_snapshot(self):
		source = self.source()
		body = dict(id='MEDIA', mime_type='image/jpeg', url='https://lookaside.fbsbx.com/media?hash=private-download-signature')
		frappe.db.set_value('WhatsApp Message', source.name, dict(content_type='image', intake_original_type='image',
			message=json.dumps(body), intake_raw_payload=json.dumps(dict(message=dict(type='image', image=body)))), update_modified=False)
		anchor = self.prepare()
		self.assertIn('private-download-signature', ai._snapshot(anchor)['messages'][0]['intake_raw_payload'])
		seen = []
		def grouping(config, payload, media, budget):
			seen.append('group')
			self.assertNotIn('private-download-signature', json.dumps(payload, default=str))
			self.assertEqual(payload['messages'][0]['message'], '')
			return Grouping(groups=[Group(message_ids=[source.name], target_request=None, request_hint='Unreadable image')], unresolved_message_ids=[source.name])
		def extracting(config, payload, media, budget):
			seen.append('extract')
			self.assertNotIn('private-download-signature', json.dumps(payload, default=str))
			self.assertNotIn('intake_raw_payload', payload['messages'][0])
			return extraction(source.name)
		self.run_ai(anchor, None, extracting, side_effect=grouping)
		self.assertEqual(seen, ['group', 'extract'])

	def test_pdf_page_count_publishes_without_changing_snapshot_and_preserves_review_notes(self):
		from io import BytesIO
		from pypdf import PdfWriter
		source = self.source()
		writer = PdfWriter()
		for _ in range(2):
			writer.add_blank_page(width=100, height=100)
		stream = BytesIO(); writer.write(stream)
		file = frappe.get_doc(dict(doctype='File', file_name='purchase-order-'+uuid4().hex+'.pdf',
			is_private=1, attached_to_doctype='WhatsApp Message', attached_to_name=source.name,
			attached_to_field='attach', content=stream.getvalue())).insert(ignore_permissions=True)
		frappe.db.set_value('WhatsApp Message', source.name, dict(attach=file.file_url, content_type='document',
			intake_original_type='document'), update_modified=False)
		frappe.db.set_single_value('Order Intake Settings', 'pdf_page_limit', 1)
		anchor = self.prepare()
		result = self.run_ai(anchor, Grouping(groups=[Group(message_ids=[source.name], target_request=None,
			request_hint='Laminate purchase order')], unresolved_message_ids=[]), [extraction(source.name)])
		self.assertEqual(result['state'], 'Unresolved')
		doc = frappe.get_doc('Order Intake Request', result['created'][0])
		self.assertEqual(doc.attachments[0].page_count, 2)
		self.assertEqual(doc.attachments[0].review_status, 'Needs Manual Review')
		doc.attachments[0].page_count = None
		doc.attachments[0].notes = 'Keep the original review note'
		doc.save()
		late = self.source(); anchor = self.prepare()
		result = self.run_ai(anchor, Grouping(groups=[Group(message_ids=[source.name, late.name], target_request=doc.name,
			request_hint='Continue this purchase order')], unresolved_message_ids=[]), [extraction(source.name)])
		self.assertEqual(result['proposed'], [doc.name])
		doc.reload()
		self.assertEqual(len(doc.attachments), 1)
		self.assertEqual(doc.attachments[0].page_count, 2)
		self.assertEqual(doc.attachments[0].notes, 'Keep the original review note')

	def test_published_unknown_quantity_keeps_explicit_unknown_state_and_specific_reason(self):
		source = self.source(); value = extraction(source.name)
		value.items[0].quantity = None
		value.unresolved_message_ids = [source.name]
		value.unresolved_questions = ['For item 21317 MR, should the quantity be 4 or 2?']
		result = self.run_ai(self.prepare(), Grouping(groups=[Group(message_ids=[source.name], target_request=None,
			request_hint='Unclear quantity')], unresolved_message_ids=[source.name]), [value])
		doc = frappe.get_doc('Order Intake Request', result['created'][0])
		self.assertTrue(doc.items[0].quantity_unknown)
		self.assertIn('4 or 2', source.reload().intake_attention)
		self.assertNotIn('Some content remains unresolved', source.intake_attention)

	def test_partial_proposal_retains_earlier_item_without_inferred_reassignment(self):
		first = self.source(); initial = extraction(first.name)
		result = self.run_ai(self.prepare(), Grouping(groups=[Group(message_ids=[first.name], target_request=None,
			request_hint='Original order')], unresolved_message_ids=[]), [initial])
		doc = frappe.get_doc('Order Intake Request', result['created'][0])
		late = self.source(); value = extraction(late.name)
		value.items[0].original_text = '21022 SF'
		value.summary = 'The earlier item was moved to another customer.'
		result = self.run_ai(self.prepare(), Grouping(groups=[Group(message_ids=[late.name],
			target_request=doc.name,request_hint='Partial update')],unresolved_message_ids=[]), [value])
		proposal = json.loads(doc.reload().proposed_updates)[0]
		self.assertEqual(len(proposal['items']),2)
		self.assertTrue(proposal['items'][1]['retained'])
		self.assertNotIn('moved to another customer',proposal['summary'])
		self.assertTrue(proposal['review_warnings'])
		self.assertEqual(doc.items[0].original_text,initial.items[0].original_text)

	def test_rephrased_unchanged_values_link_new_source_without_review_blocker(self):
		first = self.source(); anchor = self.prepare()
		created = self.run_ai(anchor, Grouping(groups=[Group(request_hint="Order", message_ids=[first.name], target_request=None)], unresolved_message_ids=[]), [extraction(first.name)])["created"][0]
		late = self.source(); anchor = self.prepare()
		updated = extraction(late.name)
		updated.summary = "The same order, described differently."
		updated.items[0].unit = "sheets"
		self.run_ai(anchor, Grouping(groups=[Group(request_hint="Order", message_ids=[late.name], target_request=created)], unresolved_message_ids=[]), [updated])
		doc = frappe.get_doc("Order Intake Request", created)
		self.assertEqual({row.message for row in doc.source_messages}, {first.name, late.name})
		self.assertEqual(json.loads(doc.proposed_updates or "[]"), [])
		self.assertEqual(doc.items[0].quantity, 4)

	def test_contact_card_keeps_each_number_as_a_reviewable_reference(self):
		from kunal_enterprises.integrations.order_intake_ai_drafts import attachments
		refs = attachments([dict(name="contact-source", intake_original_type="contacts", intake_raw_payload=json.dumps(dict(message=dict(contacts=[dict(name=dict(formatted_name="Amol Sawrikar"), phones=[dict(phone="+91 99854 45566"), dict(phone="+91 99854 45567")])]))))], {})
		self.assertEqual(len(refs), 2)
		self.assertEqual({row['contact_number'] for row in refs}, {"+91 99854 45566", "+91 99854 45567"})
		self.assertTrue(all(row['reference_type'] == 'Contact' and row['review_status'] == 'Not Reviewed' for row in refs))

	def test_anchor_status_is_its_own_coverage_not_chat_aggregate(self):
		first, second = self.source(), self.source()
		anchor = self.prepare()
		other = second.name if anchor == first.name else first.name
		result = self.run_ai(anchor, Grouping(groups=[Group(request_hint='One order', message_ids=[anchor], target_request=None)], unresolved_message_ids=[other]), [extraction(anchor)])
		self.assertEqual(result['state'], 'Unresolved')
		self.assertEqual(frappe.get_value('WhatsApp Message', anchor, 'intake_ai_state'), 'Drafted')
		self.assertEqual(frappe.get_value('WhatsApp Message', other, 'intake_ai_state'), 'Unresolved')

	def test_continuation_gets_target_evidence_only_at_extraction(self):
		first = self.source()
		initial = self.run_ai(self.prepare(), Grouping(groups=[Group(request_hint='Initial order', message_ids=[first.name], target_request=None)], unresolved_message_ids=[]), [extraction(first.name)])
		draft = initial['created'][0]
		old_coverage = first.reload().intake_ai_coverage
		second = self.source()
		anchor = self.prepare(); claim = ai._claim(anchor)
		with patch.object(ai, 'group', return_value=Grouping(groups=[Group(request_hint='Continue this order', message_ids=[second.name], target_request=draft)], unresolved_message_ids=[])) as grouping_call, patch.object(ai, 'extract', return_value=extraction(first.name)) as extract_call:
			result = ai.process(anchor, claim['token'], release_transaction=False)
		self.assertEqual(result['state'], 'Drafted')
		self.assertEqual([row['name'] for row in grouping_call.call_args.args[1]['messages']], [second.name])
		self.assertEqual({row['name'] for row in extract_call.call_args.args[1]['messages']}, {first.name, second.name})
		self.assertEqual(first.reload().intake_ai_coverage, old_coverage)

	def test_oversized_extraction_does_not_discard_other_independent_request(self):
		from kunal_enterprises.integrations.order_intake_ai_models import InputTooLarge
		first, second = self.source(), self.source()
		result = self.run_ai(self.prepare(), Grouping(groups=[
			Group(request_hint='Too large order', message_ids=[first.name], target_request=None),
			Group(request_hint='Small independent order', message_ids=[second.name], target_request=None),
		], unresolved_message_ids=[]), [InputTooLarge(21000,20000), extraction(second.name)])
		self.assertEqual(result['state'], 'Unresolved')
		self.assertEqual(len(result['created']), 1)
		self.assertIn(first.name, result['unresolved'])
		self.assertNotIn(second.name, result['unresolved'])
		self.assertIn('input token estimate', first.reload().intake_attention)

	def test_large_old_history_does_not_block_new_independent_order(self):
		first = self.source()
		initial = self.run_ai(self.prepare(), Grouping(groups=[Group(request_hint='Initial order', message_ids=[first.name], target_request=None)], unresolved_message_ids=[]), [extraction(first.name)])
		second = self.source(); anchor = self.prepare()
		with patch.object(ai, 'MAX_HISTORY_MESSAGES', 0):
			snapshot = ai._snapshot(anchor)
			self.assertTrue(snapshot['open_requests'][0]['evidence_needs_manual_review'])
			self.assertNotIn(first.name, [row['name'] for row in snapshot['messages']])
			result = self.run_ai(anchor, Grouping(groups=[Group(request_hint='Separate order', message_ids=[second.name], target_request=None)], unresolved_message_ids=[]), [extraction(second.name)])
		self.assertEqual(result['state'], 'Drafted')
		self.assertEqual(len(result['created']), 1)
		self.assertNotEqual(initial['created'], result['created'])
