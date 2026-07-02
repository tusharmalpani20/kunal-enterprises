frappe.ui.form.on("Customer", {
	refresh(frm) {
		set_customer_read_only_fields(frm);
		set_root_product_group_query(frm);

		if (!frm.is_new() && frm.doc.mobile_verified) {
			add_customer_access_buttons(frm);
		}
	},
});

function set_customer_read_only_fields(frm) {
	["status", "mobile_verified", "admin_approved", "client_code", "customer_app_access"].forEach((fieldname) => {
		frm.set_df_property(fieldname, "read_only", 1);
	});
}

function set_root_product_group_query(frm) {
	frm.set_query("product_group", "product_group_access", () => ({
		filters: {
			is_root: 1,
			is_active: 1,
		},
	}));
}

function add_customer_access_buttons(frm) {
	if (frm.doc.status !== "Active") {
		const approve_button = frm.add_custom_button(__("Approve"), () => {
			update_customer_access(frm, "approve_customer", __("Approve Customer?"));
		});
		approve_button.addClass("btn-primary");
	}

	if (frm.doc.status === "Active") {
		const disable_button = frm.add_custom_button(__("Disable"), () => {
			update_customer_access(frm, "disable_customer", __("Disable Customer?"));
		});
		disable_button.addClass("btn-danger");
	} else if (frm.doc.status === "Pending Admin Review") {
		const reject_button = frm.add_custom_button(__("Reject"), () => {
			update_customer_access(frm, "reject_customer", __("Reject Customer?"));
		});
		reject_button.addClass("btn-danger");
	}

	frm.add_custom_button(__("Client Code"), () => {
		prompt_for_client_code(frm);
	});
}

function update_customer_access(frm, method, message) {
	frappe.confirm(message, () => {
		frappe.call({
			method: `kunal_enterprises.kunal_enterprises.doctype.customer.customer.${method}`,
			args: {
				customer_name: frm.doc.name,
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

function prompt_for_client_code(frm) {
	frappe.prompt(
		[
			{
				fieldname: "client_code",
				fieldtype: "Data",
				label: __("Client Code"),
				reqd: 1,
				default: frm.doc.client_code || "",
			},
		],
		(values) => {
			frappe.call({
				method: "kunal_enterprises.kunal_enterprises.doctype.customer.customer.set_customer_client_code",
				args: {
					customer_name: frm.doc.name,
					client_code: values.client_code,
				},
				freeze: true,
				callback(response) {
					if (!response.exc) {
						frm.reload_doc();
					}
				},
			});
		},
		__("Set Client Code"),
		__("Save")
	);
}
