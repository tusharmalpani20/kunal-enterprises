"""Request-scoped local thumbnails retain the evidence review boundary."""
import io
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image
from pypdf import PdfWriter

from kunal_enterprises.api.order_intake_conversation import messages, preview
from kunal_enterprises.integrations import whatsapp_inbox_previews as service


class TestOrderIntakePreviews(FrappeTestCase):
	def setUp(self):
		frappe.set_user('Administrator')
		self.account = frappe.get_doc(dict(doctype='WhatsApp Account', account_name='Intake preview '+uuid4().hex,
			phone_id=uuid4().hex, status='Active', allow_auto_read_receipt=0)).insert(ignore_permissions=True)
		self.number = '919000000094'
		self.sources = []
		self.paths = set()
		self.old_commit = frappe.local.flags.commit

	def tearDown(self):
		frappe.set_user('Administrator')
		for row in frappe.get_all('File', filters={'attached_to_doctype': 'WhatsApp Message',
			'attached_to_name': ['in', self.sources or ['']]}, fields=['file_url']):
			self.paths.add(Path(frappe.get_site_path(row.file_url.lstrip('/'))))
		frappe.db.rollback()
		for path in self.paths:
			path.unlink(missing_ok=True)
		frappe.local.flags.commit = self.old_commit

	def source(self, pdf=False, small_png=False):
		source = frappe.get_doc(dict(doctype='WhatsApp Message', whatsapp_account=self.account.name,
			type='Incoming', message='Two sheets', message_id=uuid4().hex,
			content_type='document' if pdf else 'image', **{'from': self.number})).insert(ignore_permissions=True)
		self.sources.append(source.name)
		output = io.BytesIO()
		if pdf:
			writer = PdfWriter(); writer.add_blank_page(width=400, height=800)
			writer.add_blank_page(width=800, height=400); writer.write(output)
		else:
			Image.new('RGB', (120, 80) if small_png else (800, 400), 'red').save(output, 'PNG' if small_png else 'JPEG')
		file = frappe.get_doc(dict(doctype='File', file_name=uuid4().hex+('.pdf' if pdf else '.png' if small_png else '.jpg'),
			is_private=1, attached_to_doctype='WhatsApp Message', attached_to_name=source.name,
			content=output.getvalue())).insert(ignore_permissions=True)
		self.paths.add(Path(file.get_full_path()))
		frappe.db.set_value('WhatsApp Message', source.name, dict(attach=file.file_url,
			intake_media_mime='application/pdf' if pdf else 'image/png' if small_png else 'image/jpeg'), update_modified=False)
		return source, file

	def request(self, source):
		return frappe.get_doc(dict(doctype='Order Intake Request', whatsapp_account=self.account.name,
			sender_number=self.number, source_messages=[dict(message=source.name)])).insert()

	def args(self, doc, source):
		data = messages(doc.name)
		return dict(request=doc.name, name=source.name, revision=data['revision'], expected_modified=data['modified'])

	def test_image_and_pdf_previews_are_private_cached_and_do_not_change_sources_or_revision(self):
		for pdf in (False, True):
			source, _ = self.source(pdf=pdf); doc = self.request(source)
			args = self.args(doc, source)
			before = frappe.get_doc('WhatsApp Message', source.name).as_dict()
			result = preview(**args)
			self.assertTrue(result['available'], result)
			self.assertTrue(result['url'].startswith('/private/files/'))
			self.assertEqual(result['kind'], 'pdf' if pdf else 'image')
			self.assertEqual(result['height'], 480 if pdf else 240)
			with patch.object(service, '_render', side_effect=AssertionError('Unexpected rendering')):
				self.assertEqual(preview(**args), result)
			self.assertEqual(frappe.get_doc('WhatsApp Message', source.name).as_dict(), before)
			self.assertEqual(messages(doc.name)['revision'], args['revision'])

	def test_byte_identical_small_png_does_not_invalidate_the_review_revision(self):
		source, _ = self.source(small_png=True); doc = self.request(source)
		args = self.args(doc, source)
		self.assertTrue(preview(**args)['available'])
		self.assertEqual(messages(doc.name)['revision'], args['revision'])
		self.assertTrue(preview(**args)['available'])

	def test_unlinked_message_in_same_chat_is_rejected_before_preview_service(self):
		source, _ = self.source(); other, _ = self.source(); doc = self.request(source)
		args = self.args(doc, source); args['name'] = other.name
		with patch.object(service, 'get_preview', side_effect=AssertionError('Must not render unrelated message')):
			with self.assertRaises(frappe.PermissionError):
				preview(**args)

	def test_changed_source_file_and_request_reject_stale_thumbnail_requests(self):
		source, file = self.source(); doc = self.request(source)
		args = self.args(doc, source)
		with patch.object(service, 'get_preview', side_effect=AssertionError('Must not render stale evidence')):
			frappe.db.set_value('WhatsApp Message', source.name, 'message', 'Changed', update_modified=False)
			with self.assertRaises(frappe.TimestampMismatchError): preview(**args)
			args = self.args(doc, source)
			frappe.db.set_value('File', file.name, 'content_hash', 'changed', update_modified=False)
			with self.assertRaises(frappe.TimestampMismatchError): preview(**args)
			args = self.args(doc, source); args['expected_modified'] = 'old'
			with self.assertRaises(frappe.TimestampMismatchError): preview(**args)

	def test_request_source_and_file_permissions_are_rechecked(self):
		source, file = self.source(); doc = self.request(source); args = self.args(doc, source)
		from frappe.model.document import Document
		original = Document.check_permission
		for doctype, name in [('Order Intake Request', doc.name), ('WhatsApp Message', source.name), ('WhatsApp Account', self.account.name)]:
			def denied(record, *values, **kwargs):
				if record.doctype == doctype and record.name == name:
					frappe.throw('Denied', frappe.PermissionError)
				return original(record, *values, **kwargs)
			with patch.object(Document, 'check_permission', denied):
				with self.assertRaises(frappe.PermissionError): preview(**args)
		with patch('frappe.core.doctype.file.file.File.has_permission', return_value=False):
			self.assertFalse(preview(**args)['available'])
		frappe.set_user('Guest')
		with self.assertRaises(frappe.PermissionError): preview(**args)

	def test_saved_cross_chat_sources_and_invalid_revision_parameters_fail_closed(self):
		source, _ = self.source(); doc = self.request(source); args = self.args(doc, source)
		for field, value in [('request', {}), ('name', {}), ('revision', ''), ('revision', {}), ('expected_modified', '')]:
			with self.assertRaises(frappe.ValidationError): preview(**{**args, field: value})
		frappe.db.set_value('WhatsApp Message', source.name, 'from', '919999999999', update_modified=False)
		with self.assertRaises(frappe.PermissionError): preview(**args)
