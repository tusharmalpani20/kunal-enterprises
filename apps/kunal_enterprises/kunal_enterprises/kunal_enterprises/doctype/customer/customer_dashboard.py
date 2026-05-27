from frappe import _


def get_data():
	return {
		"fieldname": "customer",
		"non_standard_fieldnames": {
			"Order WhatsApp Notification": "recipient_customer",
			"Sales Employee Assigned Customer": "customer",
		},
		"transactions": [
			{"label": _("Orders"), "items": ["Order"]},
			{"label": _("Communication"), "items": ["Order PDF", "Order WhatsApp Notification"]},
			{"label": _("Access"), "items": ["Sales Employee Assigned Customer"]},
		],
	}
