"""The useful correction is confirmed outcome plus a small amount of provenance."""
import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe
from kunal_enterprises.integrations.order_intake_feedback import feedback_fields, source_excerpt


class Values(SimpleNamespace):
	def get(self, field):
		return getattr(self, field, None)


class TestFeedbackProjection(TestCase):
	def test_item_reason_overrides_general_reason_and_keeps_original_selection(self):
		request = Values(ai_initial_values=json.dumps(dict(items=[dict(row_key='ONE', item='OLD', godown=None)])),
			items=[Values(row_key='ONE', item='NEW', godown='WAREHOUSE', correction_reason='Correct product variant')],
			request_type='Order', correction_reason='General explanation')
		result = feedback_fields(request, 'item', 'ONE', excerpt='Source wording')
		self.assertEqual(result['suggested_value'], 'OLD')
		self.assertEqual(result['was_corrected'], 1)
		self.assertEqual(result['correction_reason'], 'Correct product variant')
		self.assertEqual(result['message_excerpt'], 'Source wording')

	def test_no_baseline_does_not_invent_an_ai_correction(self):
		request = Values(items=[], customer='CUSTOMER', request_type='Order', correction_reason='Human note')
		result = feedback_fields(request, 'customer', excerpt='Party')
		self.assertEqual(result['was_corrected'], 0)
		self.assertEqual(result['suggested_value'], '')
		self.assertEqual(result['correction_reason'], 'Human note')

	def test_source_excerpt_is_bounded_and_removes_signed_media_urls(self):
		request = Values(source_messages=[Values(message='IMAGE'), Values(message='TEXT')])
		rows = [frappe._dict(name='IMAGE', content_type='image', message='provider-json',
			intake_raw_payload=json.dumps(dict(message=dict(type='image', image=dict(caption='Two sheets', url='https://media/?token=secret'))))),
			frappe._dict(name='TEXT', content_type='text', message='A' * 2000)]
		with patch('frappe.get_all', return_value=rows):
			result = source_excerpt(request)
		self.assertEqual(len(result), 1000)
		self.assertTrue(result.startswith('Two sheets\n'))
		self.assertNotIn('secret', result)

	def test_source_text_truncation_is_detected_before_clipping_or_whitespace_cleanup(self):
		from kunal_enterprises.integrations.order_intake_feedback import source_excerpt_details
		request = Values(source_messages=[Values(message='TEXT')])
		rows = [frappe._dict(name='TEXT', content_type='text', message='A' * 1000 + ' \nNot an order')]
		with patch('frappe.get_all', return_value=rows):
			excerpt, truncated = source_excerpt_details(request)
		self.assertEqual(len(excerpt), 1000)
		self.assertTrue(truncated)
