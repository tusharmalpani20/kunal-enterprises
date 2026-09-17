frappe.ui.form.on("Order", {
	refresh(frm) {
		if (should_show_move_to_processing(frm)) {
			const button = frm.add_custom_button(__("Move to Processing"), () => {
				move_to_processing(frm);
			});
			button.addClass("btn-primary");
		}
		if (should_show_cancel_order(frm)) {
			const button = frm.add_custom_button(__("Cancel Order"), () => {
				cancel_order(frm);
			});
			button.addClass("btn-danger");
		}
	},
});

function should_show_cancel_order(frm) {
	const roles = frappe.user_roles || [];
	const cancellable_statuses = [
		"Placed",
		"Processing",
		"Partially Processed",
	];
	return (
		!frm.is_new()
		&& cancellable_statuses.includes(frm.doc.status)
		&& (
			frappe.session.user === "Administrator"
			|| roles.some((role) => ["Owner", "Admin"].includes(role))
		)
	);
}

function cancel_order(frm) {
	frappe.prompt(
		[
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Cancellation Reason"),
				reqd: 1,
			},
		],
		(values) => {
			frappe.call({
				method: "kunal_enterprises.api.order_controls.cancel_order",
				args: {
					order: frm.doc.name,
					note: values.reason,
				},
				freeze: true,
				freeze_message: __("Cancelling order..."),
				callback(response) {
					if (response.message?.success) {
						frappe.show_alert({ message: __("Order cancelled"), indicator: "green" });
						frm.reload_doc();
					} else if (response.message?.error?.message) {
						frappe.msgprint(response.message.error.message);
					}
				},
			});
		},
		__("Cancel Order"),
		__("Cancel Order"),
	);
}

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
