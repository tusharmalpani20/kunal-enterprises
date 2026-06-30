frappe.ui.form.on("User", {
	refresh(frm) {
		if (frm.is_new() || !can_manage_user_branches()) {
			return;
		}

		frm.add_custom_button(__("Branches"), () => {
			show_user_branch_dialog(frm);
		}).addClass("btn-primary");
	},
});

function can_manage_user_branches() {
	const roles = frappe.user_roles || [];
	return frappe.session.user === "Administrator" || roles.includes("Owner") || roles.includes("Admin");
}

function show_user_branch_dialog(frm) {
	frappe.call({
		method: "kunal_enterprises.api.user_branch_permissions.get_user_branches",
		args: {
			user: frm.doc.name,
		},
		freeze: true,
		callback(response) {
			if (!response.message) {
				return;
			}
			render_user_branch_dialog(frm, response.message);
		},
	});
}

function render_user_branch_dialog(frm, data) {
	const current_branches = data.branches || [];
	const inactive_branches = (data.branch_details || []).filter((branch) => !branch.is_active);
	const summary = build_branch_dialog_summary(data, inactive_branches);

	const dialog = new frappe.ui.Dialog({
		title: __("Branches - {0}", [frm.doc.full_name || frm.doc.name]),
		size: "large",
		fields: [
			{
				fieldname: "summary",
				fieldtype: "HTML",
				options: summary,
			},
			{
				fieldname: "branches",
				fieldtype: "MultiSelectList",
				label: __("Branches"),
				read_only: data.can_edit ? 0 : 1,
				get_data(txt) {
					return frappe.db.get_link_options("Portal Branch", txt, {
						is_active: 1,
					});
				},
			},
		],
		primary_action_label: data.can_edit ? __("Save") : __("Close"),
		primary_action(values) {
			if (!data.can_edit) {
				dialog.hide();
				return;
			}

			frappe.call({
				method: "kunal_enterprises.api.user_branch_permissions.set_user_branches",
				args: {
					user: frm.doc.name,
					branches: JSON.stringify(values.branches || []),
				},
				freeze: true,
				freeze_message: __("Saving branch assignments..."),
				callback(save_response) {
					const result = save_response.message;
					if (!result) {
						return;
					}
					frappe.show_alert({
						message: __("Branch assignments updated"),
						indicator: "green",
					});
					dialog.hide();
					show_user_branch_dialog(frm);
				},
			});
		},
	});

	dialog.show();
	dialog.set_value("branches", current_branches);
}

function build_branch_dialog_summary(data, inactive_branches) {
	const roles = (data.roles || []).join(", ") || __("None");
	const profile = data.role_profile || __("None");
	const readonly_message = data.can_edit
		? ""
		: `<p class="text-muted">${__("Branch assignments are editable only for Branch Manager and Branch Employee users.")}</p>`;
	const inactive_message = inactive_branches.length
		? `<div class="alert alert-warning">
			${__("Inactive assigned branches can be removed but cannot be newly assigned:")}
			<strong>${inactive_branches.map((branch) => frappe.utils.escape_html(branch.branch_name || branch.name)).join(", ")}</strong>
		</div>`
		: "";

	return `
		<div class="mb-3">
			<p class="text-muted mb-1">${__("Role Profile")}: <strong>${frappe.utils.escape_html(profile)}</strong></p>
			<p class="text-muted mb-2">${__("Roles")}: <strong>${frappe.utils.escape_html(roles)}</strong></p>
			${readonly_message}
			${inactive_message}
		</div>
	`;
}
