frappe.ui.form.on("Order", {
	refresh(frm) {
		const processing_request = frm.__processing_options_request = (frm.__processing_options_request || 0) + 1;
		frm.remove_custom_button?.(__("Move to Processing"));
		if (should_show_assign_godowns(frm)) {
			const label = frm.doc.godown_assignment_pending ? __("Assign Godowns") : __("Edit Godown Assignments");
			frm.add_custom_button(label, () => assign_godowns(frm)).addClass("btn-primary");
		}
		if (should_show_move_to_processing(frm)) {
			const order = frm.doc.name;
			frappe.call({
				method: "kunal_enterprises.api.order_controls.processing_options",
				args: { order },
				callback(response) {
					if (frm.__processing_options_request === processing_request && frm.doc.name === order
						&& should_show_move_to_processing(frm) && response.message?.success && response.message.data?.can_process) {
						frm.add_custom_button(__("Move to Processing"), () => move_to_processing(frm)).addClass("btn-primary");
					}
				},
			});
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
		&& !frm.doc.godown_assignment_pending
		&& (frappe.session.user === "Administrator" || (frappe.user_roles || []).some((role) =>
			["Owner", "Admin", "Godown Allocator", "Order Coordinator", "Branch Manager", "Branch Employee"].includes(role)))
	);
}

function move_to_processing(frm) {
	if (frm.__processing_busy) return;
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save or discard your changes before moving this order to Processing."));
		return;
	}
	const order = frm.doc.name;
	frm.__processing_busy = true;
	frappe.confirm(__("Move this order to Processing?"), () => {
		if (frm.doc.name !== order || !should_show_move_to_processing(frm) || frm.is_dirty()) {
			frm.__processing_busy = false;
			return;
		}
		frappe.call({
			method: frappe.session.user === "Administrator" || (frappe.user_roles || []).some((role) =>
				["Owner", "Admin", "Godown Allocator", "Order Coordinator"].includes(role))
				? "kunal_enterprises.api.order_controls.mark_processing"
				: "kunal_enterprises.api.branch_orders.mark_visible_order_processing",
			args: { order },
			freeze: true,
			always() { frm.__processing_busy = false; },
			callback(response) {
				if (frm.doc.name !== order) return;
				if (!response.exc && response.message?.success) {
					if (response.message.data?.can_read_order === false) {
						// Allocators retain their existing Placed-only visibility after this action.
						frappe.show_alert({ message: __("Order moved to Processing"), indicator: "green" });
						frappe.set_route("List", "Order");
					} else {
						frm.reload_doc();
					}
				}
			},
		});
	}, () => { frm.__processing_busy = false; });
}

function should_show_assign_godowns(frm) {
	return !frm.is_new()
		&& (frm.doc.status === "Placed" || Boolean(frm.doc.godown_assignment_pending))
		&& !["Cancelled", "Partially Closed"].includes(frm.doc.status)
		&& (frappe.session.user === "Administrator"
			|| (frappe.user_roles || []).some((role) => ["Owner", "Admin", "Godown Allocator"].includes(role)))
		&& (frm.doc.status === "Placed"
			|| (frm.doc.godown_allocations || []).some((row) => !row.godown));
}

async function assign_godowns(frm) {
	if (frm.__assignment_loading || frm.__assignment_dialog?.is_visible) return;
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save or discard your changes before assigning godowns."));
		return;
	}
	let response;
	frm.__assignment_loading = true;
	try {
		response = await frappe.call({
			method: "kunal_enterprises.api.godown_assignment.assignment_options",
			type: "GET",
			args: { order: frm.doc.name, edit: frm.doc.status === "Placed" ? 1 : 0 },
			freeze: true,
			freeze_message: __("Loading godowns and available quantities..."),
		});
	} finally {
		frm.__assignment_loading = false;
	}
	if (!response.message?.success) {
		frappe.msgprint(response.message?.error?.message || __("Unable to load assignment options."));
		return;
	}
	const { allocations, godowns, editing } = response.message.data;
	if (!allocations.length || !godowns.length) {
		frappe.msgprint(!godowns.length ? __("No active godowns are available.") : __("There are no quantities awaiting assignment."));
		return;
	}
	const escape = frappe.utils.escape_html;
	const quantity = (value) => escape(frappe.format(value, { fieldtype: "Float" }, { only_value: true }));
	const heading = godowns.map((godown) => `<th colspan="2" class="text-center">${escape(godown.godown_name || godown.name)}</th>`).join("");
	const subheading = godowns.map(() => `<th class="text-right">${__("Available")}</th><th>${__("Allocate")}</th>`).join("");
	const pinned_item = "position:sticky;left:0;background:var(--card-bg,#fff);min-width:180px;z-index:2";
	const pinned_quantity = "position:sticky;left:180px;background:var(--card-bg,#fff);min-width:100px;z-index:2";
	const rows = allocations.map((row, index) => {
		const cells = godowns.map((godown, column) => {
			const stock = row.stock[godown.name];
			const assigned = row.current_allocations?.[godown.name];
			const initial = assigned ? String(assigned) : "";
			return `<td class="text-right">${stock == null ? "—" : quantity(stock)}</td>
				<td><input class="form-control input-sm" type="number" min="0" step="any"
					data-row="${index}" data-column="${column}" data-initial="${escape(initial)}" value="${escape(initial)}"
					aria-label="${escape(row.item_name)} — ${escape(godown.godown_name || godown.name)} — ${__("Allocate")}" placeholder="0"></td>`;
		}).join("");
		return `<tr><th scope="row" style="${pinned_item}">${escape(row.item_name)}<div class="small text-muted assignment-total" data-row="${index}" aria-live="polite" style="font-weight:normal"></div>${row.can_split === false ? `<div class="small text-muted">${__("Already dispatched: select one godown.")}</div>` : ""}</th>
			<td class="text-right" style="${pinned_quantity}">${escape(String(row.quantity))}</td>${cells}</tr>`;
	}).join("");
	let saving = false;
	const dialog = new frappe.ui.Dialog({
		title: editing && !frm.doc.godown_assignment_pending ? __("Edit Godown Assignments") : __("Assign Godowns"), size: "extra-large", static: true,
		fields: [{ fieldname: "matrix", fieldtype: "HTML", options: `
			<p>${__("Split each item’s order quantity across the godowns.")}</p>
			<div class="assignment-error text-danger" role="alert" style="display:none;margin-bottom:12px"></div>
			<div style="overflow-x:auto"><table class="table table-bordered" style="table-layout:fixed;width:${280 + godowns.length * 220}px">
				<colgroup><col style="width:180px"><col style="width:100px">${godowns.map(() => '<col style="width:100px"><col style="width:120px">').join("")}</colgroup>
				<thead><tr><th rowspan="2" style="${pinned_item};z-index:3">${__("Item Name")}</th><th rowspan="2" class="text-right" style="${pinned_quantity};z-index:3">${__("Order Qty")}</th>${heading}</tr>
				<tr>${subheading}</tr></thead><tbody>${rows}</tbody>
			</table></div><p class="small text-muted">${__("Available quantities reflect the latest stock sync. — means stock is unavailable. You can still allocate.")}</p>` }],
		primary_action_label: __("Save Assignments"),
		async primary_action() {
			if (saving) return;
			const assignments = [];
			for (let index = 0; index < allocations.length; index++) {
				const row = allocations[index];
				const splits = [];
				let total = 0;
				let invalid = false;
				dialog.fields_dict.matrix.$wrapper.find(`input[data-row="${index}"]`).each(function () {
					const amount = this.value === "" ? 0 : Number(this.value);
					if (!Number.isFinite(amount) || amount < 0 || this.validity.badInput) invalid = true;
					if (amount > 0) splits.push({ godown: godowns[Number(this.dataset.column)].name, quantity: amount });
					total += amount;
				});
				if (invalid || !splits.length || Math.abs(total - row.quantity) > Math.max(1e-9, row.quantity * 1e-9)) {
					dialog.fields_dict.matrix.$wrapper.find(".assignment-error").text(__("Allocated quantities for {0} must total {1} and cannot be negative.", [row.item_name, row.quantity])).show();
					return;
				}
				if (row.can_split === false && splits.length > 1) {
					dialog.fields_dict.matrix.$wrapper.find(".assignment-error").text(__("{0} has dispatch history and must be assigned to one godown.", [row.item_name])).show();
					return;
				}
				assignments.push(editing ? { item: row.item, splits } : { allocation: row.name, splits });
			}
			saving = true;
			dialog.get_primary_btn().prop("disabled", true);
			dialog.fields_dict.matrix.$wrapper.find("input").prop("disabled", true);
			try {
				const result = await frappe.call({
					method: editing ? "kunal_enterprises.api.godown_assignment.replace_assignments"
						: "kunal_enterprises.api.godown_assignment.assign_godowns",
					args: { order: frm.doc.name, assignments },
					freeze: true, freeze_message: __("Saving godown assignments..."),
				});
				if (!result.message?.success) {
					frappe.msgprint(result.message?.error?.message || __("Unable to assign godowns."));
					return;
				}
				dialog.hide();
				frappe.show_alert({ message: __("Godowns assigned"), indicator: "green" });
				const can_read_assigned = editing || frappe.session.user === "Administrator"
					|| (frappe.user_roles || []).some((role) => ["Owner", "Admin"].includes(role));
				// Placed orders remain visible for allocator edits; other completed assignments leave their queue.
				if (can_read_assigned) await frm.reload_doc();
				else frappe.set_route("List", "Order");
			} finally {
				saving = false;
				dialog.fields_dict.matrix.$wrapper.find("input").prop("disabled", false);
				dialog.get_primary_btn().prop("disabled", false);
			}
		},
	});
	const wrapper = dialog.fields_dict.matrix.$wrapper;
	protect_assignment_changes(dialog,
		() => wrapper.find("input").toArray().some((input) => input.value !== input.dataset.initial || input.validity.badInput),
		() => saving);
	frm.__assignment_dialog = dialog;
	dialog.show();
	function update_progress(index) {
		let total = 0;
		let invalid = false;
		wrapper.find(`input[data-row="${index}"]`).each(function () {
			const amount = this.value === "" ? 0 : Number(this.value);
			if (!Number.isFinite(amount) || amount < 0 || this.validity.badInput) invalid = true;
			else total += amount;
		});
		const requested = Number(allocations[index].quantity);
		const remaining = requested - total;
		const complete = !invalid && Math.abs(remaining) <= Math.max(1e-9, requested * 1e-9);
		// Match stored quantity precision and avoid floating point noise in progress text.
		const display = (value) => String(Number(value.toFixed(9)));
		const text = invalid ? __("Enter valid quantities")
			: __("Allocated {0} of {1} · {2}", [display(total), display(requested),
				complete ? __("Complete") : remaining < 0
					? __("Over by {0}", [display(-remaining)])
					: __("Remaining {0}", [display(remaining)])]);
		wrapper.find(`.assignment-total[data-row="${index}"]`).text(text)
			.toggleClass("text-success", complete)
			.toggleClass("text-danger", invalid || (!complete && remaining < 0))
			.toggleClass("text-muted", !complete && !invalid && remaining >= 0);
	}
	allocations.forEach((row, index) => update_progress(index));
	wrapper.find("input").on("input", function () {
		wrapper.find(".assignment-error").hide();
		update_progress(Number(this.dataset.row));
	});
}

