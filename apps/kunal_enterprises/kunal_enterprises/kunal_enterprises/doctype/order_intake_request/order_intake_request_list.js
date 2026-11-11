frappe.listview_settings["Order Intake Request"] = {
	add_fields: ["status", "request_type", "sender_number"],
	get_indicator(doc) {
		const colors = { "Pending Review": "orange", "In Review": "blue", "Awaiting Confirmation": "yellow",
			Resolved: "green", "Converted to Order": "green", Dismissed: "gray" };
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
