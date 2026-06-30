const BRANCH_ASSIGNABLE_ROLES = ["Branch Manager", "Branch Employee"];
const GLOBAL_USER_ROLES = ["Owner", "Admin"];

frappe.ui.form.on("User", {
	onload(frm) {
		disable_user_email_delivery(frm);
	},
	refresh(frm) {
		disable_user_email_delivery(frm);
		remove_email_account_actions(frm);

		if (frm.is_new() || !can_manage_user_branches(frm)) {
			return;
		}

		frm.add_custom_button(__("Branches"), () => {
			show_user_branch_dialog(frm);
		}).addClass("btn-primary");
	},
});

function disable_user_email_delivery(frm) {
	if (frm.is_new()) {
		frm.set_value("send_welcome_email", 0);
	}
}

function remove_email_account_actions(frm) {
	frm.remove_custom_button(__("Create User Email"));
	frm.remove_custom_button(__("Reset Password"), __("Password"));

	setTimeout(() => {
		frm.remove_custom_button(__("Create User Email"));
		frm.remove_custom_button(__("Reset Password"), __("Password"));
	}, 0);
}

function can_manage_user_branches(frm) {
	const roles = frappe.user_roles || [];
	const can_manage = frappe.session.user === "Administrator" || roles.includes("Owner") || roles.includes("Admin");
	return can_manage && can_manage_target_branches(frm);
}

function can_manage_target_branches(frm) {
	const target_roles = get_target_roles(frm);
	const is_global_user = target_roles.some((role) => GLOBAL_USER_ROLES.includes(role));
	const is_branch_user = target_roles.some((role) => BRANCH_ASSIGNABLE_ROLES.includes(role));
	return is_branch_user && !is_global_user;
}

function get_target_roles(frm) {
	const role_profile = frm.doc.role_profile_name ? [frm.doc.role_profile_name] : [];
	const assigned_roles = (frm.doc.roles || []).map((row) => row.role).filter(Boolean);
	return [...role_profile, ...assigned_roles];
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
	const inactive_branches = (data.branch_details || []).filter((branch) => !branch.is_active);
	const summary = build_branch_dialog_summary(data, inactive_branches);
	const fields = [
		{
			fieldname: "summary",
			fieldtype: "HTML",
			options: summary,
		},
	];

	if (data.can_edit) {
		fields.push({
			fieldname: "branch_table",
			fieldtype: "HTML",
			label: __("Branches"),
		});
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Branches - {0}", [frm.doc.full_name || frm.doc.name]),
		size: "large",
		fields,
		primary_action_label: __("Close"),
		primary_action() {
			dialog.hide();
		},
	});

	dialog.show();
	if (!data.can_edit) {
		return;
	}
	render_branch_assignment_table(dialog, frm, data);
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

function render_branch_assignment_table(dialog, frm, data) {
	const wrapper = dialog.fields_dict.branch_table.$wrapper;
	const branch_options = data.branch_options || build_branch_options_from_details(data);

	if (!branch_options.length) {
		wrapper.html(`<p class="text-muted">${__("No active branches found.")}</p>`);
		return;
	}

	const rows = branch_options.map((branch) => build_branch_assignment_row(branch, data.can_edit)).join("");
	wrapper.html(`
		<div class="table-responsive">
			<table class="table table-bordered table-sm branch-assignment-table">
				<thead>
					<tr>
						<th>${__("Branch")}</th>
						<th class="text-center" style="width: 150px;">${__("Status")}</th>
						<th class="text-right" style="width: 120px;">${__("Action")}</th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>
		</div>
	`);

	wrapper.find("[data-branch-action]").on("click", function () {
		const button = $(this);
		update_branch_assignment(dialog, frm, data, button.attr("data-branch"), button.attr("data-branch-action"));
	});
}

function build_branch_assignment_row(branch, can_edit) {
	const assigned = Boolean(branch.assigned);
	const action = assigned ? "unassign" : "assign";
	const action_label = assigned ? __("Unassign") : __("Assign");
	const active_label = branch.is_active ? __("Active") : __("Inactive");
	const assigned_label = assigned ? __("Assigned") : __("Not Assigned");
	const can_update = can_edit && (branch.is_active || assigned);
	const disabled = can_update ? "" : "disabled";
	const button = can_edit
		? `<button class="btn btn-xs btn-default" data-branch="${frappe.utils.escape_html(branch.name)}" data-branch-action="${action}" ${disabled}>
			${action_label}
		</button>`
		: `<span class="text-muted">-</span>`;

	return `
		<tr>
			<td>
				<div class="font-weight-bold">${frappe.utils.escape_html(branch.branch_name || branch.name)}</div>
				<div class="text-muted small">${frappe.utils.escape_html(branch.name)}</div>
			</td>
			<td class="text-center">
				<span class="indicator-pill ${assigned ? "green" : "gray"}" style="white-space: nowrap;">${assigned_label}</span>
				<div class="text-muted small">${active_label}</div>
			</td>
			<td class="text-right">${button}</td>
		</tr>
	`;
}

function update_branch_assignment(dialog, frm, data, branch, action) {
	const assigned = new Set(data.branches || []);
	if (action === "assign") {
		assigned.add(branch);
	} else {
		assigned.delete(branch);
	}

	const branch_options = data.branch_options || [];
	const branches = branch_options.map((row) => row.name).filter((name) => assigned.has(name));

	frappe.call({
		method: "kunal_enterprises.api.user_branch_permissions.set_user_branches",
		args: {
			user: frm.doc.name,
			branches: JSON.stringify(branches),
		},
		freeze: true,
		freeze_message: __("Saving branch assignment..."),
		callback(response) {
			const result = response.message;
			if (!result) {
				return;
			}

			data.branches = result.branches || [];
			const updated = new Set(data.branches);
			data.branch_options = branch_options.map((row) => ({
				...row,
				assigned: updated.has(row.name),
			})).filter((row) => row.is_active || row.assigned);
			render_branch_assignment_table(dialog, frm, data);
			frappe.show_alert({
				message: __("Branch assignment updated"),
				indicator: "green",
			});
		},
	});
}

function build_branch_options_from_details(data) {
	const assigned = new Set(data.branches || []);
	return (data.branch_details || []).map((branch) => ({
		...branch,
		assigned: assigned.has(branch.name),
	}));
}
