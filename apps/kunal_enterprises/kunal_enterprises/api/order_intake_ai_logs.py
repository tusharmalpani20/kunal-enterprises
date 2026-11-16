"""Restricted, permission-aware numeric usage and cost summaries."""
import frappe
from frappe.utils import getdate, add_days, nowdate

from kunal_enterprises.integrations.order_intake_ai_logging import RUN


def _require_access():
	if frappe.session.user != "Administrator" and not {"Owner", "Admin", "System Manager"}.intersection(frappe.get_roles()):
		frappe.throw("Owner, Admin or System Manager is required for AI run logs", frappe.PermissionError)
	if not frappe.has_permission(RUN, "read"):
		frappe.throw("Read access to AI run logs is required", frappe.PermissionError)


def _aggregate(filters, fields):
	rows = frappe.get_list(RUN, filters=filters, fields=fields, limit_page_length=1, order_by="")
	return rows[0] if rows else {}


@frappe.whitelist(methods=["GET"])
def summary(from_date=None, to_date=None, provider=None, model=None):
	_require_access()
	start, end = getdate(from_date or add_days(nowdate(), -29)), getdate(to_date or nowdate())
	if start > end:
		frappe.throw("The start date must not follow the end date")
	filters = [["started_at", ">=", start], ["started_at", "<", add_days(end, 1)]]
	if provider:
		filters.append(["provider", "=", provider])
	if model:
		filters.append(["grouping_model", "=", model])
	base = _aggregate(filters, ["count(name) as runs", "sum(wire_attempts) as wire_attempts", "sum(input_tokens) as input_tokens",
		"sum(output_tokens) as output_tokens", "sum(cached_input_tokens) as cached_input_tokens", "sum(cache_write_tokens) as cache_write_tokens", "sum(reasoning_tokens) as reasoning_tokens",
		"sum(unknown_usage_calls) as unknown_usage_calls", "sum(unknown_cost_calls) as unknown_cost_calls",
		"sum(cost_known_calls) as cost_known_calls", "sum(provider_cost_known_calls) as provider_cost_known_calls",
		"sum(estimated_cost_usd) as known_estimated_spend_usd", "sum(provider_cost_usd) as known_provider_spend_usd"])
	complete = _aggregate(filters + [["cost_complete", "=", 1], ["status", "not in", ["Running", "Awaiting Commit"]]],
		["count(name) as count", "sum(estimated_cost_usd) as cost"])
	created = _aggregate(filters + [["status", "in", ["Drafted", "Unresolved"]]], ["sum(created_request_count) as created", "sum(updated_request_count) as updated"])
	base.update(from_date=str(start), to_date=str(end), complete_cost_runs=complete.get("count") or 0,
		requests_created=created.get("created") or 0, requests_updated=created.get("updated") or 0,
		average_complete_run_cost_usd=float(complete.get("cost") or 0) / complete["count"] if complete.get("count") else None,
		known_spend_per_created_request_usd=float(base.get("known_estimated_spend_usd") or 0) / created["created"] if created.get("created") else None,
		note="Known spend includes failed calls and retries. Missing usage/rates remain unknown. Cost per created request is a shared known-spend basis, not a billed per-order allocation.")
	return base
