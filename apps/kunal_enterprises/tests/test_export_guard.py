"""HTTP routing regression checks for the bulk-download policy (no database)."""
import json
from importlib import import_module
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request, Response

from kunal_enterprises.permission_guards import exports


class ExportGuardTests(unittest.TestCase):
    def invoke(self, path, form=None, roles=None, user="branch@example.com", files=()):
        request = Request(EnvironBuilder(path=path, method="GET").get_environ())
        with ExitStack() as stack:
            stack.enter_context(patch.object(frappe, "session", SimpleNamespace(user=user)))
            stack.enter_context(patch.object(frappe, "request", request))
            stack.enter_context(patch.object(frappe, "form_dict", frappe._dict(form or {})))
            stack.enter_context(patch.object(frappe, "get_roles", return_value=roles or ["Branch Employee"]))
            stack.enter_context(patch.object(frappe, "get_all", return_value=[frappe._dict(x) for x in files]))
            stack.enter_context(patch.object(frappe, "_", side_effect=lambda message: message))
            def throw(message, exception, **kwargs):
                raise exception(message)
            stack.enter_context(patch.object(frappe, "throw", side_effect=throw))
            exports.guard_request()
            return dict(frappe.form_dict)

    def test_export_routes_denied_for_all_restricted_business_roles(self):
        methods = [
            "frappe.desk.reportview.export_query",
            "frappe.desk.query_report.export_query",
            "frappe.core.doctype.data_export.exporter.export_data",
            "frappe.core.doctype.data_import.data_import.download_template",
            "frappe.core.doctype.prepared_report.prepared_report.download_attachment",
            "frappe.core.api.file.zip_files",
            "frappe.utils.print_format.download_multi_pdf",
            "frappe.utils.print_format.download_multi_pdf_async",
            "frappe.contacts.doctype.contact.contact.download_vcards",
            "frappe.email.doctype.auto_email_report.auto_email_report.send_now",
        ]
        for role in ("Branch Employee", "Branch Manager", "Order Coordinator", "Godown Allocator"):
            for method in methods:
                for prefix in ("/api/method/", "/api/v1/method/", "/api/v2/method/"):
                    with self.subTest(role=role, method=method, prefix=prefix):
                        with self.assertRaises(frappe.PermissionError):
                            self.invoke(prefix + method, {"export_in_background": "1"}, roles=[role])

    def test_administrator_role_name_does_not_create_special_user_bypass(self):
        with self.assertRaises(frappe.PermissionError):
            self.invoke("/api/method/frappe.core.api.file.zip_files", roles=["Administrator"])

    def test_legacy_command_wins_over_an_innocent_path(self):
        with self.assertRaises(frappe.PermissionError):
            self.invoke("/api/method/frappe.client.get_list", {
                "cmd": "frappe.core.api.file.zip_files", "files": "[]"})

    def test_v2_doctype_shorthand_export_is_denied(self):
        with patch("frappe.modules.utils.load_doctype_module", return_value=SimpleNamespace(
            __name__="frappe.core.doctype.data_import.data_import")):
            with self.assertRaises(frappe.PermissionError):
                self.invoke("/api/v2/method/Data Import/download_template")

    def test_privileged_users_keep_existing_bulk_routes_and_unlimited_requests(self):
        for user, roles in (("owner", ["Owner"]), ("admin", ["Admin"]),
                            ("tech", ["System Manager"]), ("mixed", ["Branch Employee", "Admin"]),
                            ("Administrator", [])):
            with self.subTest(user=user):
                self.invoke("/api/method/frappe.core.api.file.zip_files", user=user, roles=roles)
                self.invoke("/api/resource/Order", {"limit_page_length": "0"}, user=user, roles=roles)

    def test_list_routes_reject_unlimited_or_oversized_requests(self):
        for route in ("/api/resource/Order", "/api/v1/resource/Order", "/api/v2/document/Order",
                      "/api/method/frappe.client.get_list", "/api/method/frappe.desk.reportview.get",
                      "/api/method/frappe.desk.reportview.get_list",
                      "/api/method/frappe.desk.search.search_link",
                      "/api/method/frappe.desk.search.search_widget"):
            for key in ("limit", "limit_page_length", "page_length"):
                for value in ("0", "-1", "201", "500000", "bad"):
                    with self.subTest(route=route, key=key, value=value):
                        with self.assertRaises(frappe.PermissionError):
                            self.invoke(route, {key: value})
            self.invoke(route, {"limit_page_length": "200"})
            defaults = self.invoke(route)
            self.assertEqual(defaults["limit_page_length"], 20)

    def test_ordinary_single_pdf_and_form_requests_remain_available(self):
        self.invoke("/api/method/frappe.utils.print_format.download_pdf", {
            "doctype": "Order", "name": "ORDER-1"})
        self.invoke("/api/method/frappe.desk.form.load.getdoc", {
            "doctype": "Order", "name": "ORDER-1"})

    def test_document_export_methods_cannot_use_alternate_dispatch(self):
        payload = json.dumps({"doctype": "Data Import", "name": "IMPORT-1"})
        cases = [
            ("/api/method/run_doc_method", {"method": "export_errored_rows", "docs": payload}),
            ("/api/method/run_doc_method", {"method": "download_import_log", "dt": "Data Import", "dn": "IMPORT-1"}),
            ("/api/v2/method/run_doc_method", {"method": "export_errored_rows", "document": payload}),
            ("/api/v2/document/Data Import/IMPORT-1/method/export_errored_rows/", {}),
            ("/api/resource/Data Import/IMPORT-1", {"run_method": "export_errored_rows"}),
        ]
        for path, form in cases:
            with self.subTest(path=path, form=form):
                with self.assertRaises(frappe.PermissionError):
                    self.invoke(path, form)

    def test_new_spreadsheet_responses_are_blocked_and_single_pdfs_survive(self):
        with patch.object(frappe, "session", SimpleNamespace(user="branch@example.com")), \
             patch.object(frappe, "get_roles", return_value=["Branch Employee"]):
            for mime, filename in (("text/csv", "customers.csv"),
                                   ("application/octet-stream", "customers.xlsx"),
                                   ("application/zip", "attachments.zip")):
                response = Response(b"sensitive data", mimetype=mime,
                                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
                exports.guard_response(response)
                self.assertEqual(response.status_code, 403)
                self.assertNotIn(b"sensitive data", response.data)
                self.assertNotIn("Content-Disposition", response.headers)
            pdf = Response(b"pdf bytes", mimetype="application/pdf",
                           headers={"Content-Disposition": 'attachment; filename="order.pdf"'})
            exports.guard_response(pdf)
            self.assertEqual(pdf.status_code, 200)
            self.assertEqual(pdf.data, b"pdf bytes")
            json_screen = Response('{"message": []}', mimetype="application/json")
            exports.guard_response(json_screen)
            self.assertEqual(json_screen.status_code, 200)

    def test_report_artifacts_remain_private_even_for_owner_uploads(self):
        for attached_to, folder in (("Report", "Home"), ("Prepared Report", "Home"),
                                    ("Auto Email Report", "Home"), (None, "Home/Exported Reports")):
            doc = frappe._dict(attached_to_doctype=attached_to, folder=folder, is_private=0)
            exports.keep_report_file_private(doc)
            self.assertEqual(doc.is_private, 1)
        image = frappe._dict(attached_to_doctype="WhatsApp Message", folder="Home", is_private=0)
        exports.keep_report_file_private(image)
        self.assertEqual(image.is_private, 0)

    def test_spreadsheet_artifacts_cannot_be_published_outside_report_folder(self):
        for filename in ("customers.csv", "stock.XLSX", "attachments.zip", "customers.json.gz"):
            doc = frappe._dict(attached_to_doctype="Customer", folder="Home", file_name=filename, is_private=0)
            exports.keep_report_file_private(doc)
            self.assertEqual(doc.is_private, 1, filename)

    def test_scheduled_email_exports_use_same_role_policy_on_document_save(self):
        # Resolve the configured document hook, so this also catches forgetting to
        # protect ordinary Desk/REST document saves instead of only send_now.
        from kunal_enterprises import hooks
        handler = hooks.doc_events["Auto Email Report"]["before_validate"]
        module, method_name = handler.rsplit(".", 1)
        callback = getattr(import_module(module), method_name)
        report = frappe._dict(doctype="Auto Email Report", name="Weekly customer data",
                              enabled=1, format="CSV")
        cases = [
            ("report@example.com", ["Report Manager"], False),
            ("branch@example.com", ["Branch Manager", "Report Manager"], False),
            ("employee@example.com", ["Branch Employee"], False),
            ("coordinator@example.com", ["Order Coordinator"], False),
            ("allocator@example.com", ["Godown Allocator"], False),
            ("owner@example.com", ["Owner"], True),
            ("admin@example.com", ["Admin", "Report Manager"], True),
            ("technical@example.com", ["System Manager"], True),
            ("Administrator", [], True),
        ]
        def throw(message, exception, **kwargs):
            raise exception(message)
        for user, roles, allowed in cases:
            with self.subTest(user=user, roles=roles):
                with patch.object(frappe, "session", SimpleNamespace(user=user)), \
                     patch.object(frappe, "get_roles", return_value=roles), \
                     patch.object(frappe, "_", side_effect=lambda message: message), \
                     patch.object(frappe, "throw", side_effect=throw):
                    if allowed:
                        callback(report, "before_validate")
                    else:
                        with self.assertRaises(frappe.PermissionError):
                            callback(report, "before_validate")

    def test_private_generated_reports_denied_but_order_attachments_allowed(self):
        for file in (
            {"attached_to_doctype": "Prepared Report", "file_name": "data.gz"},
            {"folder": "Home/Exported Reports", "file_name": "report.pdf"},
            {"file_name": "customer-export.csv"},
        ):
            for path, form in (("/private/files/report.gz", {}),
                               ("/api/method/download_file", {"file_url": "/private/files/report.gz"})):
                with self.subTest(file=file, path=path):
                    with self.assertRaises(frappe.PermissionError):
                        self.invoke(path, form, files=[file])
        self.invoke("/private/files/order.pdf", files=[{
            "attached_to_doctype": "Order", "file_name": "order.pdf"}])
        self.invoke("/private/files/photo.png", files=[{
            "attached_to_doctype": "WhatsApp Message", "file_name": "photo.png"}])


if __name__ == "__main__":
    unittest.main()
