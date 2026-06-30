app_name = "kunal_enterprises"
app_title = "Kunal Enterprises"
app_logo_url = "/assets/kunal_enterprises/images/kunal_enterprises_logo.svg"
app_publisher = "Kunal Enterprises"
app_description = "Kunal Enterprise Tally-connected order system"
app_email = "admin@kunal-enterprises.local"
app_license = "mit"

KUNAL_ROLES = ["Owner", "Admin", "Branch Manager", "Branch Employee"]

fixtures = [
	{
		"dt": "Role",
		"filters": [["role_name", "in", KUNAL_ROLES]],
	},
	{
		"dt": "Role Profile",
		"filters": [["name", "in", KUNAL_ROLES]],
	},
	{
		"dt": "Custom DocPerm",
		"filters": [["parent", "in", ["User", "Role", "Role Profile"]], ["role", "in", ["Owner", "Admin"]]],
	},
	{
		"dt": "Workspace",
		"filters": [["name", "in", ["Kunal Operations", "Kunal Admin"]]],
	}
]

scheduler_events = {
	"cron": {
		"*/5 * * * *": [
			"kunal_enterprises.integrations.tally_postgres.import_masters",
			"kunal_enterprises.integrations.tally_postgres.import_stock_snapshots",
			"kunal_enterprises.integrations.tally_postgres.import_vouchers",
			"kunal_enterprises.cron.reconciliation.run_reconciliation",
		]
	}
}

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
add_to_apps_screen = [
	{
		"name": "kunal_enterprises",
		"logo": "/assets/kunal_enterprises/images/kunal_enterprises_logo.svg",
		"title": "Kunal Enterprises",
		"route": "/kunal_enterprises",
		"has_permission": "kunal_enterprises.api.permission.has_app_permission"
	}
]

website_context = {
	"favicon": "/assets/kunal_enterprises/images/kunal_enterprises_favicon.png"
}

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/kunal_enterprises/css/kunal_enterprises.css"
# app_include_js = "/assets/kunal_enterprises/js/kunal_enterprises.js"

# include js, css files in header of web template
# web_include_css = "/assets/kunal_enterprises/css/kunal_enterprises.css"
# web_include_js = "/assets/kunal_enterprises/js/kunal_enterprises.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "kunal_enterprises/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
	"User": "public/js/user.js",
}
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "kunal_enterprises/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

boot_session = ["kunal_enterprises.desk_navigation.limit_workspaces"]

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "kunal_enterprises.utils.jinja_methods",
# 	"filters": "kunal_enterprises.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "kunal_enterprises.install.before_install"
# after_install = "kunal_enterprises.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "kunal_enterprises.uninstall.before_uninstall"
# after_uninstall = "kunal_enterprises.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "kunal_enterprises.utils.before_app_install"
# after_app_install = "kunal_enterprises.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "kunal_enterprises.utils.before_app_uninstall"
# after_app_uninstall = "kunal_enterprises.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "kunal_enterprises.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

permission_query_conditions = {
	"Order": "kunal_enterprises.permission_query_conditions.orders.get_permission_query_conditions",
	"User": "kunal_enterprises.permission_guards.owner_admin.user_query",
	"User Permission": "kunal_enterprises.permission_guards.owner_admin.user_permission_query",
	"Role": "kunal_enterprises.permission_guards.owner_admin.role_query",
	"Role Profile": "kunal_enterprises.permission_guards.owner_admin.role_profile_query",
}

has_permission = {
	"Order": "kunal_enterprises.permission_query_conditions.orders.has_permission",
	"User": "kunal_enterprises.permission_guards.owner_admin.has_user_permission",
	"User Permission": "kunal_enterprises.permission_guards.owner_admin.has_user_permission_doc",
	"Role": "kunal_enterprises.permission_guards.owner_admin.has_role_permission",
	"Role Profile": "kunal_enterprises.permission_guards.owner_admin.has_role_profile_permission",
}

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"User": {
		"before_insert": "kunal_enterprises.permission_guards.owner_admin.guard_user_write",
		"before_save": "kunal_enterprises.permission_guards.owner_admin.guard_user_write",
		"before_rename": "kunal_enterprises.permission_guards.owner_admin.guard_user_rename",
		"on_trash": "kunal_enterprises.permission_guards.owner_admin.guard_user_delete",
	},
	"Role": {
		"before_save": "kunal_enterprises.permission_guards.owner_admin.guard_role_write",
		"on_trash": "kunal_enterprises.permission_guards.owner_admin.guard_role_delete",
	},
	"Role Profile": {
		"before_save": "kunal_enterprises.permission_guards.owner_admin.guard_role_profile_write",
		"on_trash": "kunal_enterprises.permission_guards.owner_admin.guard_role_profile_delete",
	},
	"User Permission": {
		"before_insert": "kunal_enterprises.permission_guards.owner_admin.guard_user_permission_write",
		"before_save": "kunal_enterprises.permission_guards.owner_admin.guard_user_permission_write",
		"on_trash": "kunal_enterprises.permission_guards.owner_admin.guard_user_permission_delete",
	},
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"kunal_enterprises.tasks.all"
# 	],
# 	"daily": [
# 		"kunal_enterprises.tasks.daily"
# 	],
# 	"hourly": [
# 		"kunal_enterprises.tasks.hourly"
# 	],
# 	"weekly": [
# 		"kunal_enterprises.tasks.weekly"
# 	],
# 	"monthly": [
# 		"kunal_enterprises.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "kunal_enterprises.install.before_tests"

# Overriding Methods
# ------------------------------
#
override_whitelisted_methods = {
	"frappe.core.doctype.user.user.get_all_roles": "kunal_enterprises.permission_guards.owner_admin.get_all_roles",
	"frappe.core.doctype.user.user.get_roles": "kunal_enterprises.permission_guards.owner_admin.get_roles",
	"frappe.core.doctype.user.user.get_role_profile": "kunal_enterprises.permission_guards.owner_admin.get_role_profile",
	"frappe.core.doctype.user.user.reset_password": "kunal_enterprises.permission_guards.owner_admin.reset_password",
	"frappe.desk.desktop.get_workspace_sidebar_items": "kunal_enterprises.desk_navigation.get_workspace_sidebar_items",
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "kunal_enterprises.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["kunal_enterprises.utils.before_request"]
# after_request = ["kunal_enterprises.utils.after_request"]

# Job Events
# ----------
# before_job = ["kunal_enterprises.utils.before_job"]
# after_job = ["kunal_enterprises.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"kunal_enterprises.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
