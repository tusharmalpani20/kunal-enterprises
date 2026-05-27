import frappe

from kunal_enterprises.api.utils import create_success_response, handle_error_response


@frappe.whitelist(allow_guest=True, methods=["GET"])
def smoke():
	try:
		installed_apps = frappe.get_installed_apps()
		database_type = frappe.conf.get("db_type")
		frappe.db.sql("select 1")

		return create_success_response(
			"Kunal Enterprises foundation is healthy",
			{
				"app": "kunal_enterprises",
				"database_type": database_type,
				"site": frappe.local.site,
				"installed_apps": installed_apps,
				"checks": {
					"database_reachable": True,
					"custom_app_installed": "kunal_enterprises" in installed_apps,
					"frappe_whatsapp_installed": "frappe_whatsapp" in installed_apps,
				},
			},
		)
	except Exception as error:
		return handle_error_response(error, "Kunal Enterprises foundation smoke check failed")
