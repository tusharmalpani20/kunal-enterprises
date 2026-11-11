// The upstream subscription action needs write access, even though readers can view accounts.
frappe.ui.form.off("WhatsApp Account", "refresh");
frappe.ui.form.on("WhatsApp Account", {
	refresh(frm) {
		if (frm.is_new() || !frm.perm?.[0]?.write) return;
		frm.add_custom_button(__("Subscribe App to Webhooks"), () => {
			frappe.confirm(__("Subscribe this app to webhooks for WhatsApp Business Account {0}?", [frm.doc.business_id || frm.doc.account_name]),
				() => frm.call({doc: frm.doc, method: "subscribe_app", freeze: true, freeze_message: __("Subscribing app to webhooks...")}));
		});
	},
});
