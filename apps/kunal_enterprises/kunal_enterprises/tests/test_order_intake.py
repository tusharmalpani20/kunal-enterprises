"""Incomplete drafts keep each item and its dispatch warehouse together."""
import math
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase


class TestOrderIntake(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def draft(self):
		return frappe.get_doc({"doctype": "Order Intake Request", "sender_number": "unknown-test",
			"items": [{"original_text": "21317 mr", "warehouse_text": "office godown"}]}).insert()

	def test_unknown_sender_and_incomplete_rows_can_be_saved(self):
		doc = self.draft()
		self.assertFalse(doc.customer)
		self.assertFalse(doc.items[0].item)
		self.assertFalse(doc.items[0].quantity)
		self.assertFalse(doc.items[0].godown)
		self.assertEqual(doc.status, "Pending Review")

	def test_item_warehouse_relationship_survives_editing_and_reordering(self):
		first = frappe.get_doc({"doctype": "Tally Godown", "godown_name": "Intake " + uuid4().hex, "is_active": 1}).insert()
		second = frappe.get_doc({"doctype": "Tally Godown", "godown_name": "Intake " + uuid4().hex, "is_active": 1}).insert()
		doc = self.draft()
		doc.items[0].godown = first.name
		doc.items[0].correction_reason = "Corrected the first warehouse"
		doc.items[0].notes = "Keep dry"
		doc.append("items", {"original_text": "another item", "godown": second.name, "quantity": 3,
			"correction_reason": "Confirmed the second item"})
		doc.review_notes = "General request note"
		doc.interpretation_notes = "Reviewer clarification"
		doc.save()
		doc.items.reverse()
		for index, row in enumerate(doc.items, 1):
			row.idx = index  # Desk's row move updates both list position and idx.
		doc.save()
		doc.reload()
		self.assertEqual([(row.original_text, row.godown) for row in doc.items],
			[("another item", second.name), ("21317 mr", first.name)])
		self.assertEqual([row.get("correction_reason") for row in doc.items],
			["Confirmed the second item", "Corrected the first warehouse"])
		self.assertEqual(doc.items[1].notes, "Keep dry")
		self.assertEqual(doc.review_notes, "General request note")
		self.assertEqual(doc.get("interpretation_notes"), "Reviewer clarification")
		doc.items[0].godown = first.name
		doc.save()
		self.assertEqual(doc.items[0].godown, first.name)

	def test_existing_item_ids_cannot_be_changed(self):
		doc = self.draft()
		doc.items[0].row_key = uuid4().hex
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_legacy_single_allocation_is_preserved_once(self):
		doc = frappe.get_doc({"doctype": "Order Intake Request",
			"items": [{"row_key": "old-item", "original_text": "21317 mr"}],
			"warehouses": [{"row_key": "old-warehouse", "original_text": "office godown"}],
			"allocations": [{"item_row_key": "old-item", "warehouse_row_key": "old-warehouse", "quantity": 2}]}).insert()
		self.assertEqual(doc.items[0].quantity, 2)
		self.assertEqual(doc.items[0].warehouse_text, "office godown")
		self.assertFalse(doc.items[0].godown)
		self.assertTrue(doc.layout_simplified)
		doc.save()
		self.assertEqual(len(doc.items), 1)
		self.assertEqual(len(doc.allocations), 1)  # Retained evidence, not an active relationship.
		doc.set("items", [])
		doc.save()  # A hidden historical allocation must not trap the reviewer.

	def test_ambiguous_legacy_allocations_remain_visible_as_review_notes(self):
		for allocations in ([{"item_row_key": "old-item", "warehouse_row_key": "old-warehouse", "quantity": 2}],
			[{"item_row_key": "old-item", "warehouse_row_key": "old-warehouse", "quantity": 1}] * 2):
			doc = frappe.get_doc({"doctype": "Order Intake Request",
				"items": [{"row_key": "old-item", "original_text": "21317 mr", "quantity": 5}],
				"warehouses": [{"row_key": "old-warehouse", "original_text": "office godown"}],
				"allocations": allocations}).insert()
			self.assertEqual(doc.items[0].quantity, 5)
			self.assertFalse(doc.items[0].godown)
			self.assertIn("office godown", doc.unresolved_questions)
			before = doc.unresolved_questions
			doc.save()
			self.assertEqual(doc.unresolved_questions, before)

	def test_warehouse_only_legacy_instruction_and_source_are_preserved(self):
		account = frappe.get_doc({"doctype": "WhatsApp Account", "account_name": "Intake " + uuid4().hex,
			"status": "Active", "phone_id": uuid4().hex}).insert(ignore_permissions=True)
		message = self._incoming(account.name, "919998887776")
		doc = frappe.get_doc({"doctype": "Order Intake Request", "warehouses": [
			{"row_key": "warehouse", "original_text": "office godown", "source_message": message.name}]}).insert()
		self.assertFalse(doc.items)
		self.assertIn("office godown", doc.unresolved_questions)
		self.assertEqual([row.message for row in doc.source_messages], [message.name])
		doc.save()
		self.assertEqual(len(doc.source_messages), 1)

	def test_legacy_migration_preserves_a_reviewed_warehouse_selection(self):
		selected = frappe.get_doc({"doctype": "Tally Godown", "godown_name": "Intake " + uuid4().hex,
			"is_active": 1}).insert()
		doc = frappe.get_doc({"doctype": "Order Intake Request", "items": [{"row_key": "old-item",
			"original_text": "21317 mr", "quantity": 2, "godown": selected.name,
			"warehouse_text": "reviewed warehouse"}],
			"warehouses": [{"row_key": "old-warehouse", "original_text": "office godown"}],
			"allocations": [{"item_row_key": "old-item", "warehouse_row_key": "old-warehouse", "quantity": 2}]}).insert()
		self.assertEqual(doc.items[0].godown, selected.name)
		self.assertEqual(doc.items[0].warehouse_text, "reviewed warehouse")
		self.assertIn("office godown", doc.unresolved_questions)

	def test_unimplemented_conversion_cannot_be_claimed(self):
		doc = self.draft()
		doc.status = "Converted to Order"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc.reload()
		doc.order = "fake-order"
		# Controller guard also applies when link validation is explicitly disabled.
		doc.flags.ignore_links = True
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_invalid_quantities_and_coordinates_are_rejected(self):
		for quantity in (-1, math.inf, math.nan):
			doc = frappe.get_doc({"doctype": "Order Intake Request", "items": [{"quantity": quantity}]})
			with self.assertRaises(frappe.ValidationError):
				doc.insert()
		doc = frappe.get_doc({"doctype": "Order Intake Request", "attachments": [{"reference_type": "Location", "latitude": 91}]})
		with self.assertRaises(frappe.ValidationError):
			doc.insert()

	def test_only_reviewers_can_write_requests(self):
		doc = self.draft()
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			doc.save(ignore_permissions=True)

	def test_settings_ranges_and_disabled_processing(self):
		settings = frappe.get_doc("Order Intake Settings")
		for field, value in (("pdf_page_limit", 0), ("lookback_minutes", 0), ("output_retries", -1),
			("processing_enabled", 1)):
			settings.reload()
			settings.set(field, value)
			with self.assertRaises(frappe.ValidationError):
				settings.save()

	def test_settings_are_restricted_and_password_is_not_versioned(self):
		meta = frappe.get_meta("Order Intake Settings")
		self.assertFalse(meta.track_changes)
		self.assertEqual(meta.get_field("api_key").fieldtype, "Password")
		self.assertFalse(frappe.has_permission("Order Intake Settings", "read", user="Guest"))

	def test_review_roles_can_create_and_edit_and_settings_are_restricted(self):
		from kunal_enterprises.tests.test_foundation import TestOrderSubmission as Helpers
		for role in ("Owner", "Admin", "Order Coordinator"):
			frappe.set_user("Administrator")
			user = Helpers._create_role_user(self, f"intake-{uuid4().hex}@example.com", role)
			frappe.set_user(user.name)
			doc = frappe.get_doc({"doctype": "Order Intake Request", "review_notes": role}).insert()
			doc.review_notes = "Edited"
			doc.save()
			if role == "Order Coordinator":
				self.assertFalse(frappe.has_permission("Order Intake Settings", "read"))
				settings = frappe.get_doc("Order Intake Settings")
				with self.assertRaises(frappe.PermissionError):
					settings.save(ignore_permissions=True)
			else:
				self.assertTrue(frappe.has_permission("Order Intake Settings", "read"))
				frappe.get_doc("Order Intake Settings").save()

	def test_minimal_master_lookups_require_reviewer(self):
		from kunal_enterprises.api.order_intake import intake_link_query
		from kunal_enterprises.tests.test_foundation import TestOrderSubmission as Helpers
		user = Helpers._create_role_user(self, f"intake-{uuid4().hex}@example.com", "Order Coordinator")
		frappe.set_user(user.name)
		for doctype, columns in (("Customer", 4), ("Sales Employee", 3), ("WhatsApp Account", 1), ("WhatsApp Message", 4)):
			rows = intake_link_query(doctype, "", "name", 0, 2, {})
			self.assertLessEqual(len(rows), 2)
			self.assertTrue(all(len(row) == columns for row in rows))
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			intake_link_query("WhatsApp Account", "", "name", 0, 2, {})

	def _incoming(self, account, sender):
		return frappe.get_doc({"doctype": "WhatsApp Message", "type": "Incoming", "from": sender,
			"message": "test intake", "content_type": "text", "whatsapp_account": account,
			"message_id": uuid4().hex}).insert(ignore_permissions=True)

	def test_source_lookup_accepts_formatted_sender_without_crossing_chats(self):
		from kunal_enterprises.api.order_intake import intake_link_query
		account = frappe.get_doc({"doctype": "WhatsApp Account", "account_name": "Intake " + uuid4().hex,
			"status": "Active", "phone_id": uuid4().hex}).insert(ignore_permissions=True)
		matching = self._incoming(account.name, "919998887776")
		other = self._incoming(account.name, "919998887775")
		rows = intake_link_query("WhatsApp Message", "", "name", 0, 40,
			{"whatsapp_account": account.name, "from": "+91 (999) 888-7776"})
		self.assertIn(matching.name, [row[0] for row in rows])
		self.assertNotIn(other.name, [row[0] for row in rows])

	def test_source_metadata_is_inferred_and_mixed_chats_rejected(self):
		accounts = []
		for _ in range(2):
			account = frappe.get_doc({"doctype": "WhatsApp Account", "account_name": "Intake " + uuid4().hex,
				"status": "Active", "phone_id": uuid4().hex}).insert(ignore_permissions=True)
			accounts.append(account.name)
		first = self._incoming(accounts[0], "919998887776")
		same = self._incoming(accounts[0], "919998887776")
		doc = frappe.get_doc({"doctype": "Order Intake Request", "source_messages": [{"message": first.name}, {"message": same.name}]}).insert()
		self.assertEqual(doc.whatsapp_account, accounts[0])
		self.assertEqual(doc.sender_number, "919998887776")
		for account, sender in ((accounts[0], "919998887775"), (accounts[1], "919998887776")):
			other = self._incoming(account, sender)
			with self.assertRaises(frappe.ValidationError):
				frappe.get_doc({"doctype": "Order Intake Request", "source_messages": [{"message": first.name}, {"message": other.name}]}).insert()

	def test_all_child_source_references_join_main_ledger_and_related_context(self):
		from kunal_enterprises.integrations.order_intake_queue import build_context
		account = frappe.get_doc({"doctype": "WhatsApp Account", "account_name": "Intake " + uuid4().hex,
			"status": "Active", "phone_id": uuid4().hex}).insert(ignore_permissions=True)
		messages = [self._incoming(account.name, "919998887776") for _ in range(4)]
		doc = frappe.get_doc({"doctype": "Order Intake Request", "items": [
			{"original_text": "two sheets", "source_message": messages[0].name, "warehouse_source_message": messages[1].name}],
			"attachments": [{"reference_type": "External Link", "external_url": "https://example.com/order", "source_message": messages[2].name}],
			"warehouses": [{"row_key": "old", "source_message": messages[3].name, "original_text": "earlier warehouse"}],
			"source_messages": [{"message": messages[0].name, "association_note": "Item evidence"},
				{"message": messages[0].name, "association_note": "Warehouse clarification"}]}).insert()
		self.assertEqual({row.message for row in doc.source_messages}, {message.name for message in messages})
		self.assertEqual(len(doc.source_messages), 4)
		primary = next(row for row in doc.source_messages if row.message == messages[0].name)
		self.assertIn("Item evidence", primary.association_note)
		self.assertIn("Warehouse clarification", primary.association_note)
		row_names = [row.name for row in doc.source_messages]
		doc.save()
		doc.reload()
		self.assertEqual([row.name for row in doc.source_messages], row_names)
		context = build_context([messages[2]])
		self.assertIn(doc.name, [request["name"] for request in context["open_requests"]])

	def test_child_only_source_cross_chat_is_rejected(self):
		account = frappe.get_doc({"doctype": "WhatsApp Account", "account_name": "Intake " + uuid4().hex,
			"status": "Active", "phone_id": uuid4().hex}).insert(ignore_permissions=True)
		first = self._incoming(account.name, "919998887776")
		other = self._incoming(account.name, "919998887775")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Order Intake Request", "items": [{"source_message": first.name}],
				"attachments": [{"source_message": other.name}]}).insert()

	def test_long_reference_urls_round_trip_without_weakening_scheme_validation(self):
		url = "https://example.com/location?reference=" + "a" * 2000
		doc = frappe.get_doc({"doctype": "Order Intake Request", "attachments": [
			{"reference_type": "External Link", "external_url": url}]}).insert()
		doc.reload()
		self.assertEqual(doc.attachments[0].external_url, url)
		doc.attachments[0].external_url = "javascript:alert(1)"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_historical_child_only_source_backfill_preserves_review_state(self):
		from kunal_enterprises.patches.normalize_order_intake_sources import execute
		account = frappe.get_doc({"doctype": "WhatsApp Account", "account_name": "Intake " + uuid4().hex,
			"status": "Active", "phone_id": uuid4().hex}).insert(ignore_permissions=True)
		message = self._incoming(account.name, "919998887776")
		doc = frappe.get_doc({"doctype": "Order Intake Request", "status": "In Review", "review_notes": "Keep this note",
			"items": [{"original_text": "two sheets", "source_message": message.name, "correction_reason": "Chosen by reviewer"}]}).insert()
		modified = doc.modified
		frappe.db.delete("Order Intake Source Message", {"parent": doc.name, "parenttype": "Order Intake Request"})
		frappe.db.set_value("Order Intake Request", doc.name, {"whatsapp_account": None, "sender_number": None}, update_modified=False)
		execute()
		doc.reload()
		self.assertEqual([row.message for row in doc.source_messages], [message.name])
		self.assertEqual(doc.whatsapp_account, account.name)
		self.assertEqual(doc.sender_number, "919998887776")
		self.assertEqual(doc.status, "In Review")
		self.assertEqual(doc.review_notes, "Keep this note")
		self.assertEqual(doc.items[0].correction_reason, "Chosen by reviewer")
		self.assertEqual(str(doc.modified), str(modified))
		row_name = doc.source_messages[0].name
		execute()
		self.assertEqual(doc.reload().source_messages[0].name, row_name)
