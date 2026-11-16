"""Candidate retrieval must not lose a customer over joined location words."""
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.integrations.order_intake_matching import _pool, MASTERS, POOL_LIMIT


class TestOrderIntakeCandidatePool(FrappeTestCase):
	def setUp(self):
		frappe.set_user('Administrator')
		self.prefix = 'Pool' + uuid4().hex[:6].translate(str.maketrans('0123456789', 'ghijklmnop'))

	def tearDown(self):
		frappe.db.rollback()

	def customer(self, label):
		name = uuid4().hex
		frappe.get_doc(dict(doctype='Customer', name=name, customer_name=label)).db_insert()
		return name

	def pool(self, text):
		doctype, _, fields = MASTERS['customer']
		return _pool(doctype, fields, text)

	def test_joined_location_still_retrieves_customer_when_location_only_pool_has_others(self):
		wanted = self.customer(self.prefix + ' GLASS & PLYWOOD- SHER LINGAMPALLY')
		self.customer('Other ' + self.prefix + ' Hardware - SHERLINGAMPALLY')
		rows, overflow = self.pool(self.prefix.lower() + ' glass sherlingampally')
		self.assertIn(wanted, [row.name for row in rows])
		self.assertFalse(overflow)

	def test_split_query_words_retrieve_a_joined_master_location(self):
		wanted = self.customer(self.prefix + ' GLASS - SHERLINGAMPALLY')
		rows, _ = self.pool(self.prefix.lower() + ' glass sher lingampally')
		self.assertIn(wanted, [row.name for row in rows])

	def test_misspelled_location_does_not_hide_name_matches_behind_longest_anchor(self):
		wanted = self.customer(self.prefix + ' GLASS & PLYWOOD- SHER LINGAMPALLY')
		self.customer('Unrelated ' + self.prefix + ' Hardware - SHERLINGAMPALY')
		rows, _ = self.pool(self.prefix.lower() + ' glass sherlingampaly')
		self.assertIn(wanted, [row.name for row in rows])

	def test_candidate_limit_and_overflow_stay_explicit(self):
		for _ in range(POOL_LIMIT + 1):
			self.customer(self.prefix + ' GLASS- SHER LINGAMPALLY')
		rows, overflow = self.pool(self.prefix.lower() + ' glass sherlingampally')
		self.assertEqual(len(rows), POOL_LIMIT)
		self.assertTrue(overflow)

	def test_item_family_not_hidden_by_brand_only_limit(self):
		for index in range(POOL_LIMIT + 1):
			label = self.prefix + ' AAA PLY ' + str(index)
			frappe.get_doc(dict(doctype='Tally Item', name=label, item_name=label)).db_insert()
		wanted = self.prefix + ' ZZZ MDF 8MM'
		frappe.get_doc(dict(doctype='Tally Item', name=wanted, item_name=wanted)).db_insert()
		doctype, _, fields = MASTERS['item']
		rows, overflow = _pool(doctype, fields, self.prefix.lower() + ' mdf bilo 8.')
		self.assertIn(wanted, [row.name for row in rows])
		self.assertTrue(overflow)

	def test_period_after_design_keeps_numeric_anchor(self):
		wanted = self.prefix + ' MDF 2200'
		other = self.prefix + ' MDF 2201'
		for label in (wanted, other):
			frappe.get_doc(dict(doctype='Tally Item', name=label, item_name=label)).db_insert()
		doctype, _, fields = MASTERS['item']
		rows, _ = _pool(doctype, fields, self.prefix.lower() + ' mdf 2200.')
		self.assertIn(wanted, [row.name for row in rows])
		self.assertNotIn(other, [row.name for row in rows])
