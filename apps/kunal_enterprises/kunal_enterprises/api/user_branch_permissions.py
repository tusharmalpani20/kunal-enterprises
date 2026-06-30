import json

import frappe
from frappe import _

from kunal_enterprises.permission_guards import owner_admin


OWNER_ROLE = owner_admin.OWNER_ROLE
ADMIN_ROLE = owner_admin.ADMIN_ROLE
BRANCH_ROLES = owner_admin.BRANCH_ROLES
PORTAL_BRANCH_DOCTYPE = owner_admin.PORTAL_BRANCH_DOCTYPE


@frappe.whitelist()
def get_user_branches(user):
	actor = _require_owner_admin_actor()
	state = _get_target_state(user)
	_validate_target_read(actor, state)

	branches = _current_branch_values(state["user"])
	return {
		"user": state["user"],
		"roles": sorted(state["roles"]),
		"role_profile": state["role_profile"],
		"branches": branches,
		"branch_details": _branch_details(branches),
		"branch_options": _branch_options(branches),
		"can_edit": _can_edit_target(state),
		"is_global_user": state["is_global_user"],
	}


@frappe.whitelist(methods=["POST"])
def set_user_branches(user, branches=None):
	actor = _require_owner_admin_actor()
	state = _get_target_state(user)
	_validate_target_read(actor, state)
	if not _can_edit_target(state):
		frappe.throw(_("Branch assignments can be changed only for branch users."), frappe.PermissionError)

	requested_branches = _normalize_branch_values(branches)
	existing_permissions = _current_branch_permissions(state["user"])
	_validate_requested_branches(requested_branches, {row.for_value for row in existing_permissions})

	existing_by_branch = {}
	duplicate_permission_names = []
	for row in existing_permissions:
		if row.for_value in existing_by_branch:
			duplicate_permission_names.append(row.name)
		else:
			existing_by_branch[row.for_value] = row.name

	requested_set = set(requested_branches)
	to_create = [branch for branch in requested_branches if branch not in existing_by_branch]
	to_delete = [
		row.name
		for row in existing_permissions
		if row.for_value not in requested_set
	] + duplicate_permission_names
	to_delete = _unique_values(to_delete)
	unchanged = [branch for branch in requested_branches if branch in existing_by_branch]

	for branch in to_create:
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": state["user"],
				"allow": PORTAL_BRANCH_DOCTYPE,
				"for_value": branch,
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)

	for permission_name in to_delete:
		frappe.delete_doc("User Permission", permission_name, ignore_permissions=True)

	frappe.cache.hdel("user_permissions", state["user"])

	return {
		"user": state["user"],
		"branches": requested_branches,
		"created": len(to_create),
		"deleted": len(to_delete),
		"unchanged": len(unchanged),
	}


def _require_owner_admin_actor():
	if frappe.session.user == "Administrator":
		return "Administrator"

	actor = owner_admin._actor_class()
	if actor in (OWNER_ROLE, ADMIN_ROLE):
		return actor

	frappe.throw(_("Only Owner/Admin can manage branch assignments."), frappe.PermissionError)


def _get_target_state(user):
	if not user or not frappe.db.exists("User", user):
		frappe.throw(_("User does not exist."), frappe.ValidationError)

	roles = owner_admin._roles_for_user(user)
	role_profile = owner_admin._role_profile_for_user(user)
	if not owner_admin._is_kunal_state(roles, role_profile):
		frappe.throw(_("Only Kunal portal users can be managed here."), frappe.PermissionError)

	is_owner = owner_admin._is_owner_state(roles, role_profile)
	is_admin = role_profile == ADMIN_ROLE or ADMIN_ROLE in roles
	is_branch_user = role_profile in BRANCH_ROLES or bool(roles.intersection(BRANCH_ROLES))

	return {
		"user": user,
		"roles": roles,
		"role_profile": role_profile,
		"is_owner": is_owner,
		"is_admin": is_admin,
		"is_branch_user": is_branch_user,
		"is_global_user": is_owner or is_admin,
	}


