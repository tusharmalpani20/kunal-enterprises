"""Local attachment limits preserve unread evidence without fetching external URLs."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from unittest import TestCase
from unittest.mock import Mock, patch

from PIL import Image
from pypdf import PdfWriter

from kunal_enterprises.integrations import order_intake_ai_media as media


class TestOrderIntakeAIMedia(TestCase):
	def setUp(self):
		self.temp = TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.root = Path(self.temp.name)
		self.message = dict(name="MSG-1", attach="/private/files/source.pdf", content_type="document")
		self.config = dict(pdf_page_limit=2)
		self.file = dict(name="FILE-1", file_url=self.message["attach"], is_private=1,
			attached_to_doctype="WhatsApp Message", attached_to_name="MSG-1")

	def build(self, content, suffix="source.pdf", metadata=None):
		(self.root / suffix).write_bytes(content)
		self.message["attach"] = "/private/files/" + suffix
		self.file["file_url"] = self.message["attach"]
		with patch.object(media.frappe, "get_site_path", return_value=str(self.root)), \
			patch.object(media.frappe, "db", Mock(get_value=Mock(return_value=self.file))):
			return media.build_media([self.message], self.config, metadata=metadata)

	def pdf(self, pages, encrypted=False):
		writer = PdfWriter()
		for _ in range(pages):
			writer.add_blank_page(width=100, height=100)
		if encrypted:
			writer.encrypt("synthetic-test-password")
		stream = BytesIO()
		writer.write(stream)
		return stream.getvalue()

	def test_small_pdf_becomes_binary_input_but_large_and_encrypted_stay_manual(self):
		content = self.pdf(2)
		blobs, warnings = self.build(content)
		self.assertEqual(blobs["MSG-1"][0].data, content)
		self.assertEqual(blobs["MSG-1"][0].media_type, "application/pdf")
		self.assertFalse(warnings)
		for content in (self.pdf(3), self.pdf(1, encrypted=True), b"%PDF-invalid"):
			blobs, warnings = self.build(content)
			self.assertFalse(blobs)
			self.assertTrue(warnings["MSG-1"])

	def test_real_image_validated_by_content_not_extension(self):
		stream = BytesIO()
		Image.new("RGB", (4, 4), "white").save(stream, format="PNG")
		blobs, warnings = self.build(stream.getvalue(), "source.png")
		self.assertEqual(blobs["MSG-1"][0].media_type, "image/png")
		self.assertFalse(warnings)
		blobs, warnings = self.build(b"not an image", "source.png")
		self.assertFalse(blobs)
		self.assertTrue(warnings["MSG-1"])

	def test_public_unrelated_and_external_files_never_read(self):
		for change in ({"is_private": 0}, {"attached_to_name": "OTHER"}):
			self.file.update(change)
			blobs, warnings = self.build(self.pdf(1))
			self.assertFalse(blobs)
			self.assertTrue(warnings["MSG-1"])
		self.message["attach"] = "https://example.com/order.pdf"
		with patch.object(media.frappe, "db", Mock()) as database:
			blobs, warnings = media.build_media([self.message], self.config)
			database.get_value.assert_not_called()
		self.assertFalse(blobs)
		self.assertTrue(warnings["MSG-1"])

	def test_byte_budget_and_missing_download_are_visible(self):
		with patch.object(media, "MAX_FILE_BYTES", 32):
			blobs, warnings = self.build(self.pdf(1))
		self.assertFalse(blobs)
		self.assertTrue(warnings["MSG-1"])
		self.message.update(attach=None, intake_original_type="image", intake_media_id="MEDIA-1")
		blobs, warnings = media.build_media([self.message], self.config)
		self.assertFalse(blobs)
		self.assertTrue(warnings["MSG-1"])

	def rejected_batch(self, total, content):
		(self.root / "source.pdf").write_bytes(content)
		messages = [dict(name=f"MSG-{index}", attach="/private/files/source.pdf", content_type="document")
			for index in range(total)]
		def lookup(doctype, filters, *args, **kwargs):
			return dict(name="FILE-" + filters["attached_to_name"], **filters)
		with patch.object(media.frappe, "get_site_path", return_value=str(self.root)), \
			patch.object(media.frappe, "db", Mock(get_value=Mock(side_effect=lookup))), \
			patch.object(media, "_inspect", wraps=media._inspect) as inspect:
			result = media.build_media(messages, self.config)
			return result, inspect.call_count

	def test_rejected_pdfs_count_towards_the_job_file_limit(self):
		(blobs, warnings), parsed = self.rejected_batch(12, self.pdf(3))
		self.assertFalse(blobs)
		self.assertEqual(len(warnings), 12)
		self.assertEqual(parsed, media.MAX_JOB_FILES)
		self.assertIn("budget", warnings["MSG-11"][0])

	def test_rejected_pdfs_count_towards_the_job_read_byte_limit(self):
		content = self.pdf(3)
		with patch.object(media, "MAX_JOB_BYTES", len(content) * 2):
			(blobs, warnings), parsed = self.rejected_batch(4, content)
		self.assertFalse(blobs)
		self.assertEqual(len(warnings), 4)
		self.assertEqual(parsed, 2)
		self.assertIn("budget", warnings["MSG-2"][0])

	def test_expired_job_deadline_skips_all_attachment_reads(self):
		messages = [dict(self.message, name=f"MSG-{index}") for index in range(3)]
		with patch.object(media.frappe, "db", Mock()) as database:
			blobs, warnings = media.build_media(messages, self.config, deadline=monotonic() - 1)
			database.get_value.assert_not_called()
		self.assertFalse(blobs)
		self.assertEqual(set(warnings), {row["name"] for row in messages})
		self.assertTrue(all("time limit" in note[0] for note in warnings.values()))

	def test_pdf_page_count_sidecar_includes_over_limit_files_without_reparsing(self):
		for pages in (2, 3):
			metadata = {}
			with patch.object(media, 'PdfReader', wraps=media.PdfReader) as parser:
				blobs, warnings = self.build(self.pdf(pages), metadata=metadata)
				parser.assert_called_once()
			self.assertEqual(metadata, {'MSG-1': {'page_count': pages}})
			self.assertEqual(bool(blobs), pages <= 2)
			self.assertEqual(bool(warnings), pages > 2)