// Static backdrop prevents Bootstrap from losing inputs before the user decides.
function protect_assignment_changes(dialog, has_changes, is_saving) {
	let warning_open = false;
	function request_close() {
		if (is_saving() || warning_open) return;
		if (!has_changes()) {
			dialog.hide();
			return;
		}
		warning_open = true;
		const warning = new frappe.ui.Dialog({
			title: __("Unsaved Assignments"), static: true,
			fields: [{ fieldtype: "HTML", options: `<p>${__("Your allocation quantities have not been saved. Discard these changes or continue editing?")}</p>` }],
			primary_action_label: __("Continue Editing"),
			primary_action() { warning.hide(); },
			secondary_action_label: __("Discard Changes"),
			secondary_action() { warning.hide(); dialog.hide(); },
			on_hide() { warning_open = false; },
		});
		warning.show();
	}
	dialog.get_close_btn().show().removeAttr("data-dismiss").on("click.assignment", (event) => {
		event.preventDefault();
		event.stopPropagation();
		request_close();
	});
	dialog.$wrapper.on("click.assignment", (event) => {
		if (event.target === event.currentTarget) request_close();
	});
	dialog.$wrapper.on("keydown.assignment", (event) => {
		if (event.key === "Escape") {
			event.preventDefault();
			event.stopPropagation();
			request_close();
		}
	});
}
