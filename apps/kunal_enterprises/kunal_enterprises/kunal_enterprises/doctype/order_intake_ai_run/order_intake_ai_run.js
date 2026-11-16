frappe.ui.form.on("Order Intake AI Run", {
	refresh(frm) {
		frm.disable_save();
		frm.toggle_display("estimated_cost_usd", Boolean(frm.doc.cost_known_calls));
		frm.toggle_display("provider_cost_usd", Boolean(frm.doc.provider_cost_known_calls));
		frm.set_intro(frm.doc.unknown_cost_calls
			? __("{0} calls have unavailable cost estimates. The displayed amount includes only known costs.", [frm.doc.unknown_cost_calls])
			: "", "orange");
	},
});
