frappe.ui.form.on("Tally Customer Ledger", {
	refresh(frm) {
		show_mapped_customer(frm);
	},
});

function show_mapped_customer(frm) {
	if (frm.is_new() || !frm.doc.client_code) {
		return;
	}

	frappe.call({
		method: "kunal_enterprises.kunal_enterprises.doctype.tally_customer_ledger.tally_customer_ledger.get_mapped_customer",
		args: {
			client_code: frm.doc.client_code,
		},
		callback(response) {
			const customer = response.message;
			if (!customer) {
				if (frm.dashboard && frm.dashboard.add_indicator) {
					frm.dashboard.add_indicator(__("Not mapped to Customer"), "orange");
				}
				return;
			}

			const label = customer.business_legal_name || customer.customer_name || customer.name;
			if (frm.dashboard && frm.dashboard.add_indicator) {
				frm.dashboard.add_indicator(__("Mapped to {0}", [label]), "green");
			}
			frm.add_custom_button(__("Mapped Customer: {0}", [label]), () => {
				frappe.set_route("Form", "Customer", customer.name);
			});
		},
	});
}
