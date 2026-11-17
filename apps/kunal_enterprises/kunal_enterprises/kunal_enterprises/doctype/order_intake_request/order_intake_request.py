"""Editable intake structure; automation and final Order conversion are separate steps."""
import math
import json
from uuid import uuid4

import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime

from kunal_enterprises.api.quick_orders import _require_reviewer


class OrderIntakeRequest(Document):
	def onload(self):
		# Float storage normalizes None to zero. Keep the semantic distinction in
		# the flag and send a blank editor value without changing stored evidence.
		for row in self.items:
			if row.get('quantity_unknown'):
				row.quantity = None

	def validate(self):
		if not frappe.flags.sales_portal_write:
			_require_reviewer()
		before = None if self.is_new() else self.get_doc_before_save()
		from kunal_enterprises.api.sales_portal_intake import guard_approval
		guard_approval(self, before)
		# Older open browser forms may omit this newly added hidden field. Keep
		# the server baseline; an omitted value must never erase it on save.
		if before and before.get("ai_initial_values") and not self.get("ai_initial_values"):
			self.ai_initial_values = before.ai_initial_values
		if self._validate_processing_boundary(before):
			return
		if not frappe.flags.intake_ai_write and (self.get("ai_initial_values") or None) != (before.get("ai_initial_values") or None if before else None):
			frappe.throw("Initial AI suggestions are managed by the system", frappe.PermissionError)
		if not frappe.flags.intake_ai_write and (self.proposed_updates or None) != (before.proposed_updates or None if before else None):
			frappe.throw("AI proposed updates are managed by the system", frappe.PermissionError)
		if not frappe.flags.intake_matching_write and (self.matching_json or None) != (before.matching_json or None if before else None):
			frappe.throw("Matching evidence is managed by the system", frappe.PermissionError)
		if (self.manual_match_fields or None) != (before.manual_match_fields or None if before else None):
			frappe.throw("Manual match protections are managed by the system", frappe.PermissionError)
		if self.first_received_at and self.last_received_at:
			if get_datetime(self.last_received_at) < get_datetime(self.first_received_at):
				frappe.throw("Last received time cannot precede first received time")
		self.customer_name = frappe.db.get_value("Customer", self.customer, "customer_name") if self.customer else ""
		self.sales_employee_name = frappe.db.get_value("Sales Employee", self.sales_employee, "sales_employee_name") if self.sales_employee else ""
		self._validate_legacy_evidence()
		self._simplify_legacy_layout()
		self._validate_items()
		self._protect_manual_matches(before)
		self._validate_attachments()
		self._validate_sources()
		if before and self.matching_json and not frappe.flags.intake_matching_write:
			from kunal_enterprises.integrations.order_intake_match_requests import matching_context
			if matching_context(self) != matching_context(before):
				self.matching_json = None
				for row in self.items:
					row.match_score = 0

		from kunal_enterprises.api.sales_portal_intake import finalize_approval
		finalize_approval(self, before)

	def _validate_processing_boundary(self, before):
		conversion = bool(self.flags.in_order_intake_conversion)
		transition = conversion or bool(self.flags.in_order_intake_transition)
		if before and before.status == 'Converted to Order':
			# Preserve the exact reviewed evidence and selections after conversion.
			# Standard metadata/timeline changes are not business-field changes.
			def payload(doc):
				return {field.fieldname: doc.get(field.fieldname) for field in doc.meta.fields
					if field.fieldtype not in ('Section Break', 'Column Break', 'Tab Break', 'HTML', 'Button')
					and field.fieldtype != 'Table'} | {
					field.fieldname: [{key: value for key, value in row.as_dict().items()
						if key not in ('modified', 'modified_by', 'creation', 'owner', '__unsaved')} for row in doc.get(field.fieldname)]
					for field in doc.meta.fields if field.fieldtype == 'Table'}
			if payload(self) != payload(before):
				frappe.throw('Converted intake requests are read-only. Create a new request for later changes.')
			return True
		old_order = before.order if before else None
		if (self.order or None) != (old_order or None) or self.status == 'Converted to Order':
			if not conversion or not self.order or self.status != 'Converted to Order':
				frappe.throw('Order links and conversion status are managed by Create Order.')
			order = frappe.get_doc('Order', self.order)
			if order.order_intake_request != self.name or order.customer != self.customer:
				frappe.throw('The Order must be created from this intake request and customer.')
		for field in ('reviewed_by', 'processed_at'):
			if (self.get(field) or None) != (before.get(field) or None if before else None) and not transition:
				frappe.throw('Processing audit fields are managed by the system.', frappe.PermissionError)
		return False

	def on_trash(self):
		if self.status == 'Converted to Order' or self.order:
			frappe.throw('Converted intake requests must be retained with their Order and evidence.')

	def _protect_manual_matches(self, before):
		if not before or frappe.flags.intake_matching_write:
			return
		protected = set(frappe.parse_json(before.manual_match_fields or '[]'))
		for field in ('customer', 'sales_employee'):
			if (self.get(field) or '') != (before.get(field) or ''):
				protected.add(field)
		old = {row.row_key: row for row in before.items}
		for row in self.items:
			if row.row_key in old:
				for field in ('item', 'godown'):
					if (row.get(field) or '') != (old[row.row_key].get(field) or ''):
						protected.add(f'{field}:{row.row_key}')
		valid = {'customer', 'sales_employee'} | {f'{field}:{row.row_key}' for row in self.items for field in ('item', 'godown')}
		self.manual_match_fields = json.dumps(sorted(protected & valid)) if protected else None

	def _validate_items(self):
		previous = None if self.is_new() else self.get_doc_before_save()
		old_keys = {row.name: row.row_key for row in previous.items} if previous else {}
		old_rows = {row.name: row for row in previous.items} if previous else {}
		seen = set()
		for row in self.items:
			if row.name in old_keys and row.row_key != old_keys[row.name]:
				frappe.throw("Existing item row IDs cannot be changed")
			if not row.row_key:
				row.row_key = uuid4().hex
			if row.row_key in seen:
				frappe.throw("Item row IDs must be unique within the request")
			seen.add(row.row_key)
			old = old_rows.get(row.name)
			if old and not frappe.flags.intake_matching_write and (row.item != old.item or row.original_text != old.original_text):
				# The old score describes the old suggestion, not a new manual choice.
				row.match_score = 0
			row.item_name = frappe.db.get_value("Tally Item", row.item, "item_name") if row.item else ""
			# API reviewers may provide a quantity without knowing the UI flag.
			# Explicit UI zero clears it through the child-field handler; unchanged
			# stored zero remains unknown and cannot become an actual Order.
			if (old and old.get('quantity_unknown') and row.quantity not in (None, '')
				and row.quantity != old.quantity and not frappe.flags.intake_ai_write):
				row.quantity_unknown = 0
			_validate_quantity(row.quantity)
			if not math.isfinite(row.match_score or 0) or not 0 <= (row.match_score or 0) <= 100:
				frappe.throw("Suggested match score must be between 0 and 100")

	def _validate_legacy_evidence(self):
		previous = None if self.is_new() else self.get_doc_before_save()
		if not previous:
			self.layout_simplified = 0
			return
		if self.layout_simplified != previous.layout_simplified:
			frappe.throw("The layout migration marker cannot be changed manually")
		for table, fields in {
			"warehouses": ("name", "row_key", "original_text", "godown", "source_message", "notes"),
			"allocations": ("name", "item_row_key", "warehouse_row_key", "quantity", "notes"),
		}.items():
			before = [tuple(row.get(field) for field in fields) for row in previous.get(table)]
			after = [tuple(row.get(field) for field in fields) for row in self.get(table)]
			if before != after:
				frappe.throw("Earlier warehouse allocations are retained as read-only evidence")

	def _simplify_legacy_layout(self):
		if self.layout_simplified:
			return
		# Preserve old tables as evidence, but stop treating their row references as
		# live constraints: otherwise a hidden allocation would prevent row deletion.
		warehouses = {row.row_key: row for row in self.warehouses}
		used = set()
		warnings = []
		linked_messages = {row.message for row in self.source_messages}
		for warehouse in self.warehouses:
			if warehouse.source_message and warehouse.source_message not in linked_messages:
				self.append("source_messages", {"message": warehouse.source_message})
				linked_messages.add(warehouse.source_message)
		for item in self.items:
			matches = [row for row in self.allocations if row.item_row_key == item.row_key]
			if not matches:
				continue
			allocation = matches[0]
			warehouse = warehouses.get(allocation.warehouse_row_key)
			quantity = allocation.quantity or 0
			_validate_quantity(quantity)
			conflict = item.quantity and quantity and not math.isclose(item.quantity, quantity)
			if warehouse:
				conflict = conflict or any(item.get(target) and item.get(target) != warehouse.get(source)
					for target, source in (("godown", "godown"), ("warehouse_text", "original_text"),
						("warehouse_source_message", "source_message")))
			if len(matches) != 1 or not warehouse or conflict:
				warnings.append("Please review the earlier warehouse details for " + (item.item or item.original_text or "an item") + ".")
				continue
			item.godown = warehouse.godown
			item.warehouse_text = warehouse.original_text
			item.warehouse_source_message = warehouse.source_message
			if not item.quantity:
				item.quantity = quantity
			for note in (allocation.notes, warehouse.notes):
				if note:
					item.notes = "\n".join(filter(None, (item.notes, note)))
			used.add(warehouse.row_key)
		for warehouse in self.warehouses:
			if warehouse.row_key not in used:
				text = warehouse.original_text or warehouse.godown or warehouse.notes or "Unspecified warehouse"
				warnings.append("Warehouse instruction needs review: " + text)
		if warnings:
			self.unresolved_questions = "\n".join(filter(None, [self.unresolved_questions, *warnings]))
		self.layout_simplified = 1

	def _validate_attachments(self):
		for row in self.attachments:
			if row.page_count and row.page_count < 0:
				frappe.throw("PDF page count cannot be negative")
			if not math.isfinite(row.latitude or 0) or not -90 <= (row.latitude or 0) <= 90:
				frappe.throw("Latitude must be between -90 and 90")
			if not math.isfinite(row.longitude or 0) or not -180 <= (row.longitude or 0) <= 180:
				frappe.throw("Longitude must be between -180 and 180")
			# Links are stored as text and are never fetched by this controller.
			if row.external_url and not row.external_url.lower().startswith(("https://", "http://")):
				frappe.throw("External links must start with https:// or http://")

	def _validate_sources(self):
		# Keep one complete source ledger regardless of which item, warehouse or
		# attachment originally supplied the reference. Later context lookup uses it.
		unique = {}
		for row in self.source_messages:
			if not row.message:
				frappe.throw("Each source association must select a WhatsApp Message")
			if row.message not in unique:
				unique[row.message] = row
				continue
			first = unique[row.message]
			if row.association_note and row.association_note != first.association_note:
				first.association_note = "\n".join(filter(None, (first.association_note, row.association_note)))
		refs = set(unique)
		refs.update(row.source_message for table in (self.items, self.warehouses, self.attachments)
			for row in table if row.source_message)
		refs.update(row.warehouse_source_message for row in self.items if row.warehouse_source_message)
		# A message may be linked to several requests, but each request stays in
		# one chat. Validate all references before changing the main source rows.
		for name in sorted(refs):
			message = frappe.db.get_value("WhatsApp Message", name,
				["whatsapp_account", "from", "type"], as_dict=True)
			if not message:
				frappe.throw("Source WhatsApp Message does not exist")
			if message.type != "Incoming":
				frappe.throw("Source messages must be incoming WhatsApp messages")
			if not self.whatsapp_account:
				self.whatsapp_account = message.whatsapp_account
			if not self.sender_number:
				self.sender_number = message.get("from")
			if message.whatsapp_account != self.whatsapp_account:
				frappe.throw("Source message belongs to a different WhatsApp account")
			if _sender_key(message.get("from")) != _sender_key(self.sender_number):
				frappe.throw("Source message belongs to a different sender")
		self.set("source_messages", list(unique.values()))
		for name in sorted(refs - set(unique)):
			self.append("source_messages", {"message": name})
		# Removing duplicate rows can leave repeated/gapped indexes. Keep the
		# preserved ledger order stable when Frappe reloads it from the database.
		for index, row in enumerate(self.source_messages, start=1):
			row.idx = index


def _sender_key(value):
	value = str(value or "").strip()
	# Keep future non-phone sender IDs intact instead of collapsing them to digits.
	if value and all(char.isdigit() or char in "+ -()" for char in value):
		return "".join(char for char in value if char.isdigit())
	return value


def _validate_quantity(value):
	# Zero/blank means unresolved in the draft, not a final order quantity.
	if not math.isfinite(value or 0) or (value or 0) < 0:
		frappe.throw("Draft quantities must be finite and cannot be negative")