def _validate_target_read(actor, state):
	if actor == ADMIN_ROLE and state["is_owner"]:
		frappe.throw(_("Admin cannot manage Owner users."), frappe.PermissionError)


def _can_edit_target(state):
	return state["is_branch_user"] and not state["is_global_user"]


def _normalize_branch_values(branches):
	if branches in (None, ""):
		return []

	if isinstance(branches, str):
		try:
			branches = json.loads(branches)
		except ValueError:
			frappe.throw(_("Branches must be a JSON list."), frappe.ValidationError)

	if not isinstance(branches, (list, tuple)):
		frappe.throw(_("Branches must be a list."), frappe.ValidationError)

	normalized = []
	seen = set()
	for branch in branches:
		value = branch
		if isinstance(branch, dict):
			value = branch.get("value") or branch.get("name")
		if not isinstance(value, str) or not value.strip():
			frappe.throw(_("Invalid branch value."), frappe.ValidationError)
		value = value.strip()
		if value not in seen:
			normalized.append(value)
			seen.add(value)
	return normalized


def _unique_values(values):
	unique = []
	seen = set()
	for value in values:
		if value not in seen:
			unique.append(value)
			seen.add(value)
	return unique


def _validate_requested_branches(requested_branches, existing_branches):
	if not requested_branches:
		return

	rows = frappe.get_all(
		PORTAL_BRANCH_DOCTYPE,
		filters={"name": ("in", requested_branches)},
		fields=["name", "is_active"],
	)
	branches_by_name = {row.name: row for row in rows}
	missing = [branch for branch in requested_branches if branch not in branches_by_name]
	if missing:
		frappe.throw(_("Invalid Portal Branch: {0}").format(", ".join(missing)), frappe.ValidationError)

	inactive_new = [
		branch
		for branch in requested_branches
		if branch not in existing_branches and not branches_by_name[branch].is_active
	]
	if inactive_new:
		frappe.throw(_("Inactive Portal Branch cannot be newly assigned."), frappe.ValidationError)


def _current_branch_permissions(user):
	return frappe.get_all(
		"User Permission",
		filters={"user": user, "allow": PORTAL_BRANCH_DOCTYPE},
		fields=["name", "for_value"],
		order_by="for_value asc, name asc",
	)


def _current_branch_values(user):
	values = []
	seen = set()
	for row in _current_branch_permissions(user):
		if row.for_value not in seen:
			values.append(row.for_value)
			seen.add(row.for_value)
	return values


def _branch_details(branches):
	if not branches:
		return []

	rows = frappe.get_all(
		PORTAL_BRANCH_DOCTYPE,
		filters={"name": ("in", branches)},
		fields=["name", "branch_name", "is_active"],
	)
	by_name = {row.name: row for row in rows}
	return [
		{
			"name": branch,
			"branch_name": by_name[branch].branch_name if branch in by_name else branch,
			"is_active": bool(by_name[branch].is_active) if branch in by_name else False,
		}
		for branch in branches
	]


def _branch_options(assigned_branches):
	assigned_set = set(assigned_branches)
	rows_by_name = {
		row.name: row
		for row in frappe.get_all(
			PORTAL_BRANCH_DOCTYPE,
			filters={"is_active": 1},
			fields=["name", "branch_name", "is_active"],
		)
	}

	if assigned_branches:
		rows_by_name.update(
			{
				row.name: row
				for row in frappe.get_all(
					PORTAL_BRANCH_DOCTYPE,
					filters={"name": ("in", assigned_branches)},
					fields=["name", "branch_name", "is_active"],
				)
			}
		)

	rows = sorted(rows_by_name.values(), key=lambda row: (row.branch_name or row.name).lower())
	return [
		{
			"name": row.name,
			"branch_name": row.branch_name or row.name,
			"is_active": bool(row.is_active),
			"assigned": row.name in assigned_set,
		}
		for row in rows
	]
