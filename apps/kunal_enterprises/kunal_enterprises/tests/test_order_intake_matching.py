"""Master candidates preserve ambiguity and product specifications."""
from uuid import uuid4
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.integrations.order_intake_matching import search_candidates


class TestOrderIntakeMatching(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.prefix = "Match" + uuid4().hex[:12].translate(str.maketrans("0123456789", "ghijklmnop"))

	def tearDown(self):
		frappe.db.rollback()

	def master(self, kind, label, **values):
		meta = {"customer": ("Customer", "customer_name"), "sales_employee": ("Sales Employee", "sales_employee_name"),
			"item": ("Tally Item", "item_name"), "godown": ("Tally Godown", "godown_name")}
		doctype, field = meta[kind]
		name = uuid4().hex if kind in ("customer", "sales_employee") else label
		doc = frappe.get_doc(dict(doctype=doctype, name=name, **{field: label}, **values))
		doc.db_insert()  # Search fixtures deliberately include disabled/unapproved masters.
		return name

	def test_unique_exact_identity_selected_even_without_mobile_approval(self):
		name = self.master("customer", self.prefix + " Customer", status="Disabled", admin_approved=0)
		result = search_candidates("customer", "  " + self.prefix.lower() + " Customer  ")
		self.assertEqual(result["selected"], name)
		self.assertEqual(result["candidates"][0]["score"], 100)
		self.assertFalse(result["overflow"])

	def test_duplicate_customer_label_prefills_a_reviewable_candidate(self):
		for _ in range(2):
			self.master("customer", self.prefix)
		result = search_candidates("customer", self.prefix)
		self.assertEqual(result["selected"], result["candidates"][0]["name"])
		self.assertTrue(result["review_required"])
		self.assertEqual(len(result["candidates"]), 2)

	def test_exact_client_code_and_employee_code_are_searchable(self):
		customer = self.master("customer", "Someone", client_code=self.prefix)
		employee = self.master("sales_employee", "Someone else", employee_code=self.prefix)
		self.assertEqual(search_candidates("customer", self.prefix)["selected"], customer)
		self.assertEqual(search_candidates("sales_employee", self.prefix)["selected"], employee)

	def test_sf_does_not_expand_and_mr_plus_remains_a_candidate(self):
		best = self.master("item", self.prefix + " 21317 MR+")
		self.master("item", self.prefix + " 21317 SF")
		result = search_candidates("item", self.prefix + " 21317 MR")
		self.assertEqual(result["selected"], best)
		self.assertTrue(result["candidates"])
		self.assertTrue(all(row["score"] < 100 for row in result["candidates"]))
		self.assertTrue(any("MR+" in row["label"] for row in result["candidates"]))

	def test_pack_size_and_thickness_conflicts_do_not_become_candidates(self):
		good = self.master("item", self.prefix + " Fevicol 20 KG")
		bad = self.master("item", self.prefix + " Fevicol 10 KG")
		result = search_candidates("item", self.prefix + " Fevicol 20kg")
		self.assertEqual(result["selected"], good)
		self.assertNotIn(bad, [row["name"] for row in result["candidates"]])
		good = self.master("item", self.prefix + " 21317 SF 1.5 MM")
		bad = self.master("item", self.prefix + " 21317 SF 1 MM")
		result = search_candidates("item", self.prefix + " 21317 SF 1.5mm")
		self.assertEqual(result["selected"], good)
		self.assertNotIn(bad, [row["name"] for row in result["candidates"]])

	def test_leading_zero_design_code_is_a_candidate_not_an_alias_rule(self):
		item = self.master("item", self.prefix + " MERINO 021317 MR+")
		result = search_candidates("item", self.prefix + " 21317 MR")
		self.assertEqual(result["selected"], item)
		self.assertLess(result["candidates"][0]["score"], 100)
		self.assertIn(item, [row["name"] for row in result["candidates"]])

	def test_design_phrase_keeps_matching_candidates_without_an_abbreviation_guess(self):
		item = self.master("item", self.prefix + " 021317 MR+")
		result = search_candidates("item", "design " + self.prefix + " 21317 MR")
		self.assertEqual(result["selected"], item)
		self.assertLess(result["candidates"][0]["score"], 100)
		self.assertIn(item, [row["name"] for row in result["candidates"]])

	def test_truncated_pool_suggests_best_available_without_claiming_uniqueness(self):
		label = self.prefix + " Customers"
		frappe.db.bulk_insert("Customer", ["name", "customer_name"],
			[(uuid4().hex, label) for _ in range(201)])
		result = search_candidates("customer", label)
		self.assertTrue(result["overflow"])
		self.assertEqual(result["selected"], result["candidates"][0]["name"])
		self.assertTrue(result["review_required"])
		self.assertEqual(len(result["candidates"]), 5)

	def test_full_customer_branch_is_not_hidden_by_common_business_word_pool(self):
		label = "APARNA ENTERPRISES LTD - JUBILEE HILLS " + self.prefix[:5]
		name = "zz" + uuid4().hex
		# Alphabetically earlier unrelated parties exhaust the old Enterprises
		# anchor pool before the actual full branch can even be scored.
		frappe.db.bulk_insert("Customer", ["name", "customer_name"],
			[("00" + uuid4().hex, "Unrelated Enterprises " + uuid4().hex) for _ in range(201)]
			+ [(name, label)])
		result = search_candidates("customer", label)
		self.assertEqual(result["selected"], name)
		self.assertEqual(result["candidates"][0]["score"], 100)
		self.assertFalse(result["overflow"])

	def test_clear_closest_typo_is_prefilled_as_a_reviewable_suggestion(self):
		name = self.master("customer", self.prefix + " Enterprises")
		result = search_candidates("customer", self.prefix + " Enterprizes")
		self.assertEqual(result["selected"], name)
		self.assertLess(result["candidates"][0]["score"], 100)
		self.assertIn(name, [row["name"] for row in result["candidates"]])

	def test_limit_exposes_overflow_and_does_not_hide_ambiguity(self):
		for suffix in range(4):
			self.master("godown", self.prefix + " " + str(suffix))
		result = search_candidates("godown", self.prefix, limit=2)
		self.assertEqual(len(result["candidates"]), 2)
		self.assertTrue(result["overflow"])
		self.assertEqual(result["selected"], result["candidates"][0]["name"])
		self.assertTrue(result["review_required"])

	def test_blank_wildcard_and_unsupported_queries_are_safe(self):
		self.assertEqual(search_candidates("item", "%_ ")["candidates"], [])
		self.assertEqual(search_candidates("item", "")["candidates"], [])
		with self.assertRaises(frappe.ValidationError):
			search_candidates("User", "Administrator")

	def test_distinct_indic_vowel_marks_are_not_exact_identity_aliases(self):
		self.master('customer', self.prefix + ' रीम')
		result = search_candidates('customer', self.prefix + ' राम')
		self.assertEqual(result['selected'], result['candidates'][0]['name'])
		self.assertTrue(result['review_required'])
		self.assertTrue(all(candidate['score'] < 100 for candidate in result['candidates']))

	def test_distinct_sku_punctuation_is_not_an_exact_identity_alias(self):
		self.master('item', self.prefix + ' A/B')
		result = search_candidates('item', self.prefix + ' A-B')
		self.assertIsNone(result['selected'])
		self.assertTrue(all(candidate['score'] < 100 for candidate in result['candidates']))

	def test_clear_closest_mr_plus_is_prefilled_without_expanding_sf(self):
		best = self.master('item',self.prefix+' 21317 MR+')
		self.master('item',self.prefix+' 21317 SF')
		result=search_candidates('item','design '+self.prefix+' 21317 MR')
		self.assertEqual(result['selected'],best)
		self.assertLess(result['candidates'][0]['score'],100)

	def test_incompatible_short_variant_or_pack_unit_is_not_prefilled(self):
		for source, label in [('21317 MR','21317 SF'),('Fevicol 20 KG','Fevicol 20 G')]:
			self.master('item',self.prefix+' '+label)
			self.assertIsNone(search_candidates('item',self.prefix+' '+source)['selected'])

	def test_close_fuzzy_tie_prefills_best_candidate_for_review(self):
		self.master('customer',self.prefix+' Enterprises A')
		self.master('customer',self.prefix+' Enterprises B')
		result = search_candidates('customer',self.prefix+' Enterprizes')
		self.assertIn(result['selected'], [row['name'] for row in result['candidates']])
		self.assertTrue(result['review_required'])

	def test_literal_catalogue_name_takes_priority_over_generic_wrapper_removal(self):
		literal=self.master('item','Design '+self.prefix+' 57319 MR')
		self.master('item',self.prefix+' 57319 MR')
		self.assertEqual(search_candidates('item','Design '+self.prefix+' 57319 MR')['selected'],literal)

	def test_numbers_cannot_be_reused_from_another_specification_to_match_pack_size(self):
		self.master('item',self.prefix+' Fevicol 120 KG code 20')
		self.assertIsNone(search_candidates('item',self.prefix+' Fevicol 20 KG')['selected'])

	def test_numbered_warehouse_and_customer_identifiers_must_not_be_swapped(self):
		for kind in ('godown','customer','sales_employee'):
			self.master(kind,self.prefix+' Central Dispatch 2')
			self.assertIsNone(search_candidates(kind,self.prefix+' Central Dispatch 1')['selected'])

	def test_internal_customer_id_number_cannot_override_branch_number(self):
		frappe.get_doc(dict(doctype='Customer', name='numeric-identity-1',
			customer_name=self.prefix + ' Central Dispatch 2')).db_insert()
		self.assertIsNone(search_candidates('customer', self.prefix + ' Central Dispatch 1')['selected'])

	def test_warehouse_qualifiers_do_not_hide_a_unique_named_godown(self):
		name = self.master('godown', self.prefix + ' Goshamahal')
		for wording in (self.prefix + ' Goshamahal godown', 'warehouse ' + self.prefix + ' Goshamahal'):
			result = search_candidates('godown', wording)
			self.assertEqual(result['selected'], name)
			self.assertLess(result['candidates'][0]['score'], 100)
			self.assertTrue(result['candidates'][0]['reasonable'])

	def test_short_customer_trading_name_matches_plural_name_with_branch_suffix(self):
		name = self.master('customer', self.prefix + ' PLYWOODS - GOSHAMAHAL')
		result = search_candidates('customer', self.prefix + ' plywood')
		self.assertEqual(result['selected'], name)
		self.assertLess(result['candidates'][0]['score'], 100)
		self.assertTrue(result['candidates'][0]['reasonable'])

	def test_short_customer_name_suggests_a_branch_but_explicit_branch_ranks_first(self):
		first = self.master('customer', self.prefix + ' PLYWOODS - GOSHAMAHAL')
		second = self.master('customer', self.prefix + ' PLYWOODS - KUKATPALLY')
		result = search_candidates('customer', self.prefix + ' plywood')
		self.assertIn(result['selected'], (first, second))
		self.assertTrue(result['review_required'])
		self.assertEqual(search_candidates('customer', self.prefix + ' plywood Goshamahal')['selected'], first)
		self.assertNotEqual(first, second)

	def test_customer_business_plural_is_not_an_item_variant_alias(self):
		self.master('item', self.prefix + ' PLYWOODS')
		result = search_candidates('item', self.prefix + ' PLYWOOD')
		self.assertTrue(all(row['score'] < 100 for row in result['candidates']))
		# Customer noun folding must not merge punctuation-distinct party names.
		self.master('customer', self.prefix + ' A/B PLYWOODS - GOSHAMAHAL')
		self.assertTrue(search_candidates('customer', self.prefix + ' A-B PLYWOOD')['review_required'])

	def test_spaced_typographic_branch_separator_matches_customer_name(self):
		name = self.master('customer', self.prefix + ' Enterprises Ltd - Jubilee Hills')
		result = search_candidates('customer', self.prefix + ' Enterprises Ltd — Jubilee Hills')
		self.assertEqual(result['selected'], name)
		self.assertLess(result['candidates'][0]['score'], 100)

	def test_separated_item_count_does_not_override_product_identity(self):
		name = self.master('item', self.prefix + ' 11103 SF')
		for count in (' - 1 sheet', ' — 2 NOS', ': 3 pieces'):
			self.assertEqual(search_candidates('item', self.prefix + ' 11103 SF' + count)['selected'], name)
		self.assertIsNone(search_candidates('item', self.prefix + ' 11103 SF - 20 kg')['selected'])

	def test_literal_item_count_suffix_still_takes_priority(self):
		self.master('item', self.prefix + ' 11103 SF')
		literal = self.master('item', self.prefix + ' 11103 SF - 1 sheet')
		self.assertEqual(search_candidates('item', self.prefix + ' 11103 SF - 1 sheet')['selected'], literal)

	def test_brand_code_variant_can_fill_descriptive_liner_wording(self):
		name = self.master('item', self.prefix + ' PLUS LAM 2249 SF', root_stock_group=self.prefix + ' PLUS')
		self.master('item', self.prefix + ' EDGEBAND 2249', root_stock_group=self.prefix + ' PLUS')
		result = search_candidates('item', self.prefix + ' liner 2249 SF')
		self.assertEqual(result['selected'], name)
		self.assertEqual(result['candidates'][0]['score'], 90)

	def test_root_group_supplies_brand_for_short_code_variant_name(self):
		name = self.master('item', '40268 FT ' + self.prefix, root_stock_group='Merino Industries Limited')
		self.master('item', '40268 MR+ ' + self.prefix, root_stock_group='Merino Industries Limited')
		result = search_candidates('item', 'Merino 40268 FT ' + self.prefix)
		self.assertEqual(result['selected'], name)
		self.assertEqual(result['candidates'][0]['score'], 90)

	def test_code_variant_evidence_cannot_drop_conflicting_brand_or_variant(self):
		self.master('item', self.prefix + ' PLUS LAM 2249 SF', root_stock_group=self.prefix + ' PLUS')
		for wording in ('OtherBrand liner 2249 SF', self.prefix + ' OtherBrand 2249 SF', self.prefix + ' liner 2249 FT'):
			self.assertIsNone(search_candidates('item', wording)['selected'])

	def test_brand_code_variant_suggests_a_size_for_review_when_unspecified(self):
		for size in ('4X8', '4X10'):
			self.master('item', self.prefix + ' PLUS LAM 2249 SF ' + size, root_stock_group=self.prefix + ' PLUS')
		result = search_candidates('item', self.prefix + ' liner 2249 SF')
		self.assertIsNotNone(result['selected'])
		self.assertTrue(result['review_required'])

	def test_complete_customer_name_and_branch_without_separator_is_prefilled(self):
		rows = [frappe._dict(name='SHYAM', customer_name='SHYAM PLYWOODS - GOSHAMAHAL'),
			frappe._dict(name='JAI-SHYAM', customer_name='JAI SHYAM PLYWOOD - GOSHAMAHAL'),
			frappe._dict(name='RAM-SHYAM', customer_name='RAM SHYAM PLYWOOD-GOSHAMAHAL')]
		with patch('kunal_enterprises.integrations.order_intake_matching._pool', return_value=(rows, False)):
			result = search_candidates('customer', 'Shyam plywood Goshamahal')
		self.assertEqual(result['selected'], 'SHYAM')
		self.assertLess(result['candidates'][0]['score'], 100)

	def test_omitted_separator_prefills_closest_trading_name_for_review(self):
		rows = [frappe._dict(name='SHYAM-A', customer_name='SHYAM PLYWOODS - GOSHAMAHAL'),
			frappe._dict(name='SHYAM-B', customer_name='SHYAM PLYWOOD - GOSHAMAHAL')]
		with patch('kunal_enterprises.integrations.order_intake_matching._pool', return_value=(rows, False)):
			result = search_candidates('customer', 'Shyam plywood Goshamahal')
			self.assertIn(result['selected'], ('SHYAM-A','SHYAM-B'))
			self.assertTrue(result['review_required'])

	def test_split_location_and_short_trading_name_prefill_closest_customer(self):
		rows = [frappe._dict(name='GANESH', customer_name='GANESH GLASS & PLYWOOD- SHER LINGAMPALLY'),
			frappe._dict(name='OTHER', customer_name='RAMDEV PLYWOOD & HARDWARE - SHERLINGAMPALLY')]
		with patch('kunal_enterprises.integrations.order_intake_matching._pool', return_value=(rows,False)):
			result = search_candidates('customer', 'Ganesh glass Sherlingampally')
		self.assertEqual(result['selected'], 'GANESH')
		self.assertTrue(result['review_required'])

	def test_explicit_warehouse_name_in_longer_location_wording_is_prefilled(self):
		name = self.master('godown', self.prefix + ' Kukatpally')
		result = search_candidates('godown', self.prefix + ' Kukatpally / Moosapet Godown')
		self.assertEqual(result['selected'], name)
		self.assertTrue(result['review_required'])

	def test_warehouse_options_choose_first_available_and_retain_alternatives(self):
		first = self.master('godown', self.prefix + ' Zulu Depot')
		second = self.master('godown', self.prefix + ' Alpha Depot')
		result = search_candidates('godown', first + ' / ' + second + ' Godown')
		self.assertEqual(result['selected'], first)
		self.assertEqual([row['name'] for row in result['candidates']][:2], [first, second])
		self.assertTrue(result['review_required'])
		reversed_result = search_candidates('godown', second + '/' + first)
		self.assertEqual(reversed_result['selected'], second)

	def test_tagged_warehouse_option_uses_first_available(self):
		name = self.master('godown', self.prefix + ' Kukatpally')
		result = search_candidates('godown', '@' + self.prefix + ' Kukatpally / Missingplace Godown')
		self.assertEqual(result['selected'], name)

	def test_missing_first_warehouse_option_uses_next_available(self):
		second = self.master('godown', self.prefix + ' Kukatpally')
		result = search_candidates('godown', 'UnlistedXYZ / ' + second + ' Godown')
		self.assertEqual(result['selected'], second)

	def test_warehouse_options_check_numbers_per_option(self):
		one = self.master('godown', self.prefix + ' Depot 1')
		self.master('godown', self.prefix + ' Depot 2')
		self.assertEqual(search_candidates('godown', one + ' / ' + self.prefix + ' Depot 2')['selected'], one)

	def test_literal_warehouse_with_slash_is_not_split_into_other_records(self):
		whole = self.master('godown', self.prefix + ' North/South')
		self.master('godown', self.prefix + ' North')
		self.assertEqual(search_candidates('godown', whole)['selected'], whole)

	def test_short_trading_name_typo_beats_short_unrelated_interior_party(self):
		correct = self.master('customer', self.prefix + ' STEP IN INTERIORS INDIA PVT LTD - HYDERABAD')
		self.master('customer', self.prefix + ' BIRAN INTERIOR')
		result = search_candidates('customer', self.prefix + ' Step in Interiore')
		self.assertEqual(result['selected'], correct)
		self.assertTrue(result['review_required'])

	def test_short_design_with_brand_and_variant_is_retrieved_before_unrelated_color(self):
		correct = self.master('item', self.prefix + ' ASA HG 102', root_stock_group='MARIA DECOR')
		self.master('item', self.prefix + ' EDGEBAND HG 102', root_stock_group='MARIA DECOR')
		self.master('item', self.prefix + ' ASA HG 1102', root_stock_group='MARIA DECOR')
		result = search_candidates('item', self.prefix + ' Maria Decor ASA HG 102')
		self.assertEqual(result['selected'], correct)
		self.assertTrue(result['review_required'])

	def test_missing_colour_wording_preserves_brand_code_finish_candidates_for_review(self):
		rows = [frappe._dict(name='Panel HG 102', item_name='Panel HG 102', root_stock_group='MARIA DECOR')]
		wording = '102 Polar White Maria Decor HG'
		with patch('kunal_enterprises.integrations.order_intake_matching._pool', return_value=(rows, False)):
			result = search_candidates('item', wording)
			self.assertEqual(result['selected'], 'Panel HG 102')
			self.assertTrue(result['review_required'])
			rows.append(frappe._dict(name='Edgeband HG 102', item_name='Edgeband HG 102', root_stock_group='MARIA DECOR'))
			result = search_candidates('item', wording)
			self.assertIsNone(result['selected'])
			self.assertEqual({row['name'] for row in result['candidates']}, {'Panel HG 102', 'Edgeband HG 102'})
