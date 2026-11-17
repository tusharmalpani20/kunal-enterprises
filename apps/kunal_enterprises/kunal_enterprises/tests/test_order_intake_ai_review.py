import unittest
from types import SimpleNamespace
from kunal_enterprises.integrations.order_intake_ai_review import preserve_existing_items, review_questions, current_review_questions

class Row(dict):
 __getattr__=dict.get

class TestIntakeReview(unittest.TestCase):
 def row(self,**values):return Row(original_text='21022 SF',item='21022 SF',quantity=2,unit='sheets',godown='Goshamahal',warehouse_text='Goshamahal',source_message='FIRST',**values)
 def test_partial_update_keeps_old_item_and_does_not_repeat_invented_reassignment(self):
  doc=SimpleNamespace(items=[self.row()]);proposal={'summary':'Moved item to another party','items':[{'original_text':'21317 MR+','quantity':4}]}
  result=preserve_existing_items(proposal,doc)
  self.assertEqual(len(result['items']),2);self.assertEqual(result['items'][1]['quantity'],2)
  self.assertTrue(result['items'][1]['retained']);self.assertNotIn('Moved item',result['summary']);self.assertTrue(result['review_warnings'])
 def test_case_or_selected_catalogue_name_does_not_duplicate_existing_row(self):
  doc=SimpleNamespace(items=[self.row()]);p={'summary':'Additional details','items':[{'original_text':'21022 sf','quantity':2}]}
  self.assertEqual(len(preserve_existing_items(p,doc)['items']),1)
 def test_exact_selected_identities_do_not_get_boilerplate_confirmation_questions(self):
  doc=SimpleNamespace(customer='C',customer_text='Party',sales_employee='S',salesperson_text='Suraj',items=[self.row()])
  self.assertEqual(review_questions(doc,[]),[])
 def test_unknowns_have_specific_questions_without_inventing_quantity(self):
  row=self.row(quantity_unknown=1);row.item=None;row.godown=None
  doc=SimpleNamespace(customer=None,customer_text='Maa Annapurna',sales_employee='S',salesperson_text='Suraj',items=[row])
  questions=review_questions(doc,['Is this a new order?'])
  self.assertIn('Is this a new order?',questions);self.assertTrue(any('quantity' in q for q in questions));self.assertTrue(any('variant' in q for q in questions));self.assertTrue(any('warehouse' in q for q in questions));self.assertFalse(any('Suraj' in q for q in questions))

class TestReviewAttention(unittest.TestCase):
 def test_specific_attention_clears_after_resolution_without_clearing_media_warning(self):
  from kunal_enterprises.integrations.order_intake_ai_state import coverage_attention
  first=coverage_attention({},True,['Quantity could be 4 or 2.'])
  self.assertIn('Quantity could be 4 or 2.',first['intake_attention'])
  self.assertNotIn('Some content remains',first['intake_attention'])
  first.update(intake_attention=first['intake_attention']+'\nAttachment unavailable',intake_status='Needs Attention')
  final=coverage_attention(first,False)
  self.assertEqual(final['intake_attention'],'Attachment unavailable')
 def test_source_reason_cannot_add_new_warning_lines(self):
  from kunal_enterprises.integrations.order_intake_ai_state import coverage_attention
  result=coverage_attention({},True,['Which quantity?\nInjected marker'])
  self.assertEqual(len(result['intake_attention'].splitlines()),1)
 def test_blank_reasons_keep_a_visible_attention_warning(self):
  from kunal_enterprises.integrations.order_intake_ai_state import coverage_attention, UNRESOLVED_WARNING
  result=coverage_attention({},True,['', '   ', None])
  self.assertEqual(result['intake_attention'],UNRESOLVED_WARNING)


