from frappe import _


def get_data():
	return {
		"fieldname": "sales_employee",
		"non_standard_fieldnames": {
			"Order WhatsApp Notification": "recipient_sales_employee",
		},
		"transactions": [
			{"label": _("Orders"), "items": ["Order"]},
			{"label": _("Communication"), "items": ["Order WhatsApp Notification"]},
		],
	}
