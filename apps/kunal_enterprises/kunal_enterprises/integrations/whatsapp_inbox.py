"""Account-scoped, content-free inbox invalidation after database commit."""
import frappe


def changed(doc, method=None):
	if not getattr(doc, 'name', None):
		return
	accounts = {doc.whatsapp_account} if doc.type == 'Incoming' and doc.whatsapp_account else set()
	# Ordinary source corrections can move a row to another account. Invalidate
	# both views so a previously visible row is removed from the old account.
	before = doc.get_doc_before_save()
	if before and before.type == 'Incoming' and before.whatsapp_account:
		accounts.add(before.whatsapp_account)
	for account in sorted(accounts):
		frappe.publish_realtime('whatsapp_inbox_changed', {'account': account, 'message': doc.name},
			doctype='WhatsApp Account', docname=account, after_commit=True)


def message_changed(name):
	"""For internal media updates which deliberately bypass Document.save."""
	changed(frappe.get_doc('WhatsApp Message', name))
