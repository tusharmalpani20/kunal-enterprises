import unittest
from types import SimpleNamespace
from kunal_enterprises.integrations.order_intake_ai_review import preserve_existing_items, review_questions

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
