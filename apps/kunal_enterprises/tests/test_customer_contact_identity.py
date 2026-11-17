"""WhatsApp identity integration: contacts identify parents, not salespeople."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe

from kunal_enterprises.integrations import order_intake_capture as capture


class CustomerContactIdentityTests(unittest.TestCase):
	def identify(self, sender, customers=(), employees=()):
		db = SimpleNamespace(get_single_value=Mock(return_value='91'), sql=Mock(return_value=employees))
		with patch.object(frappe, 'db', db, create=True), patch(
			'kunal_enterprises.integrations.customer_contacts.find_customer_matches', return_value=customers
		) as lookup:
			result = capture._identity(sender)
			lookup.assert_called_once_with(sender)
		return result, db

	def test_contact_phone_resolves_to_parent_with_contact_context(self):
		result, db = self.identify('919998887776', customers=[dict(name='C-1', label='ABC', status='Active',
			contact_name='Ramesh', designation='Buyer')])
		self.assertEqual(result['identity_type'], 'Customer')
		self.assertEqual(result['customer'], 'C-1')
		self.assertIsNone(result['sales_employee'])
		self.assertEqual(json.loads(result['identity_candidates'])[0]['contact_name'], 'Ramesh')
		self.assertIn('tabSales Employee', db.sql.call_args.args[0])

	def test_historical_duplicate_contact_rows_still_identify_one_customer(self):
		row = dict(name='C-1', label='ABC', status='Active')
		result, _ = self.identify('919998887776', customers=[row, row])
		self.assertEqual(result['identity_type'], 'Customer')
		self.assertEqual(len(json.loads(result['identity_candidates'])), 1)

	def test_customer_contact_and_sales_employee_collision_remains_ambiguous(self):
		result, _ = self.identify('919998887776', customers=[dict(name='C-1', label='ABC', status='Active')],
			employees=[frappe._dict(name='SE-1', label='Salesperson', status='Active')])
		self.assertEqual(result['identity_type'], 'Ambiguous')
		self.assertIsNone(result['customer'])
		self.assertIsNone(result['sales_employee'])

	def test_formatted_customer_phone_does_not_expand_sales_employee_matching(self):
		result, db = self.identify('+91 99988.87776', customers=[dict(name='C-1', label='ABC', status='Active')])
		self.assertEqual(result['customer'], 'C-1')
		db.sql.assert_not_called()

	def test_opaque_whatsapp_id_stays_unknown_without_sales_employee_query(self):
		result, db = self.identify('future-sender-id')
		self.assertEqual(result['identity_type'], 'Unknown')
		db.sql.assert_not_called()


if __name__ == '__main__':
	unittest.main()
