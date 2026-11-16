"""Only business evidence, never provider download credentials, enters model prompts."""
import json
import unittest

from kunal_enterprises.integrations.order_intake_ai_input import model_messages


class TestOrderIntakeAIInput(unittest.TestCase):
	def test_captionless_media_does_not_send_provider_json_or_signed_url(self):
		body = dict(id='MEDIA', mime_type='image/jpeg', url='https://lookaside.fbsbx.com/media?hash=secret')
		row = dict(name='IMAGE', content_type='image', message=json.dumps(body),
			intake_raw_payload=json.dumps(dict(message=dict(type='image', image=body))),
			file_evidence=[dict(content_hash='local-hash')], intake_media_job_token='private-job-token')
		result = model_messages([row])[0]
		self.assertEqual(result['message'], '')
		self.assertEqual(result['content_type'], 'image')
		self.assertNotIn('secret', json.dumps(result))
		self.assertNotIn('file_evidence', result)
		self.assertNotIn('intake_media_job_token', result)
		self.assertIn('secret', row['intake_raw_payload'])  # Original evidence is untouched.

	def test_media_caption_and_normal_text_links_remain_actual_message_text(self):
		rows = [dict(name='PDF', content_type='document', intake_raw_payload=json.dumps(dict(message=dict(
			type='document', document=dict(caption='Shyam plywood, 4 sheets', url='https://lookaside.fbsbx.com/?hash=secret'))))),
			dict(name='TEXT', content_type='text', message='Reference https://example.com/product')]
		result = model_messages(rows)
		self.assertEqual(result[0]['message'], 'Shyam plywood, 4 sheets')
		self.assertEqual(result[1]['message'], rows[1]['message'])

	def test_legacy_html_encoded_media_json_is_not_mistaken_for_caption(self):
		row = dict(name='AUDIO', content_type='audio', message='{&quot;id&quot;:&quot;MEDIA&quot;,&quot;url&quot;:&quot;https://lookaside.fbsbx.com/?hash=secret&quot;}')
		self.assertEqual(model_messages([row])[0]['message'], '')
		self.assertEqual(model_messages([dict(name='IMAGE', content_type='image', message='Four sheets please')])[0]['message'], 'Four sheets please')

	def test_reply_reaction_location_and_profile_are_preserved_without_provider_envelope(self):
		row = dict(name='REACTION', content_type='reaction', message='👍', profile_name='Suraj',
			**{'from': '916363316577'}, reply_to_message_id='PROVIDER-PARENT', intake_has_location=1,
			intake_latitude=0, intake_longitude=0, intake_raw_payload=json.dumps(dict(message=dict(
				type='reaction', context=dict(id='PARENT', forwarded=True, from_user_id='unneeded'),
				reaction=dict(emoji='👍', message_id='PROVIDER-PARENT')))))
		result = model_messages([row])[0]
		self.assertEqual(result['message'], '👍')
		self.assertEqual(result['reaction'], dict(emoji='👍', message_id='PROVIDER-PARENT'))
		self.assertEqual(result['reply_context'], dict(message_id='PARENT', forwarded=True))
		self.assertEqual(result['intake_latitude'], 0)
		self.assertEqual(result['profile_name'], 'Suraj')
		self.assertNotIn('unneeded', json.dumps(result))

	def test_unsupported_and_conflicting_sources_stay_explicit_for_manual_review(self):
		rows = [dict(name='CONTACT', content_type='contact', message='private transport metadata'),
			dict(name='TEXT', content_type='text', message='Four sheets', intake_legacy_evidence='[{"conflict":true}]')]
		for result in model_messages(rows):
			self.assertTrue(result['manual_review_reason'])
		self.assertEqual(model_messages(rows)[0]['message'], '')

	def test_shared_contact_card_projects_name_and_phone_without_vcard_or_envelope(self):
		row = dict(name='CARD', content_type='contact', intake_original_type='contacts',
			reply_to_message_id='ORDER-WIRE', intake_raw_payload=json.dumps(dict(message=dict(type='contacts',
			contacts=[dict(name=dict(formatted_name='Amol Sawrikar'), phones=[dict(phone='+91 99854 45566',wa_id='919985445566',type='CELL')],vcard='do-not-send-vcard')], context=dict(id='ORDER-WIRE')))))
		result = model_messages([row])[0]
		self.assertEqual(result['contacts'], [dict(name='Amol Sawrikar',phones=[dict(phone='+91 99854 45566',wa_id='919985445566',type='CELL')])])
		self.assertIn('+91 99854 45566',result['message'])
		self.assertEqual(result['reply_context'],{'message_id':'ORDER-WIRE'})
		self.assertNotIn('manual_review_reason',result)
		self.assertNotIn('vcard',json.dumps(result))

	def test_malformed_contact_card_is_visible_manual_evidence(self):
		result=model_messages([dict(name='BAD',content_type='contact',intake_original_type='contacts',intake_raw_payload=json.dumps(dict(message=dict(contacts={'unexpected':'object'}))))])[0]
		self.assertEqual(result['contacts'],[])
		self.assertIn('Contact card',result['manual_review_reason'])
