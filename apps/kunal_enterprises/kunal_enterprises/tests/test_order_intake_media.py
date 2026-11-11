"""Incoming evidence commits independently of bounded, private media recovery."""
from io import BytesIO
from types import SimpleNamespace
from pypdf import PdfWriter
from unittest.mock import Mock, patch
from uuid import uuid4

import frappe
import requests
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime
from kunal_enterprises.integrations import order_intake_media as media
from kunal_enterprises.tests import test_foundation as foundation


class TestOrderIntakeMedia(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.account = frappe.get_doc({"doctype": "WhatsApp Account", "account_name": "Media " + uuid4().hex,
			"phone_id": uuid4().hex, "url": "https://graph.facebook.com", "version": "v27.0", "token": "synthetic-token"}).insert(ignore_permissions=True)
		self.doc = frappe.get_doc({"doctype": "WhatsApp Message", "type": "Incoming", "whatsapp_account": self.account.name,
			"from": "919000000079", "message_id": uuid4().hex, "message": "Attachment caption", "content_type": "document",
			"intake_media_id": "media-" + uuid4().hex, "intake_media_filename": "order.pdf"})
		self.doc.flags.intake_service_write = True
		self.doc.insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def claim(self):
		result = media.queue_download(self.doc.name)
		self.assertEqual(result["state"], "Queued")
		return frappe.db.get_value("WhatsApp Message", self.doc.name, "intake_media_job_token")

	def test_duplicate_delivery_does_not_queue_two_live_downloads(self):
		token = self.claim()
		self.assertEqual(media.queue_download(self.doc.name)["state"], "Queued")
		self.assertEqual(frappe.db.get_value("WhatsApp Message", self.doc.name, "intake_media_job_token"), token)
		self.assertEqual(frappe.db.get_value("WhatsApp Message", self.doc.name, "intake_media_attempts"), 1)

	def test_download_has_bounded_requests_and_saves_private_attachment(self):
		token = self.claim()
		frappe.db.set_value("WhatsApp Message", self.doc.name, "intake_prepare_state", "Context Ready")
		metadata = SimpleNamespace(status_code=200, raise_for_status=Mock(), close=Mock(),
			json=lambda: {"url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/test", "mime_type": "application/pdf"})
		writer = PdfWriter()
		writer.add_blank_page(width=100, height=100)
		stream = BytesIO()
		writer.write(stream)
		content = stream.getvalue()
		response = SimpleNamespace(status_code=200, headers={"Content-Length": str(len(content))}, raise_for_status=Mock(), close=Mock(), iter_content=lambda **kwargs: iter([content]))
		with patch.object(media.requests, "get", side_effect=[metadata, response]) as get:
			self.assertEqual(media.download(self.doc.name, token)["state"], "Downloaded")
			for call in get.call_args_list:
				self.assertEqual(call.kwargs["timeout"], (5, 30))
				self.assertFalse(call.kwargs["allow_redirects"])
		self.doc.reload()
		self.assertTrue(self.doc.attach.startswith("/private/files/"))
		self.assertEqual(frappe.db.get_value("File", {"file_url": self.doc.attach}, "is_private"), 1)
		self.assertEqual(self.doc.intake_prepare_state, "Pending")
		self.assertEqual(media.queue_download(self.doc.name)["state"], "Downloaded")

	def test_timeout_preserves_message_and_repeated_delivery_can_retry(self):
		token = self.claim()
		with patch.object(media.requests, "get", side_effect=requests.Timeout("secret token and provider body")):
			self.assertEqual(media.download(self.doc.name, token)["state"], "Failed")
		self.doc.reload()
		self.assertEqual(self.doc.intake_status, "Needs Attention")
		self.assertEqual(self.doc.message, "Attachment caption")
		self.assertTrue(self.doc.intake_media_id)
		self.assertNotIn("secret", self.doc.intake_media_note)
		self.assertEqual(media.queue_download(self.doc.name)["state"], "Queued")
		self.assertEqual(frappe.db.get_value("WhatsApp Message", self.doc.name, "intake_media_attempts"), 2)

	def test_manual_retry_recovers_exhausted_download_but_coordinator_cannot_initiate_it(self):
		frappe.db.set_value("WhatsApp Message", self.doc.name, {"intake_media_state": "Failed", "intake_media_attempts": 3})
		self.assertEqual(media.queue_download(self.doc.name)["state"], "Failed")
		user = foundation.TestOrderSubmission._create_role_user(self, "media-" + uuid4().hex + "@example.com", "Order Coordinator")
		frappe.set_user(user.name)
		with self.assertRaises(frappe.PermissionError):
			media.retry_download(self.doc.name)
		frappe.set_user("Administrator")
		self.assertEqual(media.retry_download(self.doc.name)["state"], "Queued")

	def test_stale_claim_recovers_and_old_worker_cannot_overwrite_it(self):
		old = self.claim()
		frappe.db.set_value("WhatsApp Message", self.doc.name, "intake_media_queued_at", add_to_date(now_datetime(), minutes=-11, as_datetime=True))
		self.assertEqual(media.queue_download(self.doc.name)["state"], "Queued")
		new = frappe.db.get_value("WhatsApp Message", self.doc.name, "intake_media_job_token")
		self.assertNotEqual(old, new)
		with patch.object(media, "_fetch") as fetch:
			self.assertEqual(media.download(self.doc.name, old)["state"], "Stale")
			fetch.assert_not_called()
		self.assertEqual(frappe.db.get_value("WhatsApp Message", self.doc.name, "intake_media_job_token"), new)

	def test_changed_claim_during_network_download_is_fenced_before_file_creation(self):
		token = self.claim()
		new = uuid4().hex
		def fetch(*args):
			frappe.db.set_value("WhatsApp Message", self.doc.name, "intake_media_job_token", new)
			return b"test bytes", "application/pdf"
		with patch.object(media, "_fetch", side_effect=fetch):
			self.assertEqual(media.download(self.doc.name, token)["state"], "Stale")
		self.assertFalse(frappe.db.get_value("WhatsApp Message", self.doc.name, "attach"))

	def test_queue_failure_is_visible_without_losing_source(self):
		token = self.claim()
		with patch.object(frappe, "enqueue", side_effect=RuntimeError("sensitive details")), patch.object(frappe.db, "commit"):
			media._publish(self.doc.name, token)
		self.doc.reload()
		self.assertEqual(self.doc.intake_media_state, "Failed")
		self.assertNotIn("sensitive", self.doc.intake_media_note)
		self.assertTrue(self.doc.intake_media_id)

	def test_arbitrary_http_media_destination_is_rejected(self):
		for url in ("http://lookaside.fbsbx.com/file", "https://127.0.0.1/file", "https://example.com/file", "https://evilfacebook.com/file"):
			with self.assertRaises(ValueError):
				media._media_url(url)
