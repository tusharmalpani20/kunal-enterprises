"""Company settings and real godown masters are the only business context source."""
from unittest import TestCase
from unittest.mock import patch

import frappe
from kunal_enterprises.integrations.order_intake_business_context import business_context


class TestBusinessContext(TestCase):
	def test_editable_company_and_aliases_with_active_master_query(self):
		settings = frappe._dict(company_name='  Receiving Business  ', company_aliases='Receiving Co\n\nReceiving Co\nOther Spelling')
		rows = [frappe._dict(name='WH-1', godown_name='Depot North')]
		with patch('frappe.get_single', return_value=settings), patch('frappe.get_all', return_value=rows) as query:
			result = business_context()
		self.assertEqual(result['receiving_company'], 'Receiving Business')
		self.assertEqual(result['company_aliases'], ['Receiving Co', 'Other Spelling'])
		self.assertEqual(result['warehouses'], rows)
		self.assertEqual(query.call_args.kwargs['filters'], {'is_active': 1})
		self.assertFalse(result['warehouses_truncated'])

	def test_no_hardcoded_company_or_warehouse_when_settings_and_masters_empty(self):
		with patch('frappe.get_single', return_value=frappe._dict()), patch('frappe.get_all', return_value=[]):
			self.assertEqual(business_context(), dict(receiving_company=None, company_aliases=[], warehouses=[], warehouses_truncated=False))

	def test_overflow_is_visible_and_context_remains_bounded(self):
		with patch('frappe.get_single', return_value=frappe._dict()), patch('frappe.get_all', return_value=[{'name': str(i)} for i in range(201)]):
			result = business_context()
		self.assertEqual(len(result['warehouses']), 200)
		self.assertTrue(result['warehouses_truncated'])
