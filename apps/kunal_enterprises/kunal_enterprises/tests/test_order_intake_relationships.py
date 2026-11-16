"""Order relationships must be supported by source evidence, not repeated SKU lists."""
from unittest import TestCase

from kunal_enterprises.integrations.order_intake_ai_models import Group, Grouping
from kunal_enterprises.integrations.order_intake_ai_relationships import constrain_relationships


class TestOrderIntakeRelationships(TestCase):
	def run_groups(self, messages, groups, requests=None):
		result = Grouping(groups=[Group(**row) for row in groups], unresolved_message_ids=[])
		return constrain_relationships(result, messages, requests or [])

	def test_independent_item_lists_do_not_create_an_artificial_quantity_conflict(self):
		messages = [dict(name='A', message='14689 4\n21317 mr 4\nMaa Annapurna'),
			dict(name='B', message='14689 4\n21317 mr 2\nRequired urgently tomorrow morning')]
		result = self.run_groups(messages, [dict(message_ids=['A', 'B'], target_request=None,
			request_hint='Possible same order with conflicting quantities', relationship='continuation',
			relationship_evidence=[dict(source_message='B', quote='Required urgently tomorrow morning')])])
		self.assertEqual([g.message_ids for g in result.groups], [['A'], ['B']])
		self.assertTrue(all(g.relationship_note for g in result.groups))
		self.assertEqual(set(result.unresolved_message_ids), {'A', 'B'})

	def test_new_order_marker_cannot_reassign_an_earlier_orders_items(self):
		messages = [dict(name='OLD', message='Shyam\n21317 MR+ - 4 sheets\n21022 SF - 2 sheets'),
			dict(name='NEW', message='Two separate orders:\n1. Shyam\n21317 MR+ - 4 sheets\n2. Aparna\n21022 SF - 2 sheets')]
		result = self.run_groups(messages, [dict(message_ids=['OLD', 'NEW'], target_request='OIR-1',
			request_hint='Shyam now excludes 21022', relationship='correction',
			relationship_evidence=[dict(source_message='NEW', quote='Two separate orders:')])],
			[dict(name='OIR-1', source_messages=['OLD'])])
		self.assertEqual(result.groups[0].message_ids, ['OLD'])
		self.assertEqual(result.groups[0].target_request, 'OIR-1')
		self.assertEqual(result.groups[1].message_ids, ['NEW'])
		self.assertIsNone(result.groups[1].target_request)
		self.assertEqual(result.groups[1].relationship, 'new')

	def test_explicit_quantity_correction_and_reply_continuation_remain_grouped(self):
		for follow in [dict(name='B', message='Change 21317 MR to 5 sheets'),
			dict(name='B', message='21317 mr 5', reply_to_message_id='wire-A')]:
			messages = [dict(name='A', message='21317 mr 4', message_id='wire-A'), follow]
			result = self.run_groups(messages, [dict(message_ids=['A', 'B'], target_request='OIR-1',
				request_hint='Correction to prior order', relationship='correction',
				relationship_evidence=[dict(source_message='B', quote=follow['message'])])],
				[dict(name='OIR-1', source_messages=['A'])])
			self.assertEqual(len(result.groups), 1)
			self.assertEqual(result.groups[0].target_request, 'OIR-1')

	def test_split_order_items_and_customer_fragment_can_form_one_request(self):
		messages = [dict(name='A', message='21317 MR 4\n21022 SF 2'), dict(name='B', message='For Shyam Plywood, from Goshamahal')]
		result = self.run_groups(messages, [dict(message_ids=['A', 'B'], target_request=None,
			request_hint='Items and party followup', relationship='continuation',
			relationship_evidence=[dict(source_message='B', quote='For Shyam Plywood, from Goshamahal')])])
		self.assertEqual(len(result.groups), 1)
		self.assertEqual(result.groups[0].message_ids, ['A', 'B'])

	def test_fabricated_quote_and_sku_only_quote_do_not_authorize_existing_update(self):
		for quote in ['Please change the previous order', '21317 MR 5']:
			messages = [dict(name='NEW', message='21317 MR 5')]
			result = self.run_groups(messages, [dict(message_ids=['NEW'], target_request='OIR-1',
				request_hint='Same design', relationship='correction',
				relationship_evidence=[dict(source_message='NEW', quote=quote)])],
				[dict(name='OIR-1', source_messages=['OLD'])])
			self.assertIsNone(result.groups[0].target_request)
			self.assertTrue(result.groups[0].relationship_note)

	def test_covered_only_groups_keep_their_existing_request_without_new_evidence(self):
		result = self.run_groups([dict(name='A', message='21317 MR 4')],
			[dict(message_ids=['A'], target_request='OIR-1', request_hint='Already linked')],
			[dict(name='OIR-1', source_messages=['A'])])
		self.assertEqual(result.groups[0].target_request, 'OIR-1')

	def test_non_english_explicit_relationship_is_not_rejected_for_lack_of_english_keywords(self):
		text = 'మునుపటి ఆర్డర్ పరిమాణం మార్చండి 21317 MR 5'
		result = self.run_groups([dict(name='B', message=text)], [dict(message_ids=['B'], target_request='OIR-1',
			request_hint='Quantity correction', relationship='correction',
			relationship_evidence=[dict(source_message='B', quote=text)])], [dict(name='OIR-1', source_messages=['A'])])
		self.assertEqual(result.groups[0].target_request, 'OIR-1')

	def test_reply_with_explicit_new_order_does_not_change_the_quoted_old_order(self):
		messages = [dict(name='A', message='21317 MR 4', message_id='wire-A'),
			dict(name='B', message='Another order:\n21317 MR 5', reply_to_message_id='wire-A')]
		result = self.run_groups(messages, [dict(message_ids=['A', 'B'], target_request='OIR-1',
			request_hint='Same customer', relationship='correction',
			relationship_evidence=[dict(source_message='B', quote='Another order:')])],
			[dict(name='OIR-1', source_messages=['A'])])
		self.assertEqual(len(result.groups), 2)
		self.assertIsNone(result.groups[1].target_request)

	def test_explicit_addition_to_an_item_list_preserves_multipart_order(self):
		messages = [dict(name='A', message='21317 MR 4'), dict(name='B', message='Also add 21022 SF 2')]
		result = self.run_groups(messages, [dict(message_ids=['A', 'B'], target_request=None,
			request_hint='One order with additional item', relationship='continuation',
			relationship_evidence=[dict(source_message='B', quote='Also add 21022 SF 2')])])
		self.assertEqual(len(result.groups), 1)
		self.assertEqual(result.groups[0].message_ids, ['A', 'B'])

	def test_old_correction_quote_cannot_authorize_an_unrelated_fresh_order(self):
		messages = [dict(name='OLD', message='Change previous order to 21317 MR 4'),
			dict(name='NEW', message='21317 MR 2\nAnother Party')]
		result = self.run_groups(messages, [dict(message_ids=['OLD', 'NEW'], target_request='OIR-1',
			request_hint='Change old quantity', relationship='correction',
			relationship_evidence=[dict(source_message='OLD', quote='Change previous order')])],
			[dict(name='OIR-1', source_messages=['OLD'])])
		self.assertEqual(len(result.groups), 2)
		self.assertIsNone(result.groups[1].target_request)

	def test_defensive_splitting_keeps_overflow_messages_visible_as_unresolved(self):
		messages = [dict(name=str(i), message=f'21317 MR {i+1}') for i in range(25)]
		result = self.run_groups(messages, [dict(message_ids=[m['name'] for m in messages],
			target_request=None, request_hint='Possibly overlapping orders')])
		self.assertEqual(len(result.groups), 20)
		covered = {name for entry in result.groups for name in entry.message_ids}
		self.assertEqual(covered | set(result.unresolved_message_ids), {m['name'] for m in messages})

	def test_customer_branch_guard_preserves_qualifier_without_borrowing_delivery_or_item_text(self):
		from kunal_enterprises.integrations.order_intake_ai_relationships import omitted_customer_qualifier
		self.assertTrue(omitted_customer_qualifier('Aparna Enterprises Ltd', [dict(message='2. APARNA ENTERPRISES LTD - JUBILEE HILLS\n21022 SF 2')]))
		self.assertFalse(omitted_customer_qualifier('Aparna Enterprises Ltd - Jubilee Hills', [dict(message='APARNA ENTERPRISES LTD - JUBILEE HILLS')]))
		self.assertFalse(omitted_customer_qualifier('Aparna Enterprises Ltd', [dict(message='APARNA ENTERPRISES LTD\nDelivery: Jubilee Hills\n21317 MR - 4')]))

	def test_old_correction_cannot_override_new_order_marker_in_a_reply(self):
		messages = [dict(name='OLD', message='Change previous order to 21317 MR 4', message_id='wire-OLD'),
			dict(name='NEW', message='Another order:\n21317 MR 2', reply_to_message_id='wire-OLD')]
		result = self.run_groups(messages, [dict(message_ids=['OLD', 'NEW'], target_request='OIR-1',
			request_hint='Correct quantity', relationship='correction',
			relationship_evidence=[dict(source_message='OLD', quote='Change previous order')])],
			[dict(name='OIR-1', source_messages=['OLD'])])
		self.assertEqual(len(result.groups), 2)
		self.assertIsNone(result.groups[1].target_request)
