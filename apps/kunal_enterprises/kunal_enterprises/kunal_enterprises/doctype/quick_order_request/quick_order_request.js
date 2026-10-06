frappe.ui.form.on("Quick Order Request", {
	setup(frm) {
		frm.set_query("item", "items", () => ({
			query: "kunal_enterprises.api.quick_orders.allowed_item_query",
			filters: { quick_order_request: frm.doc.name },
		}));
		frm.set_query("godown", "items", () => ({
			query: "kunal_enterprises.api.quick_orders.allowed_godown_query",
			filters: { quick_order_request: frm.doc.name },
		}));
	},
	refresh(frm) {
		quick_order_text_display(frm);
		const can_review = frappe.session.user === "Administrator"
			|| (frappe.user_roles || []).some(role => ["Owner", "Admin", "Order Coordinator"].includes(role));
		frm.set_df_property("items", "read_only", frm.doc.status !== "In Review" || !can_review);
		if (frm.is_new() || !can_review) return;
		if (frm.doc.status === "Pending Review") {
			frm.add_custom_button(__("Start Review"), () => quick_order_action(frm, "start_review"))
				.addClass("btn-primary");
		}
		if (frm.doc.status === "In Review") {
			frm.set_intro(__("Read the customer's original text, then select products and quantities below. Godowns are optional."));
			frm.add_custom_button(__("Place Order"), async () => {
				if (!frm.doc.items?.length) {
					frappe.msgprint(__("Add at least one product and quantity before placing the order."));
					return;
				}
				frappe.confirm(__("Place this order on behalf of the customer?"), () => quick_order_action(frm, "convert"));
			}).addClass("btn-primary");
		} else {
			frm.set_intro("");
		}
		if (["Pending Review", "In Review"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Reject Request"), () => {
				frappe.prompt([{ fieldname: "reason", fieldtype: "Small Text", label: __("Rejection Reason"), reqd: 1 }],
					values => quick_order_action(frm, "reject", { reason: values.reason }), __("Reject Request"), __("Reject"));
			});
		}
		if (frm.doc.order) {
			frm.add_custom_button(__("View Order"), () => frappe.set_route("Form", "Order", frm.doc.order));
		}
	},
});

function quick_order_text_display(frm) {
	if (!frm.__quick_order_text_display) {
		frm.__quick_order_text_display = frappe.ui.form.make_control({
			parent: frm.fields_dict.text_display.$wrapper,
			df: { fieldname: "original_text_display", fieldtype: "Text Editor",
				label: __("Quick Order Text"), read_only: 1 },
			render_input: true,
		});
	}
	// Keep the stored source literal; HTML is only used for the read-only presentation.
	const text = frappe.utils.escape_html(frm.doc.text || "");
	frm.__quick_order_text_display.set_value(
		`<div style="white-space: pre-wrap; overflow-wrap: anywhere; min-height: 120px">${text}</div>`);
}

async function quick_order_action(frm, action, args = {}) {
	if (frm.__quick_order_busy) return;
	frm.__quick_order_busy = true;
	try {
		if (action === "reject" && frm.is_dirty()) {
			// Incomplete draft rows must not prevent rejection; never discard them silently.
			const discard = await new Promise(resolve => frappe.confirm(
				__("Reject this request and discard unsaved item changes?"),
				() => resolve(true), () => resolve(false), __("Discard and Reject"), __("Continue Editing")));
			if (!discard) return;
		} else if (frm.is_dirty()) {
			await frm.save();
			if (frm.is_dirty()) return;
		}
		const response = await frappe.call({
			method: `kunal_enterprises.api.quick_orders.${action}`,
			args: { request: frm.doc.name, ...args },
			freeze: true,
			freeze_message: action === "convert" ? __("Placing order...") : __("Updating request..."),
		});
		if (!response.message?.success) {
			frappe.msgprint(response.message?.error?.message || __("Unable to update the request."));
			return;
		}
		await frm.reload_doc();
		frappe.show_alert({ message: action === "convert" ? __("Order placed") : __("Request updated"), indicator: "green" });
	} finally {
		frm.__quick_order_busy = false;
	}
}
