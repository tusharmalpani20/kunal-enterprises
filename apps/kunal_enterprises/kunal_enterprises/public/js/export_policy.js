// Server-side policy remains authoritative; omit actions that would be refused.
(() => {
	const privileged_roles = new Set(["Owner", "Admin", "System Manager"]);
	const can_export = () =>
		frappe.session.user === "Administrator" ||
		(frappe.user_roles || []).some((role) => privileged_roles.has(role));
	const matches = (label, source, context) =>
		label === __(source) || (context && label === __(source, null, context));
	const is_export_label = (label) =>
		["Export", "Export as zip", "Download Report", "Download as CSV", "Setup Auto Email"].some((source) =>
			matches(label, source, "Button in list view actions menu")
		);
	const is_report = () => {
		const route = frappe.get_route();
		return route[0] === "query-report" || (route[0] === "List" && route[2] === "Report");
	};
	const denied_report_print = (label) =>
		is_report() && (matches(label, "Print") || matches(label, "PDF"));
	const max_page_length = () => frappe.boot?.kunal_max_list_rows || 200;
	let paging_policy_installed = false;
	const install_paging_policy = () => {
		const base_list = frappe.views?.BaseList?.prototype;
		if (!base_list || paging_policy_installed) return;
		paging_policy_installed = true;
		const original_paging = base_list.setup_paging_area;
		base_list.setup_paging_area = function (...args) {
			if (!can_export()) {
				const allowed_choices = [20, 100, 500, 2500].filter(value => value <= max_page_length());
				const fallback = allowed_choices.at(-1) || max_page_length();
				if (this.page_length > max_page_length()) this.page_length = fallback;
				if (this.selected_page_count > max_page_length()) {
					this.selected_page_count = fallback;
				}
			}
			const result = original_paging.apply(this, args);
			if (!can_export()) {
				this.$paging_area.find(".btn-paging").filter(function () {
					return Number($(this).data("value")) > max_page_length();
				}).remove();
			}
			return result;
		};
	};

	const original_can_export = frappe.model.can_export;
	frappe.model.can_export = function (...args) {
		return can_export() && original_can_export.apply(this, args);
	};

	// Page is in the Desk bundle, unlike the lazily loaded list/report classes.
	// Intercept their shared menu builder so newly opened views inherit the policy.
	const page = frappe.ui.Page.prototype;
	const original_dropdown = page.add_dropdown_item;
	page.add_dropdown_item = function (options) {
		// BaseList is loaded lazily. Its page menus are built before its pager.
		install_paging_policy();
		const bulk_print =
			options.parent === this.actions &&
			matches(options.label, "Print", "Button in list view actions menu");
		if (!can_export() && (is_export_label(options.label) || bulk_print || denied_report_print(options.label))) {
			return $([]);
		}
		return original_dropdown.call(this, options);
	};

	const original_inner_button = page.add_inner_button;
	page.add_inner_button = function (label, ...args) {
		if (!can_export() && is_export_label(label)) return $([]);
		return original_inner_button.call(this, label, ...args);
	};
	install_paging_policy();
})();
