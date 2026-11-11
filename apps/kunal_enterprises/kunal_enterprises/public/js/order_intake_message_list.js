frappe.listview_settings["WhatsApp Message"] = {
	add_fields: ["intake_status", "type", "status", "intake_received_at"],
	onload(listview) {
		const roles = frappe.user_roles || [];
		if (frappe.session.user !== "Administrator" && !roles.some(role => ["Owner", "Admin", "Order Coordinator"].includes(role))) return;
		listview.page.add_inner_button(__("Check Coverage"), () => {
			frappe.prompt([
				intake_capture_account_field(),
				{ fieldname: "since", fieldtype: "Datetime", label: __("Received Since") },
			], values => frappe.call({
				method: "kunal_enterprises.api.order_intake_capture.coverage_status", args: values, type: "GET",
			}).then(({ message }) => {
				frappe.msgprint({ title: __("Incoming Message Coverage"), message:
					__("Saved incoming: {0}<br>Prepared messages: {1}<br>Not prepared: {2}<br>Needs attention: {3}<br>Awaiting processing/review: {4}",
						[message.incoming_count, message.covered_count, message.missing_count, message.attention_count, message.pending_count]) });
			}), __("Check Coverage"), __("Check"));
		});
		listview.page.add_inner_button(__("Prepare Existing Messages"), () => {
			frappe.prompt([
				intake_capture_account_field(),
				{ fieldname: "since", fieldtype: "Datetime", label: __("Received Since"), reqd: 1 },
				{ fieldname: "limit", fieldtype: "Int", label: __("Maximum Messages"), default: 50, reqd: 1 },
			], values => frappe.call({
				method: "kunal_enterprises.api.order_intake_capture.capture_existing", args: values, freeze: true,
			}).then(({ message }) => {
				frappe.msgprint(__("Captured {0} source records; {1} need another repair attempt.", [message.captured.length, message.errors.length]));
				listview.refresh();
			}), __("Prepare Existing Messages"), __("Capture"));
		});
	},
	get_indicator(doc) {
		if (doc.type !== "Incoming") return [__(doc.status || "Outgoing"), "gray", `type,=,Outgoing`];
		if (!doc.intake_received_at) return [__("Not Prepared"), "gray", "intake_received_at,is,not set"];
		return [__(doc.intake_status), doc.intake_status === "Needs Attention" ? "orange" : doc.intake_status === "Duplicate" ? "gray" : "blue",
			`intake_status,=,${doc.intake_status}`];
	},
};

function intake_capture_account_field() {
	return { fieldname: "whatsapp_account", fieldtype: "Link", options: "WhatsApp Account",
		label: __("WhatsApp Account"), ignore_link_validation: true,
		get_query: () => ({ query: "kunal_enterprises.api.order_intake.intake_link_query" }) };
}
