"""Relevant learning is scoped and stays small; the model never sees all history."""
import json
from unittest import TestCase
from unittest.mock import patch

import frappe
from kunal_enterprises.integrations.order_intake_learning_context import confirmed_learning, relevant_examples


class TestCompactLearning(TestCase):
	def row(self, **values):
		return frappe._dict(dict(kind='customer', original_text='Shyam', selected_master='CUST-1',
			source_sender='919000000095', customer_context='', was_corrected=1,
			suggested_value='Other customer', correction_reason='Confirmed party', message_excerpt='', **values))

	def retrieve(self, rows, text='Order for Shyam, 21317 MR 4', **values):
		snapshot = dict(whatsapp_account='ACCOUNT', sender='919000000095', messages=[dict(name='M', content_type='text', message=text)], **values)
		with patch('kunal_enterprises.integrations.order_intake_learning_context._rows', return_value=rows) as query:
			result = confirmed_learning(snapshot)
		return result, query

	def test_only_relevant_confirmed_aliases_and_reasons_are_returned(self):
		other = self.row(); other.original_text = 'Aparna'
		result, query = self.retrieve([self.row(), other])
		self.assertEqual(len(result), 1)
		self.assertEqual(result[0]['confirmed'], 'CUST-1')
		self.assertEqual(result[0]['reason'], 'Confirmed party')
		query.assert_called_once_with('ACCOUNT', '919000000095')

	def test_item_and_warehouse_require_matching_customer_context(self):
		item = self.row(); item.update(kind='item', original_text='21317 MR', selected_master='21317 MR+', customer_context='CUST-1')
		self.assertEqual(self.retrieve([item])[0], [])
		self.assertEqual(self.retrieve([item], customer='OTHER')[0], [])
		self.assertEqual(self.retrieve([item], customer='CUST-1')[0][0]['confirmed'], '21317 MR+')
		self.assertEqual(len(self.retrieve([self.row(), item])[0]), 2)

	def test_request_type_does_not_learn_from_repeated_sku_or_party_alone(self):
		type_row = self.row(); type_row.update(kind='request_type', original_text='Stock availability Shyam 21317 MR 4', selected_master='Stock Inquiry')
		self.assertEqual(self.retrieve([type_row], text='Order for Shyam 21317 MR 4')[0], [])
		type_row.original_text = 'Please book these two sheets for Shyam'
		result, _ = self.retrieve([type_row], text='Book these two sheets for Shyam now')
		self.assertEqual(result[0]['confirmed'], 'Stock Inquiry')  # A reference, not an automatic intent override.

	def test_duplicates_and_conflicting_choices_are_explicit_and_bounded(self):
		first = self.row(); second = self.row(); second.selected_master = 'CUST-2'
		result, _ = self.retrieve([first, first, second])
		self.assertEqual(len(result), 2)
		self.assertTrue(all(row['conflicting'] for row in result))

	def test_json_budget_counts_utf8_and_preserves_complete_master_ids(self):
		rows = []
		for n in range(10):
			row = self.row(); row.selected_master = 'CUST-' + str(n); row.correction_reason = 'పేరు ' * 200
			rows.append(row)
		result, _ = self.retrieve(rows)
		self.assertLessEqual(len(result), 3)
		self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode('utf-8')), 1800)
		self.assertTrue(result)
		self.assertTrue(all(row['confirmed'].startswith('CUST-') for row in result))

	def test_stale_source_sender_and_empty_media_caption_do_not_supply_learning(self):
		row = self.row(); row.source_sender = '919000000096'
		self.assertEqual(self.retrieve([row])[0], [])
		with patch('kunal_enterprises.integrations.order_intake_learning_context._rows') as query:
			self.assertEqual(confirmed_learning(dict(whatsapp_account='ACCOUNT', sender='919000000095', messages=[dict(name='M', content_type='image', message='{"url":"https://secret.example/?token=secret"}') ])), [])
			query.assert_not_called()

	def test_identical_item_list_cannot_teach_request_type(self):
		row = self.row(); row.update(kind='request_type', original_text='21317 MR 4', selected_master='Order')
		self.assertEqual(self.retrieve([row], text='21317 MR 4')[0], [])

	def test_extraction_scope_filters_preloaded_examples_without_another_query(self):
		examples = [dict(kind='customer', wording='Shyam', confirmed='C1', label='Shyam Plywood'),
			dict(kind='item', wording='21317 MR', confirmed='SKU1', customer='C1'),
			dict(kind='godown', wording='KP', confirmed='WH1', customer='C1')]
		self.assertEqual(relevant_examples(examples, [dict(name='M', content_type='text', message='Order for Aparna 21317 MR 4')], customer='C2'), [])
		self.assertEqual(len(relevant_examples(examples, [dict(name='M', content_type='text', message='Order for Shyam 21317 MR 4 from KP')])), 3)

	def test_context_includes_readable_labels_and_reserves_room_for_intent_correction(self):
		customer = self.row(); customer.confirmed_label = 'Shyam Plywood'
		type_row = self.row(); type_row.update(kind='request_type', original_text='Book these sheets for Shyam', selected_master='Order')
		result, _ = self.retrieve([customer, type_row], text='Book these sheets for Shyam')
		self.assertEqual(result[0]['kind'], 'request_type')
		self.assertEqual(result[1]['label'], 'Shyam Plywood')

	def test_variant_plus_is_part_of_a_learned_alias_not_a_word_boundary(self):
		row = self.row(); row.update(kind='item', original_text='21317 MR', selected_master='SKU-MR', customer_context='C1')
		self.assertEqual(self.retrieve([row], text='21317 MR+ 4', customer='C1')[0], [])
		self.assertEqual(self.retrieve([row], text='21317 MR 4', customer='C1')[0][0]['confirmed'], 'SKU-MR')

	def test_compact_classification_example_does_not_cut_off_later_intent(self):
		text = 'Please book the following material. ' + 'Delivery instructions for the same site. ' * 7 + 'Correction: availability only, do not place an order.'
		row = self.row(); row.update(kind='request_type', original_text=text, selected_master='Stock Inquiry')
		result, _ = self.retrieve([row], text=text)
		self.assertTrue(result)
		self.assertTrue(result[0]['wording'].endswith('availability only, do not place an order.'))
		self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode('utf-8')), 1800)

	def test_conflicting_customer_example_cannot_supply_item_scope(self):
		examples = [dict(kind='customer', wording='Shyam', confirmed='C1', conflicting=True),
			dict(kind='item', wording='21317 MR', confirmed='SKU1', customer='C1')]
		result = relevant_examples(examples, [dict(name='M', content_type='text', message='Shyam 21317 MR 4')])
		self.assertEqual([example['kind'] for example in result], ['customer'])

	def test_old_open_request_does_not_establish_customer_for_a_new_message(self):
		item = self.row(); item.update(kind='item', original_text='21317 MR', selected_master='SKU1', customer_context='C1')
		result, _ = self.retrieve([item], text='Order for Aparna 21317 MR 4', open_requests=[dict(name='EARLIER', customer='C1')])
		self.assertEqual(result, [])

	def test_shortened_reason_is_marked_incomplete_instead_of_looking_verbatim(self):
		row = self.row(); row.correction_reason = 'Confirmed party explanation. ' * 20
		result, _ = self.retrieve([row])
		self.assertTrue(result[0]['reason'].endswith('…'))
		self.assertLessEqual(len(result[0]['reason']), 180)

	def test_any_matching_ambiguous_party_alias_blocks_inferred_item_scope(self):
		item = self.row(); item.update(kind='item', original_text='21317 MR', selected_master='SKU1', customer_context='C1')
		short = self.row(); short.update(original_text='ABC', selected_master='C1')
		first = self.row(); first.update(original_text='ABC Ltd', selected_master='C1')
		second = self.row(); second.update(original_text='ABC Ltd', selected_master='C2')
		result, _ = self.retrieve([item, short, first, second], text='ABC Ltd 21317 MR 4')
		self.assertNotIn('item', [example['kind'] for example in result])

	def test_extraction_does_not_ignore_an_overlapping_conflicting_party_alias(self):
		examples = [dict(kind='item', wording='21317 MR', confirmed='SKU1', customer='C1'),
			dict(kind='customer', wording='ABC', confirmed='C1'),
			dict(kind='customer', wording='ABC Ltd', confirmed='C2', conflicting=True)]
		messages = [dict(name='M', content_type='text', message='ABC Ltd 21317 MR 4')]
		self.assertNotIn('item', [example['kind'] for example in relevant_examples(examples, messages)])
		self.assertIn('item', [example['kind'] for example in relevant_examples(examples, messages, customer='C1')])
