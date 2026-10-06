from frappe import _


def get_data():
	return {
		"fieldname": "order",
		"non_standard_fieldnames": {
			"Tally Voucher": "order_number",
		},
		"transactions": [
			{"label": _("Quick Order"), "items": ["Quick Order Request"]},
			{"label": _("Confirmation"), "items": ["Order PDF", "Order WhatsApp Notification"]},
			{"label": _("Reconciliation"), "items": ["Tally Voucher", "Order Reconciliation Log"]},
		],
	}
