"""Master lookup publication preserves edits, source details and access boundaries."""
import json
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.api.order_intake_matching import match_request
from kunal_enterprises.integrations.order_intake_match_requests import match_document


class TestOrderIntakeMatchRequests(FrappeTestCase):
	def setUp(self):
		frappe.set_user('Administrator')

	def tearDown(self):
		frappe.set_user('Administrator'); frappe.db.rollback()

	def draft(self):
		return frappe.get_doc(dict(doctype='Order Intake Request', customer_text='Synthetic Customer',
			items=[dict(original_text='Synthetic item', warehouse_text='Synthetic warehouse', quantity=4, unit='NOS')])).insert()

	def test_exact_master_matching_fills_blank_fields_without_creating_learning(self):
		doc = self.draft()
		# Use real master values for existence validation; mocked search only
		# controls candidate choice, not persistence or document authorization.
		godown = frappe.get_doc(dict(doctype='Tally Godown', godown_name='Step5 '+uuid4().hex)).insert()
		def search(kind, text, limit=5):
			return dict(candidates=[dict(name=godown.name,label=godown.godown_name,score=100,reason='Exact')] if kind=='godown' else [],
				selected=godown.name if kind=='godown' else None, overflow=False)
		before = frappe.db.count('Order Intake Match Evidence')
		with patch('kunal_enterprises.integrations.order_intake_match_requests.search_candidates', side_effect=search):
			result = match_request(doc.name, str(doc.modified))
		doc.reload()
		self.assertEqual(result['selected_count'],1)
		self.assertEqual(doc.items[0].godown,godown.name)
		self.assertEqual(doc.items[0].quantity,4)
		self.assertEqual(doc.items[0].unit,'NOS')
		self.assertEqual(frappe.db.count('Order Intake Match Evidence'), before)
		self.assertEqual(json.loads(doc.matching_json)['items'][0]['row_key'],doc.items[0].row_key)

	def test_matching_never_replaces_existing_selection_or_item_wording(self):
		doc = self.draft()
		first = frappe.get_doc(dict(doctype='Tally Godown',godown_name='Step5 '+uuid4().hex)).insert()
		other = frappe.get_doc(dict(doctype='Tally Godown',godown_name='Step5 '+uuid4().hex)).insert()
		doc.items[0].godown=first.name; doc.save()
		with patch('kunal_enterprises.integrations.order_intake_match_requests.search_candidates',
			return_value=dict(candidates=[dict(name=other.name,label=other.name,score=100,reason='Exact')],selected=other.name,overflow=False)):
			match_document(doc)
		self.assertEqual(doc.items[0].godown,first.name)
		self.assertEqual(doc.items[0].original_text,'Synthetic item')

	def test_stale_closed_and_unprivileged_requests_cannot_be_matched(self):
		doc=self.draft()
		with self.assertRaises(frappe.TimestampMismatchError):
			match_request(doc.name,'stale')
		doc.status='Dismissed'; doc.save()
		with self.assertRaises(frappe.ValidationError):
			match_request(doc.name,str(doc.modified))
		frappe.set_user('Guest')
		with self.assertRaises(frappe.PermissionError):
			match_request(doc.name,str(doc.modified))

	def test_matching_snapshot_cannot_be_forged_by_a_reviewer(self):
		doc=self.draft(); doc.matching_json='{"customer":{"selected":"invented"}}'
		with self.assertRaises(frappe.PermissionError):
			doc.save()

	def test_sender_salesperson_is_not_assumed_to_be_the_customer(self):
		doc=self.draft(); doc.customer_text=''; doc.sender_number='919000000098'
		with patch('kunal_enterprises.integrations.order_intake_match_requests._identity',return_value=dict(sales_employee='SALES-SYNTHETIC')), patch(
			'kunal_enterprises.integrations.order_intake_match_requests.search_candidates',return_value=dict(candidates=[],selected=None,overflow=False)):
			match_document(doc)
		self.assertFalse(doc.customer)
		self.assertEqual(doc.sales_employee,'SALES-SYNTHETIC')


	def test_matching_failure_retains_draft_and_removes_partial_suggestions(self):
		from kunal_enterprises.integrations.order_intake_match_requests import match_new_document
		doc = self.draft()
		def failed(doc):
			doc.customer = 'partial-guess'
			doc.items[0].item = 'partial-item'
			raise ValueError('synthetic master search failure')
		with patch('kunal_enterprises.integrations.order_intake_match_requests.match_document',side_effect=failed):
			result = match_new_document(doc)
		doc.save()
		self.assertEqual(result['state'],'Needs Review')
		self.assertFalse(doc.customer); self.assertFalse(doc.items[0].item)
		self.assertEqual(doc.items[0].quantity,4)
		self.assertIn('Master matching was unavailable',doc.unresolved_questions)

	def test_long_wording_is_retained_without_blocking_draft_matching(self):
		doc = self.draft(); doc.items[0].original_text = 'long source wording ' * 30
		match_document(doc)
		result = json.loads(doc.matching_json)['items'][0]['item']
		self.assertTrue(result['overflow']); self.assertFalse(result['selected'])
		self.assertEqual(result['text'],doc.items[0].original_text)

	def test_conflicting_exact_master_and_learned_alias_require_review(self):
		from kunal_enterprises.integrations.order_intake_match_requests import _search
		doc = self.draft(); doc.whatsapp_account='synthetic'; doc.sender_number='919000000098'
		def result(name):
			return dict(selected=name,candidates=[dict(name=name,label=name,score=100,reason='Exact')],overflow=False)
		with patch('kunal_enterprises.integrations.order_intake_match_requests.search_candidates',return_value=result('new-master')), patch(
			'kunal_enterprises.integrations.order_intake_learning.lookup_confirmed',return_value=result('old-confirmed')):
			found = _search('customer','Synthetic Customer',doc)
		self.assertFalse(found['selected'])
		self.assertEqual({r['name'] for r in found['candidates']},{'new-master','old-confirmed'})


	def test_source_edits_invalidate_saved_matching_snapshot_and_score(self):
		doc = self.draft()
		with patch('kunal_enterprises.integrations.order_intake_match_requests.search_candidates',
			return_value=dict(candidates=[],selected=None,overflow=False)):
			match_request(doc.name,str(doc.modified))
		doc.reload()
		self.assertEqual(json.loads(doc.matching_json)['context']['items'][0]['original_text'],'Synthetic item')
		doc.items[0].original_text='Changed product wording'; doc.items[0].match_score=90
		doc.save()
		self.assertFalse(doc.matching_json)
		self.assertEqual(doc.items[0].match_score,0)

	def test_confirmed_alias_overrides_fuzzy_catalogue_choice(self):
		from kunal_enterprises.integrations.order_intake_match_requests import _search
		doc=self.draft();doc.whatsapp_account='synthetic';doc.sender_number='919000000098'
		with patch('kunal_enterprises.integrations.order_intake_match_requests.search_candidates',return_value=dict(
			selected='fuzzy',candidates=[dict(name='fuzzy',label='fuzzy',score=92,reason='Closest wording')],overflow=False)), patch(
			'kunal_enterprises.integrations.order_intake_learning.lookup_confirmed',return_value=dict(
			selected='confirmed',candidates=[dict(name='confirmed',label='confirmed',score=100,reason='Previously confirmed')],overflow=False)):
			self.assertEqual(_search('customer','Synthetic Customer',doc)['selected'],'confirmed')

	def test_saved_manual_clear_remains_blank_when_matching_again(self):
		doc=self.draft()
		godown=frappe.get_doc(dict(doctype='Tally Godown',godown_name='Manual clear '+uuid4().hex)).insert()
		doc.items[0].godown=godown.name;doc.save()
		doc.items[0].godown=None;doc.save()
		with patch('kunal_enterprises.integrations.order_intake_match_requests.search_candidates',return_value=dict(
			selected=godown.name,candidates=[dict(name=godown.name,label=godown.name,score=100,reason='Exact')],overflow=False)):
			match_document(doc)
		self.assertFalse(doc.items[0].godown)
		self.assertIn('godown:'+doc.items[0].row_key,json.loads(doc.manual_match_fields))

	def test_manual_match_protection_cannot_be_forged_or_removed_through_save(self):
		doc=self.draft();doc.manual_match_fields='["customer"]'
		with self.assertRaises(frappe.PermissionError):
			doc.save()

	def test_long_confirmed_alias_is_used_even_when_catalogue_search_is_bounded(self):
		from kunal_enterprises.integrations.order_intake_match_requests import _search
		doc=self.draft();doc.whatsapp_account='synthetic';doc.sender_number='919000000098'
		with patch('kunal_enterprises.integrations.order_intake_learning.lookup_confirmed',return_value=dict(
			selected='confirmed',candidates=[dict(name='confirmed',label='confirmed',score=100,reason='Previously confirmed')],overflow=False)):
			self.assertEqual(_search('customer','Long confirmed wording '*20,doc)['selected'],'confirmed')

	def test_warehouse_options_do_not_split_quantities_or_replace_manual_dispatch(self):
		first = frappe.get_doc(dict(doctype='Tally Godown', godown_name='Zulu Depot '+uuid4().hex)).insert()
		second = frappe.get_doc(dict(doctype='Tally Godown', godown_name='Alpha Depot '+uuid4().hex)).insert()
		wording = first.name+' / '+second.name
		doc = frappe.get_doc(dict(doctype='Order Intake Request', items=[
			dict(original_text='Unknown Material A', warehouse_text=wording, quantity=4),
			dict(original_text='Unknown Material B', warehouse_text=wording, quantity=7)])).insert()
		before = frappe.db.count('Order Intake Match Evidence')
		match_request(doc.name, str(doc.modified)); doc.reload()
		self.assertEqual([row.godown for row in doc.items], [first.name, first.name])
		self.assertEqual([row.quantity for row in doc.items], [4,7])
		self.assertEqual([row.warehouse_text for row in doc.items], [wording, wording])
		doc.items[1].godown=second.name; doc.save()
		match_request(doc.name,str(doc.modified)); doc.reload()
		self.assertEqual([row.godown for row in doc.items], [first.name, second.name])
		self.assertEqual([row.quantity for row in doc.items], [4,7])
		self.assertEqual(frappe.db.count('Order Intake Match Evidence'), before)
