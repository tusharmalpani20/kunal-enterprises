"""Cards retain business names/numbers within explicit bounds, never vCard blobs."""
import json
from unittest import TestCase
from kunal_enterprises.integrations.order_intake_contacts import project_contacts, contacts_from_source


class TestContactProjection(TestCase):
	def test_legacy_escaped_cards_and_wa_id_without_phone_remain_readable(self):
		body=[dict(name=dict(first_name='Contact',last_name='Person'),phones=[dict(wa_id='919000000001')],vcard='secret')]
		contacts,warning=contacts_from_source(dict(message=json.dumps(body).replace('"','&quot;')))
		self.assertEqual(contacts,[dict(name='Contact Person',phones=[dict(phone='919000000001',wa_id='919000000001')])])
		self.assertIsNone(warning)

	def test_limits_keep_truncated_cards_explicit_for_review(self):
		body=[dict(name=dict(formatted_name='Person '+str(i)),phones=[dict(phone=str(n)) for n in range(11)]) for i in range(11)]
		contacts,warning=project_contacts(body)
		self.assertEqual(len(contacts),10)
		self.assertEqual(len(contacts[0]['phones']),10)
		self.assertTrue(warning)

	def test_non_objects_do_not_raise_or_invent_contacts(self):
		for body in (None,{},['bad'],[dict(name='bad',phones='bad')]):
			contacts,warning=project_contacts(body)
			self.assertEqual(contacts,[])
			self.assertTrue(warning)

	def test_non_phone_text_is_not_exposed_as_a_phone_number(self):
		contacts,warning=project_contacts([dict(name=dict(formatted_name='Person'),phones=[dict(phone='https://provider/?token=secret',wa_id='919000000001')])])
		self.assertEqual(contacts[0]['phones'][0]['phone'],'919000000001')
		self.assertTrue(warning)
		self.assertNotIn('secret',str(contacts))
