"""Unchanged business values must not manufacture another review blocker."""
from unittest import TestCase

from kunal_enterprises.integrations.order_intake_ai_updates import (
	proposal_changes_values, proposal_signature, prune_noop_updates, reference_key,
)


class Values(dict):
	__getattr__ = dict.get


class TestSemanticUpdates(TestCase):
	def draft(self):
		return Values(request_type='Order',customer_text='APARNA ENTERPRISES LTD - JUBILEE HILLS',
			customer='CUST',salesperson_text='Tushar Malpani',delivery_contact_name='Amol',
			delivery_contact_number='+91 99854 45566',source_messages=[Values(message='FIRST'),Values(message='CORRECTION')],
			items=[Values(original_text='21022 SF',item='21022 SF',quantity=2,warehouse_text='Kukatpally',notes=None),
				Values(original_text='21069 SF',item='21069 SF',quantity=5,warehouse_text='Kukatpally',notes='Corrected from 3 sheets to 5 sheets by message CORRECTION.')], attachments=[])

	def proposal(self):
		return dict(request_type='Order',customer_text='aparna enterprises ltd - jubilee hills.',salesperson_text='Tushar Malpani',
			items=[dict(original_text='21022 SF',quantity=2,unit='NOS',warehouse_text='@Kukatpally Godown'),
				dict(original_text='21069 SF',quantity=5,warehouse_text='Kukatpally',notes='Quantity corrected from 3 sheets to 5 sheets in CORRECTION.')],
			delivery_contact_name='Amol',delivery_contact_number='+919985445566',source_messages=['FIRST','CORRECTION'],summary='Different cosmetic summary')

	def test_already_applied_quantity_correction_is_noop_despite_summary_and_note_wording(self):
		self.assertFalse(proposal_changes_values(self.proposal(),self.draft()))

	def test_real_quantity_price_and_customer_changes_still_require_review(self):
		for field,value in [('quantity',6),('notes','Additional discount 45%')]:
			p=self.proposal();p['items'][1][field]=value
			self.assertTrue(proposal_changes_values(p,self.draft()))
		p=self.proposal();p['customer_text']='Another buyer'
		self.assertTrue(proposal_changes_values(p,self.draft()))

	def test_new_delivery_contact_and_unreviewed_location_still_require_review(self):
		p=self.proposal();p['delivery_contact_number']='+919111111111'
		self.assertTrue(proposal_changes_values(p,self.draft()))
		p=self.proposal();p['new_references']=[dict(reference_type='Location',source_message='PIN',latitude=0,longitude=0)]
		doc=self.draft();self.assertTrue(proposal_changes_values(p,doc))
		doc['attachments']=[Values(**p['new_references'][0],review_status='Not Reviewed')]
		self.assertTrue(proposal_changes_values(p,doc))
		doc['attachments'][0]['review_status']='Reviewed'
		self.assertFalse(proposal_changes_values(p,doc))

	def test_cleanup_keeps_real_edits_and_reviewed_history_without_claiming_human_review(self):
		noop=self.proposal();real=self.proposal();real['items'][0]['quantity']=4
		reviewed=self.proposal();reviewed['reviewed_at']='previous review'
		kept,removed=prune_noop_updates(self.draft(),[noop,real,reviewed])
		self.assertEqual(removed,1);self.assertEqual(kept,[real,reviewed])
		self.assertNotIn('reviewed_at',noop)

	def test_equivalent_proposals_ignore_summary_unit_and_source_id_changes(self):
		one=self.proposal();two=self.proposal();two['summary']='Fresh phrasing';two['source_messages']=['LATER'];two['items'][0]['unit']='sheets';two['items'][0]['quantity']=2.0;two['delivery_contact_number']='+91 99854 45566'
		self.assertEqual(proposal_signature(one),proposal_signature(two))

	def test_contact_keys_keep_each_number_and_zero_coordinates_are_real_locations(self):
		one=dict(reference_type='Contact',source_message='CARD',contact_name='Amol',contact_number='+91 123')
		two={**one,'contact_number':'+91 456'}
		self.assertNotEqual(reference_key(one),reference_key(two))
		self.assertEqual(reference_key(dict(reference_type='Location',latitude=0,longitude=0)),reference_key(dict(reference_type='Location',latitude=0.0,longitude=0.0)))

	def test_retained_row_boilerplate_does_not_hide_added_business_instructions(self):
		p = self.proposal()
		p['items'][0]['notes'] = 'Existing item retained. Remove it only after checking an explicit removal instruction. Apply 45% discount.'
		self.assertTrue(proposal_changes_values(p, self.draft()))
		p['items'][0]['notes'] = 'Existing item retained. Remove it only after checking an explicit removal instruction.'
		self.assertFalse(proposal_changes_values(p, self.draft()))

	def test_quantity_correction_with_new_urgency_is_not_cosmetic(self):
		p = self.proposal()
		p['items'][1]['notes'] = 'Corrected from 3 to 5 urgent'
		self.assertTrue(proposal_changes_values(p, self.draft()))
