"""Request-scoped conversation evidence, private files and stable review pages."""
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.api.order_intake_conversation import messages


class TestOrderIntakeConversation(FrappeTestCase):
	def setUp(self):
		frappe.set_user('Administrator')
		self.account = frappe.get_doc(dict(doctype='WhatsApp Account', account_name='Conversation '+uuid4().hex,
			phone_id=uuid4().hex, status='Active')).insert(ignore_permissions=True)
		self.sender='919000000094'
		self.files=[]

	def tearDown(self):
		frappe.set_user('Administrator');frappe.db.rollback()
		for path in self.files:
			path.unlink(missing_ok=True)

	def source(self, text='Synthetic request', **values):
		return frappe.get_doc(dict(doctype='WhatsApp Message', type='Incoming', whatsapp_account=self.account.name,
			**{'from':self.sender}, message=text, message_id=uuid4().hex, content_type='text', **values)).insert(ignore_permissions=True)

	def request(self, sources=(), **values):
		return frappe.get_doc(dict(doctype='Order Intake Request',whatsapp_account=self.account.name,sender_number=self.sender,
			source_messages=[dict(message=s.name) for s in sources],**values)).insert()

	def private_file(self, owner, doctype='WhatsApp Message'):
		name='conversation-'+uuid4().hex+'.pdf'
		path=Path(frappe.get_site_path('private','files',name));path.write_bytes(b'%PDF-1.4 synthetic fixture')
		self.files.append(path)
		file=frappe.get_doc(dict(doctype='File',name='file-'+uuid4().hex,file_url='/private/files/'+name,
			file_name=name,is_private=1,attached_to_doctype=doctype,attached_to_name=owner))
		file.db_insert();return file

	def test_complete_text_zero_location_and_safe_replies_are_returned_without_payload_secrets(self):
		first=self.source('<script>bad()</script>\n'+'long text '*1000, profile_name='WhatsApp profile')
		second=self.source('Second',reply_to_message_id=first.message_id)
		frappe.db.set_value('WhatsApp Message',second.name,dict(intake_has_location=1,intake_latitude=0,intake_longitude=0,
			intake_raw_payload='private-provider-secret',intake_attention='Needs review'),update_modified=False)
		doc=self.request([first,second]);result=messages(doc.name)
		by_name={row['name']:row for row in result['messages']}
		self.assertEqual(by_name[first.name]['text'],first.message)
		self.assertEqual(by_name[second.name]['reply_to'],first.name)
		self.assertEqual(by_name[second.name]['location']['latitude'],0)
		self.assertNotIn('private-provider-secret',str(result))
		self.assertEqual(by_name[second.name]['warnings'],['Needs review'])
		self.assertEqual(result['sender_profile_name'], 'WhatsApp profile')

	def test_sender_identity_uses_phone_not_selected_order_customer_and_handles_ambiguity(self):
		number = '9' + str(uuid4().int)[:9]
		self.sender = '91' + number
		source = self.source(); doc = self.request([source])
		self.assertEqual(messages(doc.name)['sender_identity'], dict(status='Unknown', matches=[]))
		customer = frappe.get_doc(dict(doctype='Customer', customer_name='Sender '+uuid4().hex,
			business_legal_name='Synthetic', mobile_number=number)).insert()
		identity = messages(doc.name)['sender_identity']
		self.assertEqual(identity['status'], 'Matched')
		self.assertEqual(identity['matches'], [dict(doctype='Customer', name=customer.name, label=customer.customer_name)])
		other = frappe.get_doc(dict(doctype='Customer', customer_name='Order recipient '+uuid4().hex,
			business_legal_name='Synthetic', onboarding_source='Tally')).insert()
		doc.customer = other.name; doc.save()
		self.assertEqual(messages(doc.name)['sender_identity']['matches'][0]['name'], customer.name)
		employee = frappe.get_doc(dict(doctype='Sales Employee', sales_employee_name='Sender salesperson '+uuid4().hex,
			mobile_number='8'+str(uuid4().int)[:9])).insert()
		# Restored legacy data can contain duplicates even though new forms
		# enforce global phone uniqueness. Never pick one silently in that case.
		frappe.db.set_value('Sales Employee', employee.name, 'mobile_number', number)
		identity = messages(doc.name)['sender_identity']
		self.assertEqual(identity['status'], 'Ambiguous')
		self.assertEqual({row['name'] for row in identity['matches']}, {customer.name, employee.name})
		frappe.db.set_value('Customer', customer.name, 'mobile_number', None)
		identity = messages(doc.name)['sender_identity']
		self.assertEqual(identity['matches'], [dict(doctype='Sales Employee', name=employee.name, label=employee.sales_employee_name)])

	def test_keyset_pages_have_stable_order_no_duplicates_and_revision_fence(self):
		sources=[self.source(str(i)) for i in range(4)]
		for index,source in enumerate(sources):
			frappe.db.set_value('WhatsApp Message',source.name,'intake_received_at',datetime(2026,1,1)+timedelta(minutes=index),update_modified=False)
		doc=self.request(sources)
		first=messages(doc.name,limit=2)
		self.assertEqual([row['text'] for row in first['messages']],['2','3'])
		second=messages(doc.name,cursor=first['next_cursor'],limit=2,revision=first['revision'])
		self.assertEqual([row['text'] for row in second['messages']],['0','1'])
		self.assertFalse(second['has_more'])
		frappe.db.set_value('WhatsApp Message',sources[0].name,'message','late correction',update_modified=False)
		with self.assertRaises(frappe.TimestampMismatchError):
			messages(doc.name,cursor=first['next_cursor'],revision=first['revision'])
		with self.assertRaises(frappe.ValidationError):
			messages(doc.name,cursor='outside-chat',revision=messages(doc.name)['revision'])

	def test_replaced_file_metadata_invalidates_review_even_with_same_url(self):
		source = self.source(); file = self.private_file(source.name)
		frappe.db.set_value('WhatsApp Message', source.name, 'attach', file.file_url, update_modified=False)
		doc = self.request([source]); initial = messages(doc.name)
		frappe.db.set_value('File', file.name, 'content_hash', 'replacement', update_modified=False)
		with self.assertRaises(frappe.TimestampMismatchError):
			messages(doc.name, revision=initial['revision'])

	def test_processing_uses_current_locked_evidence_instead_of_older_snapshot(self):
		from kunal_enterprises.api.order_intake_processing import handle_inquiry
		source = self.source(); doc = self.request([source], request_type='Stock Inquiry')
		revision = messages(doc.name)['revision']
		original_get = frappe.get_doc
		source = original_get('WhatsApp Message', source.name)
		frappe.db.set_value('WhatsApp Message', source.name, 'message', 'Concurrent correction', update_modified=False)
		def snapshot_read(*args, **kwargs):
			# Model repeatable-read: ordinary reads retain the old version, while
			# SELECT FOR UPDATE sees the correction committed before its lock.
			if len(args) > 1 and args[:2] == ('WhatsApp Message', source.name) and not kwargs.get('for_update'):
				return source
			return original_get(*args, **kwargs)
		with patch.object(frappe, 'get_doc', snapshot_read):
			with self.assertRaises(frappe.TimestampMismatchError):
				handle_inquiry(doc.name, str(doc.modified), revision)
		self.assertEqual(frappe.db.get_value(doc.doctype, doc.name, 'status'), 'Pending Review')

	def test_cross_chat_or_unreadable_source_outside_current_page_rejects_the_whole_view(self):
		first,second=self.source(),self.source();doc=self.request([first,second])
		frappe.db.set_value('WhatsApp Message',first.name,'from','919000000093',update_modified=False)
		with self.assertRaises(frappe.PermissionError):messages(doc.name,limit=1)
		frappe.db.set_value('WhatsApp Message',first.name,'from',self.sender,update_modified=False)
		original=frappe.model.document.Document.check_permission
		def denied(source,*args,**kwargs):
			if source.doctype=='WhatsApp Message' and source.name==first.name:
				frappe.throw('Synthetic denied source',frappe.PermissionError)
			return original(source,*args,**kwargs)
		with patch('frappe.model.document.Document.check_permission',denied):
			with self.assertRaises(frappe.PermissionError):messages(doc.name,limit=1)

	def test_only_owned_private_readable_files_have_manual_links_and_changes_invalidate_pages(self):
		first,second=self.source(),self.source();file=self.private_file(first.name)
		frappe.db.set_value('WhatsApp Message',first.name,'attach',file.file_url,update_modified=False)
		doc=self.request([first,second]);initial=messages(doc.name,limit=1)
		all_messages=messages(doc.name)
		attachment=next(row for row in all_messages['messages'] if row['name']==first.name)['attachment']
		self.assertTrue(attachment['available']);self.assertTrue(attachment['url'].startswith('/private/files/'))
		frappe.db.set_value('WhatsApp Message',second.name,'attach',file.file_url,update_modified=False)
		with self.assertRaises(frappe.TimestampMismatchError):messages(doc.name,cursor=initial['next_cursor'],revision=initial['revision'])
		second_view=next(row for row in messages(doc.name)['messages'] if row['name']==second.name)
		self.assertFalse(second_view['attachment']['available'])

	def test_unsafe_files_do_not_hide_other_messages_and_shared_url_ownership_is_filtered_before_limit(self):
		first,second=self.source(),self.source();doc=self.request([first,second])
		frappe.db.set_value('WhatsApp Message',first.name,'attach','http://[',update_modified=False)
		result=messages(doc.name)
		self.assertEqual(len(result['messages']),2)
		self.assertFalse(next(row for row in result['messages'] if row['name']==first.name)['attachment']['available'])
		file=self.private_file(first.name)
		frappe.db.bulk_insert('File',['name','file_url','is_private','attached_to_doctype','attached_to_name'],
			[('000-unrelated-'+uuid4().hex,file.file_url,1,'WhatsApp Message','other-chat') for _ in range(51)])
		frappe.db.set_value('WhatsApp Message',first.name,'attach',file.file_url,update_modified=False)
		self.assertTrue(next(row for row in messages(doc.name)['messages'] if row['name']==first.name)['attachment']['available'])

	def test_attachment_only_request_plain_links_and_page_limits_are_preserved(self):
		doc=self.request(attachments=[dict(reference_type='External Link',external_url='https://example.invalid/never-fetch',label='Shared link'),
			dict(reference_type='Location',latitude=0,longitude=0),dict(reference_type='File',label='Pending PDF',page_count=999,review_status='Needs Manual Review')])
		result=messages(doc.name)
		self.assertEqual(result['messages'],[])
		self.assertEqual(result['references'][0]['external_url'],'https://example.invalid/never-fetch')
		self.assertEqual(result['references'][1]['longitude'],0)
		self.assertTrue(result['references'][2]['manual_review'])
		with self.assertRaises(frappe.TimestampMismatchError):messages(doc.name,expected_modified='old')
		frappe.set_user('Guest')
		with self.assertRaises(frappe.PermissionError):messages(doc.name)


	def test_file_permission_and_private_path_containment_are_required(self):
		source=self.source();file=self.private_file(source.name)
		frappe.db.set_value('WhatsApp Message',source.name,'attach',file.file_url,update_modified=False)
		doc=self.request([source])
		with patch('frappe.core.doctype.file.file.File.has_permission',return_value=False):
			self.assertFalse(messages(doc.name)['messages'][0]['attachment']['available'])
		for url in ('/files/public.pdf','/private/files/../../site_config.json','/private/files/%2e%2e/site_config.json','https://example.invalid/file.pdf'):
			frappe.db.set_value('WhatsApp Message',source.name,'attach',url,update_modified=False)
			self.assertFalse(messages(doc.name)['messages'][0]['attachment']['available'])


	def test_invalid_pagination_parameters_fail_cleanly(self):
		doc=self.request([self.source()])
		for kwargs in ({'request':{}},{'request':''},{'request':doc.name,'cursor':{}},{'request':doc.name,'revision':[]}):
			with self.assertRaises(frappe.ValidationError):
				messages(**kwargs)
