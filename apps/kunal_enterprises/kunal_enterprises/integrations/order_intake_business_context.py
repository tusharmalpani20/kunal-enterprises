"""Small, editable business context; warehouse identities come from masters."""
import frappe


def business_context():
	settings = frappe.get_single('Order Intake Settings')
	company = (settings.get('company_name') or '').strip()
	aliases = list(dict.fromkeys(line.strip() for line in
		(settings.get('company_aliases') or '').splitlines() if line.strip()))
	# Bound additional prompt data. Missing or inactive godowns must not become
	# invented master links; their original message wording is still retained.
	warehouses = frappe.get_all('Tally Godown', filters={'is_active': 1},
		fields=['name', 'godown_name'], order_by='name', limit_page_length=201)
	return dict(receiving_company=company or None, company_aliases=aliases,
		warehouses=warehouses[:200], warehouses_truncated=len(warehouses) > 200)
