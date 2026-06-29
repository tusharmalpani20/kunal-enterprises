frappe.listview_settings["Tally Stock Snapshot"] = {
	onload(listview) {
		if (!can_import_tally_stock()) {
			return;
		}

		listview.page.add_inner_button(__("Import Tally Stock Excel"), () => {
			new frappe.ui.FileUploader({
				folder: "Home/Attachments",
				restrictions: {
					allowed_file_types: [".xls", ".xlsx", ".xlsm"],
				},
				on_success(file) {
					frappe.call({
						method: "kunal_enterprises.api.sync_admin.import_stock_excel_now",
						args: {
							file_url: file.file_url,
						},
						freeze: true,
						freeze_message: __("Importing Tally stock..."),
						callback(response) {
							const result = response.message;
							if (!result || !result.success) {
								return;
							}

							const data = result.data || {};
							frappe.msgprint({
								title: __("Tally Stock Imported"),
								indicator: data.errors_count ? "orange" : "green",
								message: __(
									"Rows found: {0}<br>Rows processed: {1}<br>Errors: {2}",
									[data.records_seen || 0, data.records_processed || 0, data.errors_count || 0]
								),
							});
							listview.refresh();
						},
					});
				},
			});
		});
	},
};

function can_import_tally_stock() {
	const roles = frappe.user_roles || [];
	return frappe.session.user === "Administrator" || roles.includes("Owner") || roles.includes("Admin");
}
