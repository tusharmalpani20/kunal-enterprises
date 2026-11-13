"""Real local media rendering, cache safety and permission boundaries."""
import io
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image
from pypdf import PdfWriter

from kunal_enterprises.api.whatsapp_inbox_previews import preview
from kunal_enterprises.integrations import whatsapp_inbox_previews as service


class TestWhatsAppInboxPreviews(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.account = frappe.get_doc(dict(doctype="WhatsApp Account", account_name="Preview " + uuid4().hex,
            phone_id=uuid4().hex, status="Active", allow_auto_read_receipt=0)).insert(ignore_permissions=True)
        self.number = "919000000094"
        self.paths = set()
        self.old_commit = frappe.local.flags.commit

    def tearDown(self):
        frappe.set_user("Administrator")
        for row in frappe.get_all("File", filters={"attached_to_doctype": "WhatsApp Message"}, fields=["file_url", "attached_to_name"]):
            if row.attached_to_name in getattr(self, "sources", []):
                self.paths.add(Path(frappe.get_site_path(row.file_url.lstrip("/"))))
        frappe.db.rollback()
        for path in self.paths:
            path.unlink(missing_ok=True)
        frappe.local.flags.commit = self.old_commit

    def source(self, content, mime="image/jpeg", filename="photo.jpg"):
        source = frappe.get_doc(dict(doctype="WhatsApp Message", whatsapp_account=self.account.name, type="Incoming",
            message="Preview test", message_id=uuid4().hex, content_type="image", **{"from": self.number})).insert(ignore_permissions=True)
        self.sources = getattr(self, "sources", []) + [source.name]
        file = frappe.get_doc(dict(doctype="File", file_name=uuid4().hex + filename, is_private=1,
            attached_to_doctype="WhatsApp Message", attached_to_name=source.name, content=content)).insert(ignore_permissions=True)
        frappe.db.set_value("WhatsApp Message", source.name, {"attach": file.file_url, "intake_media_mime": mime}, update_modified=False)
        self.paths.add(Path(file.get_full_path()))
        return source, file

    def image(self, color="red"):
        output = io.BytesIO()
        Image.new("RGB", (800, 400), color).save(output, "JPEG")
        return output.getvalue()

    def get(self, source):
        return preview(self.account.name, self.number, source.name)

    def test_image_cached_privately_without_message_mutation(self):
        source, original = self.source(self.image())
        before = frappe.get_doc("WhatsApp Message", source.name).as_dict()
        result = self.get(source)
        self.assertTrue(result["available"], result)
        self.assertEqual((result["width"], result["height"]), (480, 240))
        self.assertTrue(result["url"].startswith("/private/files/"))
        cache = frappe.get_doc("File", {"file_url": result["url"], "attached_to_name": source.name})
        self.assertTrue(cache.is_private)
        self.assertEqual(cache.attached_to_doctype, "WhatsApp Message")
        count = frappe.db.count("File", {"attached_to_name": source.name})
        with patch.object(service, "_render", side_effect=AssertionError("Unexpected render")):
            self.assertEqual(self.get(source), result)
        self.assertEqual(frappe.db.count("File", {"attached_to_name": source.name}), count)
        self.assertEqual(frappe.get_doc("WhatsApp Message", source.name).as_dict(), before)

    def test_pdf_renders_only_first_page(self):
        output = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=400, height=800)
        writer.add_blank_page(width=800, height=400)
        writer.write(output)
        source, _ = self.source(output.getvalue(), "application/pdf", "doc.pdf")
        result = self.get(source)
        self.assertTrue(result["available"], result)
        self.assertEqual(result["kind"], "pdf")
        self.assertEqual(result["height"], 480)
        self.assertLessEqual(abs(result["width"] - 240), 1)

    def test_denied_original_and_cache_do_not_leak_previews(self):
        source, original = self.source(self.image())
        result = self.get(source)
        cached_name = frappe.db.get_value("File", {"file_url": result["url"], "attached_to_name": source.name}, "name")
        from frappe.core.doctype.file.file import File
        real = File.has_permission
        for denied in (original.name, cached_name):
            with patch.object(File, "has_permission", lambda doc, *args, **kwargs: False if doc.name == denied else real(doc, *args, **kwargs)):
                self.assertFalse(self.get(source)["available"])
        with self.assertRaises(frappe.PermissionError):
            preview(self.account.name, "919999999999", source.name)
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            self.get(source)

    def test_source_bytes_changed_invalidates_cache(self):
        source, original = self.source(self.image())
        result = self.get(source)
        Path(original.get_full_path()).write_bytes(self.image("blue"))
        changed = self.get(source)
        self.assertTrue(changed["available"])
        self.assertNotEqual(result["url"], changed["url"])
        self.assertEqual(frappe.db.count("File", {"attached_to_name": source.name}), 3)

    def test_unowned_public_remote_malformed_and_oversized_fail_closed(self):
        source, file = self.source(self.image())
        frappe.db.set_value("File", file.name, "attached_to_name", "unrelated")
        self.assertFalse(self.get(source)["available"])
        frappe.db.set_value("File", file.name, "attached_to_name", source.name)
        frappe.db.set_value("File", file.name, "is_private", 0)
        self.assertFalse(self.get(source)["available"])
        frappe.db.set_value("File", file.name, "is_private", 1)
        frappe.db.set_value("WhatsApp Message", source.name, "attach", "https://example.com/image.jpg")
        self.assertFalse(self.get(source)["available"])
        frappe.db.set_value("WhatsApp Message", source.name, "attach", file.file_url)
        path = Path(file.get_full_path())
        path.write_bytes(b"invalid image")
        self.assertFalse(self.get(source)["available"])
        with path.open("wb") as stream:
            stream.truncate(service.MAX_BYTES + 1)
        self.assertFalse(self.get(source)["available"])
        self.assertEqual(frappe.db.count("File", {"attached_to_name": source.name}), 1)

    def test_render_failure_does_not_create_cache(self):
        source, _ = self.source(self.image())
        with patch.object(service, "_render", side_effect=TimeoutError):
            self.assertFalse(self.get(source)["available"])
        self.assertEqual(frappe.db.count("File", {"attached_to_name": source.name}), 1)

    def test_failed_cache_insert_rolls_back_file_and_disk(self):
        source, _ = self.source(self.image())
        directory = Path(frappe.get_site_path("private", "files"))
        before = set(directory.iterdir())
        original = service._owned_file
        calls = 0
        def deny_created(url, doc):
            nonlocal calls
            calls += 1
            return None if calls == 3 else original(url, doc)
        with patch.object(service, "_owned_file", side_effect=deny_created):
            self.assertFalse(self.get(source)["available"])
        self.assertEqual(frappe.db.count("File", {"attached_to_name": source.name}), 1)
        self.assertEqual(set(directory.iterdir()), before)

    def test_preview_rejects_stale_captured_sender_key(self):
        source, _ = self.source(self.image())
        frappe.db.set_value("WhatsApp Message", source.name,
            {"from": "919999999999", "intake_sender_key": self.number}, update_modified=False)
        with self.assertRaises(frappe.PermissionError):
            self.get(source)

    def test_preview_obeys_message_permission_query_filters(self):
        source, _ = self.source(self.image())
        get_list = frappe.get_list
        def filtered(doctype, *args, **kwargs):
            if doctype == "WhatsApp Message":
                return []
            return get_list(doctype, *args, **kwargs)
        with patch.object(frappe, "get_list", side_effect=filtered):
            with self.assertRaises(frappe.PermissionError):
                self.get(source)
