// Replace upstream message-action handlers so read-only reviewers never send
// read receipts or see Reply. The backend enforces the same write boundary.
frappe.ui.form.off("WhatsApp Message", "onload");
frappe.ui.form.off("WhatsApp Message", "refresh");
frappe.ui.form.on("WhatsApp Message", {
	async onload(frm) {
		if (!frm.perm?.[0]?.write || frm.is_new() || frm.doc.type !== "Incoming" || !frm.doc.message_id || frm.doc.status === "marked as read") return;
		const { message } = await frappe.db.get_value("WhatsApp Account", frm.doc.whatsapp_account, "allow_auto_read_receipt");
		if (message?.allow_auto_read_receipt) await frm.call("send_read_receipt");
	},
	async refresh(frm) {
		if (!frm.perm?.[0]?.write || frm.is_new() || frm.doc.type !== "Incoming") return;
		if (frappe.model.can_create("WhatsApp Message")) {
			frm.add_custom_button(__("Reply"), () => frappe.new_doc("WhatsApp Message", {to: frm.doc.from, whatsapp_account: frm.doc.whatsapp_account}));
		}
		if (!frm.doc.message_id || frm.doc.status === "marked as read") return;
		const { message } = await frappe.db.get_value("WhatsApp Account", frm.doc.whatsapp_account, "allow_auto_read_receipt");
		if (!message?.allow_auto_read_receipt) frm.add_custom_button(__("Mark as read"), () => frm.call("send_read_receipt"));
	},
});

// Intake uses the original WhatsApp Message. Keep technical metadata collapsed.
frappe.ui.form.on("WhatsApp Message", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.type !== "Incoming") return;
		const roles = frappe.user_roles || [];
		if (frappe.session.user !== "Administrator" && !roles.some(role => ["Owner", "Admin", "Order Coordinator"].includes(role))) return;
		frm.add_custom_button(__("View Sender Messages"), () => {
			frappe.set_route("List", "WhatsApp Message", {
				type: "Incoming", whatsapp_account: frm.doc.whatsapp_account, intake_sender_key: frm.doc.intake_sender_key || frm.doc.from,
			});
		});
		frm.add_custom_button(__("Refresh Sender Match"), async () => {
			await frappe.call({method: "kunal_enterprises.api.order_intake_capture.refresh_sender", args: {message: frm.doc.name}, freeze: true});
			await frm.reload_doc();
		});
	},
});

frappe.ui.form.on("WhatsApp Message", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.type !== "Incoming" || !frm.doc.intake_media_id || !frm.perm?.[0]?.write) return;
		if (frm.doc.intake_media_state === "Downloaded" && frm.doc.attach) return;
		frm.add_custom_button(__("Retry Attachment Download"), async () => {
			const {message} = await frappe.call({method: "kunal_enterprises.api.order_intake_capture.retry_attachment",
				args: {message: frm.doc.name}, freeze: true});
			frappe.show_alert({message: __(message.state === "Downloaded" ? "Attachment is already available" : "Attachment download queued"), indicator: "blue"});
			await frm.reload_doc();
		});
	},
});
