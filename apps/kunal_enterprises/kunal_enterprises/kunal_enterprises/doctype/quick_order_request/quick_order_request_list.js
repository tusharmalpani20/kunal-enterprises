frappe.listview_settings["Quick Order Request"] = {
	get_indicator(doc) {
		const colors = { "Pending Review": "orange", "In Review": "blue", "Converted to Order": "green", "Rejected": "red" };
		return [__(doc.status), colors[doc.status] || "grey", `status,=,${doc.status}`];
	},
};
