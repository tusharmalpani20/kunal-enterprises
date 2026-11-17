"""Bulk download policy, enforced after cookie and API-token authentication.

Keep this in the app rather than modifying Frappe. Read/print permissions still
apply: this guard can deny a bulk operation but never grants document access.
"""

from urllib.parse import unquote, urlsplit

from werkzeug.exceptions import HTTPException

import frappe

PRIVILEGED_ROLES = frozenset({"Owner", "Admin", "System Manager"})
MAX_LIST_ROWS = 200
EXPORT_FILE_SUFFIXES = (".csv", ".xlsx", ".xls", ".ods", ".zip", ".json", ".json.gz")
DENIED_METHODS = frozenset({
	"frappe.desk.reportview.export_query",
	"frappe.desk.query_report.export_query",
	"frappe.core.doctype.data_export.exporter.export_data",
	"frappe.core.doctype.data_import.data_import.download_template",
	"frappe.core.doctype.data_import.data_import.download_errored_template",
	"frappe.core.doctype.data_import.data_import.download_import_log",
	"frappe.core.doctype.prepared_report.prepared_report.download_attachment",
	"frappe.core.doctype.prepared_report.prepared_report.enqueue_json_to_csv_conversion",
	"frappe.email.doctype.auto_email_report.auto_email_report.download",
	"frappe.email.doctype.auto_email_report.auto_email_report.send_now",
	"frappe.core.api.file.zip_files",
	"frappe.utils.print_format.download_multi_pdf",
	"frappe.utils.print_format.download_multi_pdf_async",
	"frappe.utils.print_format.report_to_pdf",
	"frappe.contacts.doctype.contact.contact.download_vcards",
})
LIST_METHODS = frozenset({
	"frappe.client.get_list", "frappe.desk.reportview.get", "frappe.desk.reportview.get_list",
	"frappe.desk.search.search_link", "frappe.desk.search.search_widget",
})
DOWNLOAD_METHODS = frozenset({
	"download_file", "frappe.handler.download_file", "frappe.core.doctype.file.file.download_file",
})
DENIED_DOCUMENT_METHODS = {
	"Data Import": {"export_errored_rows", "download_import_log"},
}


