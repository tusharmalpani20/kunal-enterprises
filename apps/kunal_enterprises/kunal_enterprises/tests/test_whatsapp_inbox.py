"""Incoming-only inbox queries, paging, sender classification and event boundaries."""
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.api import whatsapp_inbox as api
from kunal_enterprises.integrations import whatsapp_inbox as events
from kunal_enterprises.integrations import order_intake_media as media


class TestWhatsAppInbox(FrappeTestCase):
	def setUp(self):
		frappe.set_user('Administrator')
		self.account = self.make_account()
		self.other = self.make_account()
		self.number = '91' + '9' + str(uuid4().int)[:9]
		self.files = []

	def tearDown(self):
		frappe.set_user('Administrator')
		frappe.db.rollback()
		for path in self.files:
			path.unlink(missing_ok=True)

	def make_account(self):
		return frappe.get_doc(dict(doctype='WhatsApp Account', account_name='Inbox '+uuid4().hex,
			phone_id=uuid4().hex, status='Active', allow_auto_read_receipt=0)).insert(ignore_permissions=True)

	def source(self, text='Synthetic incoming', sender=None, account=None, profile='Sender', **extra):
		return frappe.get_doc(dict(doctype='WhatsApp Message', whatsapp_account=(account or self.account).name,
			type='Incoming', message=text, message_id=uuid4().hex, content_type='text', profile_name=profile,
			**{'from':self.number if sender is None else sender}, **extra)).insert(ignore_permissions=True)

	def customer(self, number=None, label=None):
		return frappe.get_doc(dict(doctype='Customer', customer_name=label or 'Inbox Customer '+uuid4().hex,
			business_legal_name='Synthetic', mobile_number=number or self.number[2:])).insert(ignore_permissions=True)

	def coordinator(self):
		return frappe.get_doc(dict(doctype='User', email='inbox-'+uuid4().hex+'@example.com',
			first_name='Inbox reviewer', enabled=1, send_welcome_email=0, user_type='System User',
			roles=[dict(role='Order Coordinator')])).insert(ignore_permissions=True)

	def test_account_scope_and_incoming_only_normalized_conversation_grouping(self):
		first=self.source('First',sender='+91 ('+self.number[2:7]+') '+self.number[7:])
		second=self.source('Second')
		self.source('Other account',account=self.other)
		out=frappe.get_doc(dict(doctype='WhatsApp Message',whatsapp_account=self.account.name,type='Outgoing',
			message='Do not show outgoing',to=self.number,content_type='text'))
		out.flags.ignore_mandatory=True;out.db_insert()
		result=api.conversations(self.account.name)
		self.assertEqual(len(result['conversations']),1)
		self.assertEqual(result['conversations'][0]['sender'],self.number)
		self.assertEqual(result['conversations'][0]['preview'],'Second')
		page=api.messages(self.account.name,self.number)
		self.assertEqual({row['name'] for row in page['messages']},{first.name,second.name})
		self.assertNotIn('Do not show outgoing',str(page))

	def test_sender_filters_search_names_phone_and_literal_wildcards_not_message_text(self):
		self.source('secret-body-not-a-search-target',profile='Salesperson % _ Name')
		self.customer(label='Registered Client')
		self.assertEqual(len(api.conversations(self.account.name,sender_type='Clients')['conversations']),1)
		self.assertFalse(api.conversations(self.account.name,sender_type='Salespersons')['conversations'])
		self.assertEqual(len(api.conversations(self.account.name,search='Registered Client')['conversations']),1)
		self.assertEqual(len(api.conversations(self.account.name,search='+91 ('+self.number[2:]+')')['conversations']),1)
		self.assertEqual(len(api.conversations(self.account.name,search='%')['conversations']),1)
		self.assertFalse(api.conversations(self.account.name,search='secret-body-not-a-search-target')['conversations'])
		self.assertFalse(api.conversations(self.account.name,search='missing%')['conversations'])
		employee=frappe.get_doc(dict(doctype='Sales Employee',sales_employee_name='Ambiguous sender',
			mobile_number='8'+str(uuid4().int)[:9])).insert()
		frappe.db.set_value('Sales Employee',employee.name,'mobile_number',self.number[2:])
		unknown=api.conversations(self.account.name,sender_type='Unknown')['conversations']
		self.assertEqual(unknown[0]['identity']['status'],'Ambiguous')
		self.assertFalse(api.conversations(self.account.name,sender_type='Clients')['conversations'])
		self.assertFalse(api.conversations(self.account.name,sender_type='Salespersons')['conversations'])

	def test_unknown_nonphone_ids_never_match_blank_master_phones(self):
		self.source(sender='future-sender',profile='Future sender')
		frappe.get_doc(dict(doctype='Customer',customer_name='No phone '+uuid4().hex,
			business_legal_name='Synthetic',onboarding_source='Tally')).insert()
		row=api.conversations(self.account.name,sender_type='Unknown')['conversations'][0]
		self.assertEqual(row['identity']['status'],'Unknown')
		self.assertFalse(api.conversations(self.account.name,sender_type='Clients')['conversations'])

	def test_conversation_cursor_is_stable_with_ties_and_new_activity(self):
		for index in range(3):
			source=self.source(str(index),sender='91900000001'+str(index))
			frappe.db.set_value('WhatsApp Message',source.name,'creation',datetime(2026,1,1))
		first=api.conversations(self.account.name,limit=1)
		second=api.conversations(self.account.name,cursor=first['next_cursor'],limit=1)
		third=api.conversations(self.account.name,cursor=second['next_cursor'],limit=1)
		self.assertEqual(len({page['conversations'][0]['sender'] for page in [first,second,third]}),3)
		self.assertFalse(third['has_more'])
		with self.assertRaises(frappe.ValidationError):api.conversations(self.other.name,cursor=first['next_cursor'])
		with self.assertRaises(frappe.ValidationError):api.conversations(self.account.name,search='different',cursor=first['next_cursor'])

	def test_history_before_after_pages_and_empty_after_keep_canonical_profile(self):
		sources=[self.source(str(index),profile='Known profile' if index==0 else '') for index in range(4)]
		for index,source in enumerate(sources):
			frappe.db.set_value('WhatsApp Message',source.name,'creation',datetime(2026,1,1)+timedelta(seconds=index))
		first=api.messages(self.account.name,self.number,limit=2)
		self.assertEqual([row['text'] for row in first['messages']],['2','3'])
		older=api.messages(self.account.name,self.number,before=first['next_cursor'],limit=2)
		self.assertEqual([row['text'] for row in older['messages']],['0','1'])
		self.assertFalse(older['has_more'])
		new=self.source('new',profile='')
		frappe.db.set_value('WhatsApp Message',new.name,'creation',datetime(2026,1,2))
		after=api.messages(self.account.name,self.number,after=first['newest_cursor'])
		self.assertEqual([row['text'] for row in after['messages']],['new'])
		empty=api.messages(self.account.name,self.number,after=after['newest_cursor'])
		self.assertFalse(empty['messages']);self.assertEqual(empty['sender_profile_name'],'Known profile')
		self.assertEqual(empty['newest_cursor'],after['newest_cursor'])
		chat=api.conversations(self.account.name,search='Known profile')['conversations']
		self.assertEqual(chat[0]['profile_name'],'Known profile')
		with self.assertRaises(frappe.ValidationError):api.messages(self.other.name,self.number,before=first['next_cursor'])
		with self.assertRaises(frappe.ValidationError):api.messages(self.account.name,'different',before=first['next_cursor'])
		with self.assertRaises(frappe.ValidationError):api.messages(self.account.name,self.number,before='bad-cursor')

	def test_refresh_names_updates_owned_media_and_removes_other_chat_names(self):
		source=self.source('Before');other=self.source('Other',account=self.other)
		page=api.messages(self.account.name,self.number)
		frappe.db.set_value('WhatsApp Message',source.name,'message','Updated',update_modified=False)
		result=api.messages(self.account.name,self.number,after=page['newest_cursor'],refresh_names=frappe.as_json([source.name,other.name,'missing']))
		self.assertEqual([row['text'] for row in result['refreshed_messages']],['Updated'])
		self.assertEqual(set(result['removed_names']),{other.name,'missing'})
		self.assertNotIn('Other',str(result['refreshed_messages']))
		with self.assertRaises(frappe.ValidationError):api.messages(self.account.name,self.number,refresh_names=['x']*1001)

	def test_read_queries_do_not_mark_read_send_or_return_payload_secrets(self):
		source=self.source('Text')
		frappe.db.set_value('WhatsApp Message',source.name,dict(status='received',intake_raw_payload='TOP-SECRET-PAYLOAD'),update_modified=False)
		before=frappe.db.get_value('WhatsApp Message',source.name,['status','modified'],as_dict=True)
		with patch('requests.sessions.Session.request',side_effect=AssertionError('No network')):
			api.accounts();api.conversations(self.account.name);result=api.messages(self.account.name,self.number)
		self.assertNotIn('TOP-SECRET-PAYLOAD',str(result))
		self.assertEqual(frappe.db.get_value('WhatsApp Message',source.name,['status','modified'],as_dict=True),before)

	def test_private_files_belong_to_this_source_and_no_remote_media_is_loaded(self):
		source=self.source('Document');other=self.source('Other',account=self.other)
		path=Path(frappe.get_site_path('private','files','inbox-'+uuid4().hex+'.pdf'));path.write_bytes(b'%PDF synthetic')
		self.files.append(path)
		file=frappe.get_doc(dict(doctype='File',name='inbox-file-'+uuid4().hex,file_name=path.name,
			file_url='/private/files/'+path.name,is_private=1,attached_to_doctype='WhatsApp Message',attached_to_name=source.name))
		file.db_insert();frappe.db.set_value('WhatsApp Message',source.name,'attach',file.file_url,update_modified=False)
		self.assertTrue(api.messages(self.account.name,self.number)['messages'][0]['attachment']['available'])
		frappe.db.set_value('File',file.name,'attached_to_name',other.name,update_modified=False)
		self.assertFalse(api.messages(self.account.name,self.number)['messages'][0]['attachment']['available'])

	def test_account_user_permissions_and_guest_denial(self):
		self.source();self.source(account=self.other)
		user=self.coordinator()
		frappe.get_doc(dict(doctype='User Permission',user=user.name,allow='WhatsApp Account',
			for_value=self.account.name,apply_to_all_doctypes=1)).insert(ignore_permissions=True)
		frappe.set_user(user.name)
		self.assertEqual([row['name'] for row in api.accounts()['accounts']],[self.account.name])
		self.assertEqual(len(api.conversations(self.account.name)['conversations']),1)
		with self.assertRaises(frappe.PermissionError):api.messages(self.other.name,self.number)
		frappe.set_user('Guest')
		with self.assertRaises(frappe.PermissionError):api.accounts()
		with self.assertRaises(frappe.PermissionError):api.conversations(self.account.name)

	def test_per_document_message_denial_rejects_chat_history(self):
		source=self.source()
		original=frappe.model.document.Document.check_permission
		def denied(doc,*args,**kwargs):
			if doc.doctype=='WhatsApp Message' and doc.name==source.name:frappe.throw('No source access',frappe.PermissionError)
			return original(doc,*args,**kwargs)
		with patch('frappe.model.document.Document.check_permission',denied):
			with self.assertRaises(frappe.PermissionError):api.messages(self.account.name,self.number)

	def test_events_are_account_scoped_content_free_and_after_commit(self):
		source=self.source('Private content')
		with patch.object(frappe,'publish_realtime') as publish:
			events.changed(source)
		publish.assert_called_once_with('whatsapp_inbox_changed',{'account':self.account.name,'message':source.name},
			doctype='WhatsApp Account',docname=self.account.name,after_commit=True)
		source.type='Outgoing'
		with patch.object(frappe,'publish_realtime') as publish:
			events.changed(source)
		publish.assert_not_called()

	def test_media_failure_queues_the_same_after_commit_invalidation(self):
		source=self.source()
		frappe.db.set_value('WhatsApp Message',source.name,dict(intake_media_state='Queued',intake_media_job_token='fixture'))
		with patch.object(frappe,'publish_realtime') as publish:
			media._fail(source.name,'fixture','Synthetic failure')
		self.assertTrue(any(call.args and call.args[0]=='whatsapp_inbox_changed' and call.kwargs.get('after_commit') for call in publish.call_args_list))


	def test_literal_search_symbols_do_not_match_every_conversation(self):
		self.source(profile='100% real_name')
		self.source(profile='Plain sender',sender='918'+str(uuid4().int)[:9])
		for term in ('%', '_'):
			rows=api.conversations(self.account.name,search=term)['conversations']
			self.assertEqual([row['sender'] for row in rows],[self.number])
		self.assertFalse(api.conversations(self.account.name,search="' OR 1=1 --")['conversations'])

	def test_actual_incoming_insert_runs_the_after_commit_event_hook(self):
		frappe.clear_cache()
		with patch.object(frappe,'publish_realtime') as publish:
			source=self.source('Synthetic hook test')
		calls=[call for call in publish.call_args_list if call.args and call.args[0]=='whatsapp_inbox_changed']
		self.assertEqual(len(calls),1)
		self.assertEqual(calls[0].args[1],{'account':source.whatsapp_account,'message':source.name})
		self.assertTrue(calls[0].kwargs['after_commit'])

	def test_successful_download_invalidates_chat_without_sending_anything(self):
		from kunal_enterprises.api.orders import _build_plain_text_pdf
		source=self.source('Media caption')
		frappe.db.set_value('WhatsApp Message',source.name,dict(intake_media_id='synthetic',
			intake_media_filename='Inbox-'+uuid4().hex+'.pdf',intake_media_state='Queued',intake_media_job_token='fixture'))
		with patch.object(media,'_fetch',return_value=(_build_plain_text_pdf('Inbox '+uuid4().hex),'application/pdf')), patch.object(frappe,'publish_realtime') as publish:
			self.assertEqual(media.download(source.name,'fixture')['state'],'Downloaded')
		self.assertTrue(any(call.args and call.args[0]=='whatsapp_inbox_changed' and call.kwargs.get('after_commit') for call in publish.call_args_list))
		source.reload()
		self.assertTrue(api.messages(self.account.name,self.number)['messages'][0]['attachment']['available'])


	def test_default_incoming_account_is_returned_only_when_readable(self):
		frappe.db.set_single_value('WhatsApp Settings','default_incoming_account',self.other.name)
		self.assertEqual(api.accounts()['default_account'],self.other.name)
		user=self.coordinator()
		frappe.get_doc(dict(doctype='User Permission',user=user.name,allow='WhatsApp Account',
			for_value=self.account.name,apply_to_all_doctypes=1)).insert(ignore_permissions=True)
		frappe.set_user(user.name)
		self.assertIsNone(api.accounts()['default_account'])
		self.assertNotIn(self.other.name,str(api.accounts()))

	def test_late_committed_message_can_be_recovered_by_targeted_refresh(self):
		first=self.source('Already viewed')
		page=api.messages(self.account.name,self.number)
		late=self.source('Created earlier, became visible later')
		frappe.db.set_value('WhatsApp Message',late.name,'creation',datetime(2000,1,1))
		result=api.messages(self.account.name,self.number,after=page['newest_cursor'],refresh_names=[late.name])
		self.assertFalse(result['messages'])
		self.assertEqual([row['name'] for row in result['refreshed_messages']],[late.name])


	def test_nontext_provider_metadata_is_hidden_but_captions_and_literal_text_json_remain(self):
		from html import escape
		payload={'id':'provider-id','mime_type':'image/jpeg','sha256':'private-hash','url':'https://cdn.invalid/private-signed?token=secret'}
		source=self.source(escape(frappe.as_json(payload)))
		frappe.db.set_value('WhatsApp Message',source.name,dict(content_type='image',intake_original_type='image'))
		page=api.messages(self.account.name,self.number)
		self.assertEqual(page['messages'][0]['text'],'')
		self.assertNotIn('private-signed',str(page))
		self.assertNotIn('private-hash',str(api.conversations(self.account.name)))
		payload['caption']='Please send the items in this photo'
		envelope={'entry':[{'changes':[{'value':{'messages':[{'type':'image','image':payload}]}}]}]}
		frappe.db.set_value('WhatsApp Message',source.name,'message',escape(frappe.as_json(envelope)))
		self.assertEqual(api.messages(self.account.name,self.number)['messages'][0]['text'],payload['caption'])
		self.assertEqual(api.conversations(self.account.name)['conversations'][0]['preview'],payload['caption'])
		literal=frappe.as_json({'id':'user-text-order','url':'https://example.com/reference'})
		frappe.db.set_value('WhatsApp Message',source.name,dict(message=literal,content_type='text',intake_original_type='text'))
		self.assertEqual(api.messages(self.account.name,self.number)['messages'][0]['text'],literal)

	def test_contact_objects_show_name_and_phone_instead_of_raw_json(self):
		payload=[{'name':{'formatted_name':'Test Contact'},'phones':[{'phone':'+91 9000000000','wa_id':'provider-private-id'}]}]
		source=self.source(frappe.as_json(payload))
		frappe.db.set_value('WhatsApp Message',source.name,dict(content_type='contacts',intake_original_type='contacts'))
		text=api.messages(self.account.name,self.number)['messages'][0]['text']
		self.assertEqual(text,'Test Contact · +91 9000000000')
		self.assertNotIn('provider-private-id',text)

	def test_captured_contacts_use_plain_names_and_wa_id_only_numbers_in_chat_and_preview(self):
		cards = [dict(name=dict(formatted_name='A&B Glass'), phones=[dict(wa_id='919998887776')], vcard='PRIVATE VCARD')]
		source = self.source('A&amp;B Glass · 919998887776')
		frappe.db.set_value('WhatsApp Message', source.name, dict(content_type='contact', intake_original_type='contacts',
			intake_raw_payload=frappe.as_json(dict(message=dict(contacts=cards)))))
		result = api.messages(self.account.name, self.number)['messages'][0]
		self.assertEqual(result['text'], 'A&B Glass · 919998887776')
		self.assertEqual(result['contacts'][0]['phones'][0]['phone'], '919998887776')
		self.assertEqual(api.conversations(self.account.name)['conversations'][0]['preview'], 'A&B Glass · 919998887776')
		self.assertNotIn('PRIVATE VCARD', str(result))

	def test_attachment_type_uses_captured_mime_when_file_extension_is_missing(self):
		source=self.source('Image caption')
		path=Path(frappe.get_site_path('private','files','inbox-'+uuid4().hex));path.write_bytes(b'Synthetic image')
		self.files.append(path)
		file=frappe.get_doc(dict(doctype='File',name='inbox-file-'+uuid4().hex,file_name='Attachment',
			file_url='/private/files/'+path.name,is_private=1,attached_to_doctype='WhatsApp Message',attached_to_name=source.name))
		file.db_insert()
		frappe.db.set_value('WhatsApp Message',source.name,dict(attach=file.file_url,intake_media_mime='image/jpeg'))
		self.assertEqual(api.messages(self.account.name,self.number)['messages'][0]['attachment']['file_type'],'image/jpeg')


	def test_moving_incoming_message_invalidates_old_and_new_account_after_commit(self):
		source=self.source()
		source.whatsapp_account=self.other.name
		with patch.object(frappe,'publish_realtime') as publish:
			source.save(ignore_permissions=True)
		calls=[call for call in publish.call_args_list if call.args and call.args[0]=='whatsapp_inbox_changed']
		self.assertEqual({call.args[1]['account'] for call in calls},{self.account.name,self.other.name})
		self.assertTrue(all(call.kwargs.get('after_commit') and call.args[1]['message']==source.name for call in calls))
		self.assertEqual(api.messages(self.account.name,self.number,refresh_names=[source.name])['removed_names'],[source.name])

	def test_deletion_invalidates_only_its_account_after_commit(self):
		frappe.clear_cache()
		source=self.source()
		with patch.object(frappe,'publish_realtime') as publish:
			frappe.delete_doc('WhatsApp Message',source.name,ignore_permissions=True)
		calls=[call for call in publish.call_args_list if call.args and call.args[0]=='whatsapp_inbox_changed']
		self.assertEqual(len(calls),1)
		self.assertEqual(calls[0].args[1],{'account':self.account.name,'message':source.name})
		self.assertTrue(calls[0].kwargs['after_commit'])


	def test_provider_envelope_uses_this_records_message_id_not_the_first_caption(self):
		source=self.source()
		payload={'entry':[{'changes':[{'value':{'messages':[
			{'id':'other-provider-id','type':'image','image':{'id':'media-other','mime_type':'image/jpeg','caption':'Other message caption'}},
			{'id':source.message_id,'type':'image','image':{'id':'media-this','mime_type':'image/jpeg','caption':'This message caption'}}
		]}}]}]}
		frappe.db.set_value('WhatsApp Message',source.name,dict(message=frappe.as_json(payload),content_type='image',intake_original_type='image'))
		self.assertEqual(api.messages(self.account.name,self.number)['messages'][0]['text'],'This message caption')
		self.assertEqual(api.conversations(self.account.name)['conversations'][0]['preview'],'This message caption')
		frappe.db.set_value('WhatsApp Message',source.name,'message_id','no-envelope-match')
		self.assertEqual(api.messages(self.account.name,self.number)['messages'][0]['text'],'')
		self.assertEqual(api.conversations(self.account.name)['conversations'][0]['preview'],'Image')

	def test_reply_context_resolves_history_scope_and_missing_original(self):
		original=self.source('Original body')
		reply=self.source('Reply',reply_to_message_id=original.message_id)
		page=api.messages(self.account.name,self.number,limit=1)
		self.assertEqual(page['messages'][0]['reply_context']['summary'],'Original body')
		self.assertEqual(page['messages'][0]['reply_context']['target_name'],original.name)
		self.source('Wrong account',account=self.other)
		wrong=self.source('Wrong sender',sender='919123456789')
		frappe.db.set_value('WhatsApp Message',reply.name,'reply_to_message_id',wrong.message_id)
		context=api.messages(self.account.name,self.number)['messages'][1]['reply_context']
		self.assertFalse(context['available']);self.assertIsNone(context['target_name'])
		self.assertNotIn('Wrong sender',str(context))
		frappe.db.set_value('WhatsApp Message',reply.name,'reply_to_message_id','missing-provider')
		self.assertIn('not stored',api.messages(self.account.name,self.number)['messages'][1]['reply_context']['summary'])

	def test_reactions_update_remove_and_decorate_target_across_pages(self):
		original=self.source('Hello')
		def react(emoji):
			event=self.source(emoji or 'removed',reply_to_message_id=original.message_id)
			frappe.db.set_value('WhatsApp Message',event.name,dict(intake_original_type='reaction',
				intake_raw_payload=frappe.as_json({'message':{'reaction':{'message_id':original.message_id,'emoji':emoji}}})))
			return event
		first=react('👍')
		page=api.messages(self.account.name,self.number,limit=1)
		event=page['messages'][0]
		self.assertEqual(event['content_type'],'reaction');self.assertIsNone(event['reply_context'])
		self.assertEqual(event['reaction']['target_name'],original.name)
		older=api.messages(self.account.name,self.number,before=page['next_cursor'])
		self.assertEqual(older['messages'][0]['reactions'][0]['emoji'],'👍')
		react('❤️')
		self.assertEqual(api.messages(self.account.name,self.number)['messages'][0]['reactions'][0]['emoji'],'❤️')
		react('')
		result=api.messages(self.account.name,self.number)
		self.assertEqual(result['messages'][0]['reactions'],[])
		self.assertTrue(result['messages'][-1]['reaction']['removed'])
		self.assertEqual(api.conversations(self.account.name)['conversations'][0]['preview'],'Removed a reaction')

	def test_reply_outgoing_context_never_becomes_main_history_and_checks_acl(self):
		out=frappe.get_doc(dict(doctype='WhatsApp Message',whatsapp_account=self.account.name,type='Outgoing',
			message='Business answer',to=self.number,content_type='text',message_id=uuid4().hex))
		out.flags.ignore_mandatory=True;out.db_insert()
		with self.assertRaises(frappe.DoesNotExistError):api.message_context(self.account.name,self.number,out.name)
		reply=self.source('Following up',reply_to_message_id=out.message_id)
		page=api.messages(self.account.name,self.number)
		self.assertEqual([row['name'] for row in page['messages']],[reply.name])
		self.assertEqual(page['messages'][0]['reply_context']['summary'],'Business answer')
		context=api.message_context(self.account.name,self.number,out.name)
		self.assertTrue(context['context_only']);self.assertEqual(context['messages'],[])
		original=frappe.model.document.Document.has_permission
		def denied(doc,*args,**kwargs):
			return False if doc.doctype=='WhatsApp Message' and doc.name==out.name else original(doc,*args,**kwargs)
		with patch('frappe.model.document.Document.has_permission',denied):
			self.assertFalse(api.messages(self.account.name,self.number)['messages'][0]['reply_context']['available'])
			with self.assertRaises(frappe.DoesNotExistError):api.message_context(self.account.name,self.number,out.name)

	def test_context_window_has_cursors_and_duplicate_provider_reference_is_unavailable(self):
		original=self.source('Target')
		reply=self.source('Reply',reply_to_message_id=original.message_id)
		context=api.message_context(self.account.name,self.number,original.name)
		self.assertEqual([row['name'] for row in context['messages']],[original.name,reply.name])
		self.assertIsNotNone(context['next_cursor']);self.assertIsNotNone(context['newest_cursor'])
		duplicate=self.source('Duplicate')
		frappe.db.set_value('WhatsApp Message',duplicate.name,'message_id',original.message_id)
		rows=api.messages(self.account.name,self.number)['messages']
		self.assertFalse(next(row for row in rows if row['name']==reply.name)['reply_context']['available'])

	def test_stale_capture_sender_key_does_not_relabel_or_hide_chat(self):
		source=self.source('Current sender message')
		stale='919123456789'
		frappe.db.set_value('WhatsApp Message',source.name,'intake_sender_key',stale,update_modified=False)
		chats=api.conversations(self.account.name)['conversations']
		self.assertEqual([row['sender'] for row in chats],[self.number])
		self.assertEqual([row['name'] for row in api.messages(self.account.name,self.number)['messages']],[source.name])
		self.assertFalse(api.messages(self.account.name,stale)['messages'])

	def test_delayed_reaction_does_not_override_later_removal(self):
		original=self.source('Hello')
		for emoji, received in [('',datetime(2026,1,2)), ('👍',datetime(2026,1,1))]:
			event=self.source('Reaction event')
			# Legacy capture can retain the target only inside the raw payload.
			frappe.db.set_value('WhatsApp Message',event.name,dict(intake_original_type='reaction',
				intake_received_at=received, intake_raw_payload=frappe.as_json({'message':{
					'reaction':{'message_id':original.message_id,'emoji':emoji}}})))
		result=api.messages(self.account.name,self.number)
		self.assertEqual(result['messages'][0]['reactions'],[])
