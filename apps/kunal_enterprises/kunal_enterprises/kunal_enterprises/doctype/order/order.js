frappe.ui.form.on("Order", {
	refresh(frm) {
		if (should_show_move_to_processing(frm)) {
			const button = frm.add_custom_button(__("Move to Processing"), () => {
				move_to_processing(frm);
			});
			button.addClass("btn-primary");
		}
	},
});

function should_show_move_to_processing(frm) {
	return (
		!frm.is_new()
		&& frm.doc.status === "Placed"
		&& frappe.user_roles.some((role) => ["Branch Manager", "Branch Employee"].includes(role))
	);
}

function move_to_processing(frm) {
	frappe.confirm(__("Move this order to Processing?"), () => {
		frappe.call({
			method: "kunal_enterprises.api.branch_orders.mark_visible_order_processing",
			args: {
				order: frm.doc.name,
			},
			freeze: true,
			callback(response) {
				if (!response.exc) {
					frm.reload_doc();
				}
			},
		});
	});
}
