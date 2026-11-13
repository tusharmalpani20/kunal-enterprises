"""Lazy private previews for the read-only inbox."""
import frappe

from kunal_enterprises.integrations.whatsapp_inbox_previews import get_preview


@frappe.whitelist(methods=["GET"])
def preview(account, sender, name):
    return get_preview(account, sender, name)