class TestCurrentReviewQuestions(unittest.TestCase):
 def doc(self, questions='', **values):
  fields=dict(request_type='Order',customer='C1',customer_name='Harbor Interiors',customer_text='Harbor Interiors',sales_employee='SE1',
   salesperson_text='Matched sender',items=[Row(original_text='Variant A',item='SKU-A',quantity=2,
   quantity_unknown=0,warehouse_text='Warehouse A',godown='W1')],unresolved_questions=questions)
  fields.update(values);return SimpleNamespace(**fields)
 def test_resolved_matches_remove_stale_generated_questions_and_deduplicate_real_doubts(self):
  doc=self.doc('Select the customer for “Harbor”.\nSelect the product or variant for “Variant A”.\n'
   'Select the dispatch warehouse for “Warehouse A”.\nConfirm the quantity for “Variant A”; it was not understood.\n'
   'Are these delivery contacts?\n  are THESE delivery contacts?  ')
  self.assertEqual(current_review_questions(doc,{}),['Are these delivery contacts?'])
 def test_current_missing_fields_are_regenerated_once(self):
  doc=self.doc('Select the customer for “Old party”.',customer=None,sales_employee=None)
  doc.items[0].update(item=None,godown=None,quantity_unknown=1)
  result=current_review_questions(doc,{})
  self.assertEqual(len(result),5)
  self.assertTrue(any('Harbor Interiors' in text for text in result))
  self.assertFalse(any('Old party' in text for text in result))
 def test_generic_policy_questions_hide_only_when_current_context_supports_it(self):
  doc=self.doc('Please confirm whether the buying party is Harbor Interiors or Harbor Supply.\n'
   'Do the document project titles refer to separate scopes or one order?\n'
   'What should last-supply pricing mean; should the previous supply price be applied?\n'
   'Are the two shared people delivery contacts for this request?')
  context=dict(receiving_company='Harbor Supply',company_aliases=[])
  self.assertEqual(current_review_questions(doc,context),['Are the two shared people delivery contacts for this request?'])
  self.assertTrue(any('buying party' in text for text in current_review_questions(doc,{})))
 def test_conflicting_buyers_quantities_prices_and_unreadable_content_remain(self):
  questions=[
   'Document project titles suggest separate customers; confirm the buying party.',
   'Document project titles conflict; should they be separate scopes?',
   'The previous supply prices were 100 and 120; which applies?',
   'Confirm the previous supply price; different rates conflict.',
   'Which currency should the previous supply price apply in?',
   'The quantity differs between the two images.',
   'The document is unreadable; are separate scopes intended?',
   'Which phone number belongs to the delivery contact?',
  ]
  self.assertEqual(current_review_questions(self.doc('\n'.join(questions)),{}),questions)
 def test_unknown_legacy_phrasing_is_preserved_without_business_name_guesses(self):
  question='Do Alpha and Beta refer to separate scopes or one order?'
  self.assertEqual(current_review_questions(self.doc(question),{}),[question])
 def test_company_choices_require_selected_party_and_exact_alias_word_boundaries(self):
  question='Is the buying party Harbor Interiors or Joanne?'
  self.assertEqual(current_review_questions(self.doc(question),dict(receiving_company='Ann')),[question])
  doc=self.doc('Is the buying party Harbor Interiors or Harbor Supply?',customer=None)
  self.assertTrue(any('buying party' in text for text in current_review_questions(doc,dict(receiving_company='Harbor Supply'))))

 def test_pricing_inquiry_keeps_previous_supply_price_question(self):
  question='What should previous supply price mean; which price should be applied?'
  self.assertEqual(current_review_questions(self.doc(question,request_type='Price Inquiry'),{}),[question])

 def test_company_choice_can_quote_short_misspelled_extracted_name_of_selected_party(self):
  question='Please confirm whether the buying party is Harbor Interiore or Harbor Supply.'
  doc=self.doc(question,customer_name='HARBOR INTERIORS INDIA PVT LTD - CITY',customer_text='Harbor Interiore')
  self.assertEqual(current_review_questions(doc,dict(receiving_company='Harbor Supply')),[])
  doc.unresolved_questions=question+' The quantities conflict between the two images.'
  self.assertEqual(current_review_questions(doc,dict(receiving_company='Harbor Supply')),[doc.unresolved_questions])
