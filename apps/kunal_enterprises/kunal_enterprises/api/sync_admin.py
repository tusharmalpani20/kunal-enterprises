import frappe

from kunal_enterprises.api.utils import create_success_response, handle_error_response
from kunal_enterprises.cron.reconciliation import run_reconciliation
from kunal_enterprises.cron.tally_sync import sync_stock_snapshots, sync_tally_masters, sync_tally_vouchers
from kunal_enterprises.integrations.tally_stock_excel import import_tally_stock_excel_file


OWNER_ADMIN_ROLES = ("Owner", "Admin")


@frappe.whitelist(methods=["POST"])
def sync_masters_now(role=None, records=None):
	try:
		_require_owner_admin()
		run = sync_tally_masters(records)
		return create_success_response("Master sync completed", _serialize_run(run))
	except Exception as error:
		return handle_error_response(error, "Unable to sync masters")


@frappe.whitelist(methods=["POST"])
def sync_stock_now(role=None, records=None):
	try:
		_require_owner_admin()
		run = sync_stock_snapshots(records)
		return create_success_response("Stock sync completed", _serialize_run(run))
	except Exception as error:
		return handle_error_response(error, "Unable to sync stock")


@frappe.whitelist(methods=["POST"])
def sync_vouchers_now(role=None, records=None):
	try:
		_require_owner_admin()
		run = sync_tally_vouchers(records)
		return create_success_response("Voucher sync completed", _serialize_run(run))
	except Exception as error:
		return handle_error_response(error, "Unable to sync vouchers")


@frappe.whitelist(methods=["POST"])
def import_stock_excel_now(file_url, role=None):
	try:
		_require_owner_admin()
		run = import_tally_stock_excel_file(file_url)
		return create_success_response("Stock Excel import completed", _serialize_run(run))
	except Exception as error:
		return handle_error_response(error, "Unable to import stock Excel")


@frappe.whitelist(methods=["POST"])
def run_reconciliation_now(role=None):
	try:
		_require_owner_admin()
		run = run_reconciliation()
		return create_success_response("Reconciliation completed", _serialize_run(run))
	except Exception as error:
		return handle_error_response(error, "Unable to run reconciliation")


def _require_owner_admin():
	if frappe.session.user == "Administrator":
		return
	if not set(OWNER_ADMIN_ROLES).intersection(frappe.get_roles(frappe.session.user)):
		frappe.throw("Only Owner/Admin can run sync actions", title="Owner/Admin Required")


def _serialize_run(run):
	return {
		"run": run.name,
		"sync_type": run.sync_type,
		"status": run.status,
		"records_seen": run.records_seen,
		"records_processed": run.records_processed,
		"errors_count": run.errors_count,
	}
