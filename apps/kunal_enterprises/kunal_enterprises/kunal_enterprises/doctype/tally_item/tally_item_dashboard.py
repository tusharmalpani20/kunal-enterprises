from frappe import _


def get_data():
	return {
		"fieldname": "item",
		"transactions": [
			{"label": _("Orders"), "items": ["Order Item", "Order Godown Allocation"]},
			{"label": _("Tally"), "items": ["Tally Stock Snapshot", "Tally Voucher Line"]},
		],
	}
