"""Reconcile real report queries against transaction-scoped fixtures."""

from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.api.whatsapp_intake_report import UNASSIGNED, read
from kunal_enterprises.integrations.customer_contacts import normalize_phone


class TestWhatsAppIntakeReport(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.key = "report-" + uuid4().hex[:14]
        self.account = self.record("WhatsApp Account", account_name=self.key, status="Inactive")
        self.customer = self.record("Customer", customer_name=self.key, business_legal_name=self.key)
        self.godown_a = self.record("Tally Godown", godown_name=self.key + " A", is_active=1)
        self.godown_b = self.record("Tally Godown", godown_name=self.key + " B", is_active=1)
        self.filters = {"account": self.account.name, "from_date": "2020-01-02", "to_date": "2020-01-02"}

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def record(self, doctype, parent=None, field=None, **fields):
        if parent:
            fields.update(parent=parent.name, parenttype=parent.doctype, parentfield=field)
        doc = frappe.get_doc(dict(name=self.key + "-" + uuid4().hex[:12], doctype=doctype, **fields))
        doc.db_insert()
        return doc

    def message(self, number="918001000001", **fields):
        return self.record("WhatsApp Message", **{"from": number}, whatsapp_account=self.account.name,
            message_id=uuid4().hex, type="Incoming", profile_name="Sample sender", content_type="text",
            message="Sample text", **{"intake_received_at": "2020-01-02 23:59:59", **fields})

    def intake(self, messages, locations=(), original=None, final="Order", **fields):
        request = self.record("Order Intake Request", source="WhatsApp", request_type=final, status="Pending Review",
            customer=self.customer.name, whatsapp_account=self.account.name, sender_number=messages[0].get("from"),
            ai_initial_values=frappe.as_json({"request_type": original}) if original else None, **fields)
        for msg in messages:
            self.record("Order Intake Source Message", request, "source_messages", message=msg.name)
        for item, godown in locations:
            self.record("Order Intake Item", request, "items", item=item, godown=godown)
        return request

    def convert(self, request, locations, status="Placed"):
        order = self.record("Order", customer=request.customer, status=status, order_intake_request=request.name,
                            sales_employee=request.sales_employee)
        frappe.db.set_value(request.doctype, request.name, {"order": order.name, "status": "Converted to Order"})
        for item, godown in locations:
            self.record("Order Godown Allocation", order, "godown_allocations", item=item, godown=godown)
        return order

    def user(self, role):
        return frappe.get_doc(dict(doctype="User", email=f"{self.key}-{role.lower().replace(' ', '-') }@example.com",
            first_name=self.key, user_type="System User", send_welcome_email=0, roles=[dict(role=role)])).insert().name

    def read(self, view="summary", **filters):
        return read(filters={**self.filters, **filters}, view=view)

    def test_received_cohort_counts_distinct_records_and_preserves_original_type(self):
        first = self.message(intake_ai_state="Drafted")
        second = self.message(intake_ai_state="Unresolved")
        self.message(intake_media_state="Failed")
        self.message(intake_status="Duplicate")
        self.message()
        self.message(intake_received_at="2020-01-03 00:00:00")
        request = self.intake([first, second], original="Stock Inquiry")
        order = self.convert(request, [("ITEM-A", self.godown_a.name), ("ITEM-B", self.godown_b.name)])
        self.intake([first], final="Price Inquiry")
        summary = self.read()
        self.assertEqual(summary["totals"], dict(received=5, processed=2, intakes=2, orders=1, unaccounted=2))
        self.assertEqual([(r["key"], r["intakes"], r["orders"]) for r in summary["types"]],
                         [("Stock Inquiry", 1, 1), ("Original type unknown", 1, 0)])
        self.assertEqual([row.order for row in self.read("intakes", metric="orders", request_type="Stock Inquiry")["rows"]],
                         [order.name])
        for godown in (self.godown_a, self.godown_b):
            self.assertEqual(self.read(godown=godown.name)["totals"]["orders"], 1)
        self.assertEqual(self.read(godown=self.godown_a.name, item="ITEM-B")["totals"]["received"], 0)
        self.assertEqual(self.read(godown=UNASSIGNED)["totals"]["received"], 4)
        self.assertEqual(self.read(godown=UNASSIGNED)["totals"]["orders"], 0)

    def test_linked_photos_are_accounted_for_while_intake_still_needs_review(self):
        photos = [self.message(intake_original_type="image", intake_ai_state="Unresolved", intake_status="Needs Attention")
                  for _ in range(2)]
        unlinked = self.message(intake_ai_state="Unresolved", intake_status="Needs Attention")
        question = 'What does "less 50/- sheets" mean?'
        request = self.intake(photos, unresolved_questions=question)

        linked = self.read("messages", metric="linked")["rows"]
        self.assertEqual({row.name for row in linked}, {photo.name for photo in photos})
        for photo in photos:
            self.assertEqual(self.read("message", message=photo.name)["status"], "Linked to intake")
        self.assertEqual([row.name for row in self.read("messages", metric="unaccounted")["rows"]], [unlinked.name])
        self.assertEqual(self.read()["totals"], dict(received=3, processed=3, intakes=1, orders=0, unaccounted=1))
        self.assertEqual(frappe.db.get_value(request.doctype, request.name, "unresolved_questions"), question)

    def test_mismatched_source_and_nonreciprocal_order_are_not_counted(self):
        one = self.message(intake_ai_state="Drafted")
        two = self.message(number="918001000002")
        request = self.intake([one, two], original="Price Inquiry")
        order = self.record("Order", customer=self.customer.name, status="Placed")
        frappe.db.set_value(request.doctype, request.name, {"order": order.name, "status": "Converted to Order"})
        self.assertEqual(self.read()["totals"], dict(received=2, processed=1, intakes=1, orders=0, unaccounted=1))
        self.assertEqual([row.name for row in self.read("messages", metric="unaccounted")["rows"]], [two.name])

    def test_message_paging_survives_a_new_message_arriving(self):
        for _ in range(51):
            self.message(intake_received_at="2020-01-02 12:00:00")
        filters = {**self.filters, "metric": "unaccounted"}
        first = read(filters=filters, view="messages")
        self.assertEqual(len(first["rows"]), 50)
        for size in ("100", 500, 2000):
            full = read(filters=filters, view="messages", page_size=size)
            self.assertEqual(len(full["rows"]), 51)
            self.assertIsNone(full["next_cursor"])
        self.message()
        next_page = read(filters=filters, view="messages", cursor=first["next_cursor"])
        self.assertEqual(len(next_page["rows"]), 1)
        self.assertNotIn(next_page["rows"][0].name, {row.name for row in first["rows"]})
        self.assertIsNone(next_page["next_cursor"])

    def test_message_list_previews_bound_text_and_omit_media_payloads(self):
        text = self.message()
        image = self.message(intake_original_type="image")
        frappe.db.set_value("WhatsApp Message", text.name, "message", "Send\n four sheets " + "x" * 200)
        frappe.db.set_value("WhatsApp Message", image.name, "message", '{"id":"provider-media-id"}')
        rows = {row.name: row for row in self.read("messages")["rows"]}
        self.assertTrue(rows[text.name].preview.startswith("Send four sheets "))
        self.assertEqual(len(rows[text.name].preview), 120)
        self.assertEqual((rows[image.name].message_kind, rows[image.name].preview), ("image", ""))

    def test_largest_page_has_a_distinct_continuation(self):
        names = [f"{self.key}-page-{i:04}" for i in range(2001)]
        frappe.db.bulk_insert("WhatsApp Message", ["name", "type", "whatsapp_account", "from", "intake_received_at"],
                              [(name, "Incoming", self.account.name, "918001000001", "2020-01-02 12:00:00") for name in names])
        first = read(filters=self.filters, view="messages", page_size=2000)
        self.assertEqual([row.name for row in first["rows"]], names[:0:-1])
        second = read(filters=self.filters, view="messages", cursor=first["next_cursor"], page_size=2000)
        self.assertEqual([row.name for row in second["rows"]], names[:1])
        self.assertIsNone(second["next_cursor"])

    def test_sales_phone_scope_applies_to_totals_drilldown_and_context(self):
        user = self.user("Sales Portal User")
        self.customer.mobile_number = "8" + str(uuid4().int)[:9]
        frappe.db.set_value("Customer", self.customer.name, "mobile_number", self.customer.mobile_number)
        mobile = "+917" + str(uuid4().int)[:9]
        self.record("Customer Contact", self.customer, "contacts", contact_name="Second contact", mobile_number=mobile)
        employee = frappe.get_doc(dict(doctype="Sales Employee", sales_employee_name=self.key, portal_user=user,
            mobile_number="9" + str(uuid4().int)[:9], assigned_customers=[dict(customer=self.customer.name)])).insert()
        own = self.message(normalize_phone(employee.mobile_number))
        primary = self.message(normalize_phone(self.customer.mobile_number))
        contact = self.message(normalize_phone(mobile))
        hidden = self.message()
        self.intake([contact], sales_employee=employee.name)
        self.assertEqual(self.read(sales_employee=employee.name)["totals"]["received"], 3)
        frappe.set_user(user)
        self.assertEqual(self.read()["totals"]["received"], 3)
        self.assertEqual({row.name for row in self.read("messages")["rows"]}, {own.name, primary.name, contact.name})
        self.assertEqual(self.read("message", message=contact.name)["target"]["name"], contact.name)
        with self.assertRaises(frappe.PermissionError):
            self.read("message", message=hidden.name)
        frappe.set_user("Administrator")
        frappe.db.set_value("Customer", self.customer.name, "mobile_number", None)
        blank = self.message(number="")
        frappe.set_user(user)
        self.assertEqual({row.name for row in self.read("messages")["rows"]}, {own.name, contact.name})
        with self.assertRaises(frappe.PermissionError):
            self.read("message", message=blank.name)
        with self.assertRaises(frappe.PermissionError):
            blank.check_permission("read")

    def test_godown_scope_only_grants_exact_linked_evidence(self):
        visible = self.message()
        unrelated = self.message()
        unassigned = self.message()
        opened = self.intake([visible], [("ITEM-A", self.godown_a.name)])
        self.intake([unrelated], [("ITEM-A", self.godown_b.name)])
        self.intake([unassigned])
        older = self.message()
        cancelled = self.intake([older])
        self.convert(cancelled, [("ITEM-A", self.godown_a.name)], status="Cancelled")
        shared = self.message()
        frappe.db.set_value("WhatsApp Message", shared.name, "profile_name", None)
        self.intake([shared], [("ITEM-A", self.godown_a.name), ("ITEM-B", self.godown_b.name)])
        split = self.message()
        self.intake([split], [("ITEM-A", self.godown_a.name)])
        self.intake([split], [("ITEM-B", self.godown_b.name)])
        branch = self.record("Portal Branch", branch_name=self.key, is_active=1)
        self.record("Branch Godown Mapping", portal_branch=branch.name, godown=self.godown_a.name, is_active=1)
        for role, allowed in (("Branch Manager", {visible.name, older.name}), ("Branch Employee", {visible.name})):
            frappe.set_user("Administrator")
            user = self.user(role)
            self.record("User Permission", user=user, allow="Portal Branch", for_value=branch.name)
            frappe.set_user(user)
            rows = self.read("messages")["rows"]
            self.assertEqual({row.name for row in rows}, allowed | {shared.name, split.name})
            self.assertFalse(next(row.sender_name for row in rows if row.name == shared.name))
            self.assertEqual(next(row.preview for row in rows if row.name == visible.name), "Sample text")
            self.assertTrue(all((row.message_kind, row.preview) == ("restricted", "")
                                for row in rows if row.name in {shared.name, split.name}))
            self.assertEqual(self.read(godown=UNASSIGNED)["totals"]["received"], 0)
            self.assertEqual(self.read(sales_employee="unrelated")["totals"], self.read()["totals"])
            self.assertEqual(self.read("breakdown", group="sales_employee")["rows"], [])
            self.assertEqual(read(filters=self.filters, view="options", field="sales_employee")["rows"], [])
            detail = self.read("message", message=visible.name)
            self.assertEqual([row["name"] for row in detail["messages"]], [visible.name])
            self.assertTrue(detail["context_only"])
            self.assertEqual(detail["target"]["text"], "Sample text")
            self.assertFalse(detail["can_retry_attachment"])
            for message in (shared, split):
                restricted = self.read("message", message=message.name)["target"]
                self.assertEqual(restricted["text"], "Message preview is restricted for this godown.")
            self.assertFalse(next(row for row in self.read("intakes")["rows"] if row.name == opened.name).can_open_intake)
            with self.assertRaises(frappe.PermissionError):
                self.read("message", message=unrelated.name)
        frappe.set_user("Administrator")
        frappe.db.set_value("Portal Branch", branch.name, "is_active", 0)
        frappe.set_user(user)
        self.assertEqual(self.read()["totals"]["received"], 0)

    def test_options_and_breakdowns_match_filters(self):
        msg = self.message()
        request = self.intake([msg], [("ITEM-A", self.godown_a.name), ("ITEM-B", self.godown_b.name)])
        self.assertEqual(self.read("breakdown", group="godown", item="ITEM-A")["rows"][0].name, self.godown_a.name)
        self.assertEqual([row.name for row in self.read("breakdown", group="godown", godown=self.godown_a.name)["rows"]],
                         [self.godown_a.name])
        result = read(filters=self.filters, view="options", field="godown", search=self.godown_b.name)
        self.assertEqual([row.value for row in result["rows"]], [self.godown_b.name])
        self.assertEqual([row.name for row in self.read("intakes", godown=self.godown_b.name)["rows"]], [request.name])
        self.assertEqual(read(filters=self.filters, view="options", field="item", search="%")["rows"], [])
        filtered = read(filters={**self.filters, "item": "ITEM-A"}, view="options", field="godown")
        self.assertEqual([row.value for row in filtered["rows"] if row.value != UNASSIGNED], [self.godown_a.name])
        filtered = read(filters={**self.filters, "godown": self.godown_b.name}, view="options", field="item")
        self.assertEqual([row.value for row in filtered["rows"]], ["ITEM-B"])

    def test_system_manager_report_does_not_grant_intake_form_access(self):
        message = self.message()
        request = self.intake([message], original="Order")
        frappe.set_user(self.user("System Manager"))
        self.assertEqual(self.read()["totals"]["intakes"], 1)
        row = self.read("intakes")["rows"][0]
        self.assertEqual((row.name, row.customer_name), (request.name, self.customer.customer_name))
        self.assertEqual(bool(row.can_open_intake), frappe.has_permission("Order Intake Request", "read"))

    def test_attachment_retry_requires_media_and_existing_write_permission(self):
        missing = self.message(intake_media_state="Failed")
        failed = self.message(intake_media_state="Failed", intake_media_id="test-media-id")
        self.assertFalse(self.read("message", message=missing.name)["can_retry_attachment"])
        detail = self.read("message", message=failed.name)
        self.assertTrue(detail["can_retry_attachment"])
        self.assertEqual(detail["sender"], failed.get("from"))
        frappe.set_user(self.user("System Manager"))
        self.assertFalse(self.read("message", message=failed.name)["can_retry_attachment"])

    def test_invalid_input_and_unrelated_role_are_denied(self):
        with self.assertRaises(frappe.ValidationError):
            self.read(from_date="2021-01-01")
        with self.assertRaises(frappe.ValidationError):
            read(self.filters, view="options", field="password")
        with self.assertRaises(frappe.ValidationError):
            read(self.filters, view="messages", cursor='["invalid-date", "message"]')
        with self.assertRaises(frappe.ValidationError):
            read(self.filters, view="messages", page_size=51)
        frappe.set_user(self.user("Desk User"))
        with self.assertRaises(frappe.PermissionError):
            self.read()