def can_bulk_export(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(PRIVILEGED_ROLES.intersection(frappe.get_roles(user)))


def _deny():
	frappe.throw(frappe._("Bulk exports and downloads are restricted to Owner and Admin users."),
		frappe.PermissionError)


def _request_target(request, form):
	"""Use Frappe's own router so aliases, v2 shorthand and trailing slashes agree."""
	if form.get("cmd"):
		return form.cmd, {}
	if not request.path.startswith("/api/"):
		return "", {}
	from frappe.api import API_URL_MAP

	try:
		endpoint, arguments = API_URL_MAP.bind_to_environ(request.environ).match()
	except HTTPException:
		return "", {}  # Let the framework return its usual routing error.
	if endpoint.__name__ == "handle_rpc_call":
		method = arguments["method"]
		if arguments.get("doctype"):
			from frappe.modules.utils import load_doctype_module

			method = load_doctype_module(arguments["doctype"]).__name__ + "." + method
		elif not request.path.startswith("/api/v2/"):
			method = method.split("/")[0]
		return method, arguments
	return endpoint.__module__ + "." + endpoint.__name__, arguments


def _canonical_method(method):
	# Resolve aliases as the handler does, including its deprecated short names.
	if not method:
		return method
	from frappe.handler import get_attr

	try:
		fn = get_attr(method)
		return fn.__module__ + "." + fn.__name__
	except (AttributeError, ImportError, KeyError):
		return method


def _check_list_limits(form):
	for key in ("limit", "limit_page_length", "page_length"):
		value = form.get(key)
		if value is None or value == "":
			continue
		try:
			valid = 0 < int(value) <= MAX_LIST_ROWS
		except (TypeError, ValueError, OverflowError):
			valid = False
		if not valid:
			frappe.throw(frappe._("Please request between 1 and {0} rows per page.").format(MAX_LIST_ROWS),
				frappe.PermissionError)
	# reportview otherwise defaults to an unlimited DatabaseQuery when omitted.
	if form.get("limit_page_length") in (None, ""):
		form.limit_page_length = 20


def _check_document_method(method, arguments, form):
	if method.endswith("run_doc_method") or form.get("document") or form.get("docs"):
		doc_method = form.get("method")
	else:
		doc_method = arguments.get("method") or form.get("run_method") or form.get("method")
	doctype = arguments.get("doctype") or form.get("dt")
	if method.endswith("run_doc_method") or form.get("document") or form.get("docs"):
		doc = form.get("document") or form.get("docs") or {}
		if isinstance(doc, str):
			doc = frappe.parse_json(doc)
		if isinstance(doc, dict):
			doctype = doc.get("doctype") or doctype
	if doc_method in DENIED_DOCUMENT_METHODS.get(doctype, set()):
		_deny()


def _check_file_url(file_url):
	if not file_url:
		return
	path = unquote(urlsplit(file_url).path)
	# Match metadata as well as extensions: prepared reports can use .gz, while
	# order PDFs and image previews must continue to work.
	files = frappe.get_all("File", filters={"file_url": path},
		fields=["attached_to_doctype", "folder", "file_name"])
	for file in files:
		if (file.attached_to_doctype in {"Report", "Prepared Report", "Auto Email Report"}
			or file.folder == "Home/Exported Reports"
			or (file.file_name or "").lower().endswith(EXPORT_FILE_SUFFIXES)):
			_deny()


def guard_request():
	"""auth_hooks runs after API credentials resolve to the actual user."""
	if can_bulk_export():
		return
	request, form = frappe.request, frappe.form_dict
	method, arguments = _request_target(request, form)
	method = _canonical_method(method)
	if method in DENIED_METHODS:
		_deny()
	if method in LIST_METHODS or method in {"frappe.api.v1.document_list", "frappe.api.v2.document_list"}:
		_check_list_limits(form)
	_check_document_method(method, arguments, form)
	if request.path.startswith(("/private/files/", "/files/")):
		_check_file_url(request.path)
	elif method in DOWNLOAD_METHODS:
		_check_file_url(form.get("file_url"))


def boot_session(bootinfo):
	bootinfo.kunal_can_bulk_export = can_bulk_export()
	bootinfo.kunal_max_list_rows = MAX_LIST_ROWS


def guard_auto_email_report(doc, method=None):
	# A Report Manager must not bypass the download policy by scheduling an
	# emailed spreadsheet through an ordinary document save.
	if not can_bulk_export():
		_deny()


def guard_response(response, request=None):
	"""Backstop new file-producing endpoints without blocking JSON screen data."""
	if can_bulk_export() or response.status_code >= 400:
		return
	content_type = response.mimetype or ""
	disposition = response.headers.get("Content-Disposition", "").lower()
	if (content_type in {"text/csv", "application/zip", "application/x-zip-compressed",
		"application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		"application/vnd.oasis.opendocument.spreadsheet"}
		or ("attachment" in disposition and any(ext in disposition for ext in
			(".csv", ".xlsx", ".xls", ".ods", ".zip", ".json")))):
		response.status_code = 403
		response.set_data('{"message":"Bulk exports and downloads are restricted to Owner and Admin users."}')
		response.headers.pop("Content-Disposition", None)
		response.content_type = "application/json"


def keep_report_file_private(doc, method=None):
	# Public files bypass Python in bench/nginx. Export artifacts must therefore
	# stay private even when created by an unrestricted account.
	if (doc.attached_to_doctype in {"Report", "Prepared Report", "Auto Email Report"}
		or doc.folder == "Home/Exported Reports"
		or (doc.file_name or "").lower().endswith(EXPORT_FILE_SUFFIXES)):
		doc.is_private = 1
		return True
	return False
