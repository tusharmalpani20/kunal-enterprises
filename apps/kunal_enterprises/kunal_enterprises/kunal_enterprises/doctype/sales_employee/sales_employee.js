frappe.ui.form.on("Sales Employee", {
	refresh(frm) {
		set_sales_employee_read_only_fields(frm);
		set_root_product_group_query(frm);

		if (!frm.is_new() && frm.doc.mobile_verified) {
			add_sales_employee_access_buttons(frm);
		}
	},
});

function set_sales_employee_read_only_fields(frm) {
	["status", "mobile_verified"].forEach((fieldname) => {
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

function add_sales_employee_access_buttons(frm) {
	if (frm.doc.status !== "Active") {
		const approve_button = frm.add_custom_button(__("Approve"), () => {
			update_sales_employee_access(frm, "approve_sales_employee", __("Approve Sales Employee?"));
		});
		approve_button.addClass("btn-primary");
	}

	if (frm.doc.status !== "Disabled") {
		const reject_button = frm.add_custom_button(__("Reject"), () => {
			update_sales_employee_access(frm, "reject_sales_employee", __("Reject Sales Employee?"));
		});
		reject_button.addClass("btn-danger");
	}
}

function update_sales_employee_access(frm, method, message) {
	frappe.confirm(message, () => {
		frappe.call({
			method: `kunal_enterprises.kunal_enterprises.doctype.sales_employee.sales_employee.${method}`,
			args: {
				sales_employee_name: frm.doc.name,
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
