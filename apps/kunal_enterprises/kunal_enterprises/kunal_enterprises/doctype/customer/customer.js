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
	let selected_ledger = null;
	let search_timer = null;

	const dialog = new frappe.ui.Dialog({
		title: __("Set Client Code"),
		fields: [
			{
				fieldname: "ledger_search",
				fieldtype: "Data",
				label: __("Search Tally Ledger"),
				default: frm.doc.client_code || "",
			},
			{
				fieldname: "ledger_results",
				fieldtype: "HTML",
			},
		],
		primary_action_label: __("Save"),
		primary_action() {
			if (!selected_ledger) {
				frappe.msgprint(__("Select a Tally Ledger first"));
				return;
			}
			frappe.call({
				method: "kunal_enterprises.kunal_enterprises.doctype.customer.customer.set_customer_client_code",
				args: {
					customer_name: frm.doc.name,
					client_code: selected_ledger.client_code,
				},
				freeze: true,
				callback(response) {
					if (!response.exc) {
						dialog.hide();
						frm.reload_doc();
					}
				},
			});
		},
	});

	const results_wrapper = dialog.fields_dict.ledger_results.$wrapper.get(0);
	const search_input = dialog.fields_dict.ledger_search.$input;
	results_wrapper.style.maxHeight = "320px";
	results_wrapper.style.overflowY = "auto";
	results_wrapper.style.marginTop = "8px";

	function render_results(ledgers) {
		results_wrapper.innerHTML = "";

		if (!ledgers.length) {
			const empty = document.createElement("div");
			empty.className = "text-muted small";
			empty.style.padding = "10px 0";
			empty.textContent = __("No unassigned active Tally Ledgers found");
			results_wrapper.appendChild(empty);
			return;
		}

		const list = document.createElement("div");
		list.className = "list-group";

		ledgers.forEach((ledger) => {
			const option = document.createElement("button");
			option.type = "button";
			option.className = "list-group-item list-group-item-action";
			option.style.textAlign = "left";

			const title = document.createElement("div");
			title.style.fontWeight = "600";
			title.textContent = ledger.client_code;

			const subtitle = document.createElement("div");
			subtitle.className = "text-muted small";
			subtitle.textContent = ledger.ledger_name || "";

			option.appendChild(title);
			option.appendChild(subtitle);
			if (ledger.mapped_customer) {
				const mapped_to = ledger.mapped_customer_business || ledger.mapped_customer_name || ledger.mapped_customer;
				const assignment = document.createElement("div");
				assignment.className = "small text-danger";
				assignment.style.marginTop = "4px";
				assignment.style.fontWeight = "600";
				assignment.textContent = __("Already assigned to Customer: {0}", [mapped_to]);
				option.appendChild(assignment);
			}
			option.addEventListener("click", () => {
				selected_ledger = ledger;
				search_input.val(`${ledger.client_code} - ${ledger.ledger_name || ""}`);
				Array.from(list.children).forEach((child) => child.classList.remove("active"));
				option.classList.add("active");
			});
			list.appendChild(option);
		});

		results_wrapper.appendChild(list);
	}

	function search_ledgers() {
		frappe.call({
			method: "kunal_enterprises.kunal_enterprises.doctype.customer.customer.search_tally_customer_ledgers",
			args: {
				search_text: search_input.val(),
				customer_name: frm.doc.name,
				limit: 10,
			},
			callback(response) {
				if (!response.exc) {
					render_results(response.message || []);
				}
			},
		});
	}

	search_input.on("input", () => {
		selected_ledger = null;
		clearTimeout(search_timer);
		search_timer = setTimeout(search_ledgers, 250);
	});

	dialog.show();
	search_ledgers();
}
