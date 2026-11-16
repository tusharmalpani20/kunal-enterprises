"""Portable WhatsApp reviewer access and write checks for external actions."""
import frappe
from frappe.integrations.utils import make_post_request
from frappe.utils import get_datetime
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.permissions import setup_custom_perms
from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_account.whatsapp_account import WhatsAppAccount
from frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.whatsapp_message import WhatsAppMessage

MANAGED_TYPES = ("WhatsApp Message", "WhatsApp Account", "WhatsApp Settings")
REVIEW_ROLES = ("Owner", "Admin", "Order Coordinator")
CREDENTIAL_FIELDS = ("token", "webhook_verify_token")
PERMISSIONS = ("read", "select", "write", "create", "delete", "submit", "cancel", "amend",
	"report", "export", "import", "share", "print", "email")


class KunalWhatsAppAccount(WhatsAppAccount):
	@frappe.whitelist()
	def subscribe_app(self):
		self.check_permission("write")
		return super().subscribe_app()


class KunalWhatsAppMessage(WhatsAppMessage):
	@frappe.whitelist(methods=['POST'])
	def send_read_receipt(self):
		# Document calls carry the browser's entire, possibly stale document.
		# Use persisted identity for Meta and update only status after the call;
		# never save old intake/media fields back over a completed download.
		doc = frappe.get_doc('WhatsApp Message', self.name)
		doc.check_permission('write')
		if doc.type != 'Incoming' or not doc.message_id:
			frappe.throw('Only saved incoming messages can be marked as read.')
		account = frappe.get_doc('WhatsApp Account', doc.whatsapp_account)
		response = make_post_request(f'{account.url}/{account.version}/{account.phone_id}/messages',
			headers={'authorization': 'Bearer ' + account.get_password('token'), 'content-type': 'application/json'},
			data=frappe.as_json(dict(messaging_product='whatsapp', status='read', message_id=doc.message_id)))
		if response.get('success'):
			frappe.db.set_value(doc.doctype, doc.name, 'status', 'marked as read')
			self.reload()
			return True
		return False


def _set_permission(doctype, role, level, grants):
	filters = dict(parent=doctype, role=role, permlevel=level, if_owner=0)
	names = frappe.get_all("Custom DocPerm", filters=filters, pluck="name")
	values = {key: int(key in grants) for key in PERMISSIONS}
	if names:
		for name in names:
			frappe.db.set_value("Custom DocPerm", name, values, update_modified=False)
	else:
		frappe.get_doc(dict(doctype="Custom DocPerm", parenttype="DocType", parentfield="permissions",
			**filters, **values)).insert(ignore_permissions=True)


def setup():
	"""Add explicit Kunal grants while preserving existing upstream/other-role permissions."""
	for doctype in MANAGED_TYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		setup_custom_perms(doctype)
		for role in REVIEW_ROLES:
			if not frappe.db.exists("Role", role):
				continue
			grants = {"read", "select"}
			if role in {"Owner", "Admin"}:
				grants.add("write")
				if doctype != "WhatsApp Settings":
					grants.add("create")
			_set_permission(doctype, role, 0, grants)
		frappe.clear_cache(doctype=doctype)
	if frappe.db.exists("DocType", "WhatsApp Account"):
		for field in CREDENTIAL_FIELDS:
			make_property_setter("WhatsApp Account", field, "permlevel", 1, "Int", validate_fields_for_doctype=False)
		for role in ("Owner", "Admin", "System Manager"):
			if frappe.db.exists("Role", role):
				_set_permission("WhatsApp Account", role, 1, {"read", "write"})
		frappe.clear_cache(doctype="WhatsApp Account")


def _evidence_value(field, value):
	if value and field.fieldtype == 'Datetime':
		try:
			return get_datetime(value)
		except (TypeError, ValueError, OverflowError):
			pass  # Invalid input remains different and is rejected by the guard.
	return value or None


def guard_intake_fields(doc, method=None):
	"""Read-only form fields are not a server-side integrity boundary in Frappe."""
	if doc.flags.intake_service_write or doc.flags.intake_migrating or frappe.flags.in_migrate or frappe.flags.in_install:
		return
	before = None if doc.is_new() else doc.get_doc_before_save()
	if before and before.type == "Incoming" and before.get("intake_received_at"):
		# Provider identity/direction are part of the captured evidence. Editing
		# either can defeat deduplication or hide the source from preparation.
		if doc.type != before.type or doc.message_id != before.message_id:
			frappe.throw("Captured message ID and direction cannot be changed", frappe.PermissionError)
	for field in doc.meta.fields:
		if not field.fieldname.startswith("intake_") or field.fieldtype in {"Section Break", "Column Break", "HTML"}:
			continue
		value = doc.get(field.fieldname)
		if before:
			changed = _evidence_value(field, value) != _evidence_value(field, before.get(field.fieldname))
		else:
			changed = value not in (None, "", 0, False, field.default)
		if changed:
			frappe.throw("Intake evidence and preparation fields are managed by the system", frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def retry_failed(name):
	"""Guard the upstream convenience endpoint as well as document/worker entry points."""
	doc = frappe.get_doc("Bulk WhatsApp Message", name)
	doc.check_permission("write")
	if not frappe.has_permission("WhatsApp Message", "write"):
		frappe.throw("Message write access is required to retry sending", frappe.PermissionError)
	doc.retry_failed()
	return True


from frappe_whatsapp.frappe_whatsapp.doctype.bulk_whatsapp_message.bulk_whatsapp_message import BulkWhatsAppMessage


class KunalBulkWhatsAppMessage(BulkWhatsAppMessage):
	def retry_failed(self):
		self.check_permission("write")
		if not frappe.has_permission("WhatsApp Message", "write"):
			frappe.throw("Message write access is required to retry sending", frappe.PermissionError)
		return super().retry_failed()

	def resend_single_message(self, message_name):
		self.check_permission("write")
		message = frappe.get_doc("WhatsApp Message", message_name)
		message.check_permission("write")
		if message.bulk_message_reference != self.name or message.type != "Outgoing":
			frappe.throw("The selected message does not belong to this outgoing batch")
		return super().resend_single_message(message_name)
