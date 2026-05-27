import frappe


def create_success_response(message, data=None, status_code=200):
	frappe.local.response["http_status_code"] = status_code
	response = {
		"success": True,
		"status": "success",
		"message": message,
		"http_status_code": status_code,
	}
	if data is not None:
		response["data"] = data
	return response


def handle_error_response(error, error_message, status_code=None, log_title=None):
	status_code = status_code or _status_code_for_error(error)
	frappe.local.response["http_status_code"] = status_code
	frappe.log_error(frappe.get_traceback(), (log_title or error_message)[:140])
	return {
		"success": False,
		"status": "error",
		"message": error_message,
		"error": {
			"message": str(error),
		},
		"http_status_code": status_code,
	}


def _status_code_for_error(error):
	if isinstance(error, frappe.PermissionError):
		return 403
	if isinstance(error, frappe.DoesNotExistError):
		return 404
	if isinstance(error, frappe.ValidationError):
		return 400
	return 500


def convert_headers_to_dict(headers):
	return dict(headers or {})
