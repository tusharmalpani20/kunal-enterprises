import frappe


OWNER_ROLE = "Owner"
ADMIN_ROLE = "Admin"
BRANCH_MANAGER_ROLE = "Branch Manager"
BRANCH_EMPLOYEE_ROLE = "Branch Employee"
PORTAL_BRANCH_DOCTYPE = "Portal Branch"

KUNAL_ROLES = (OWNER_ROLE, ADMIN_ROLE, BRANCH_MANAGER_ROLE, BRANCH_EMPLOYEE_ROLE)
ADMIN_ASSIGNABLE_ROLES = (ADMIN_ROLE, BRANCH_MANAGER_ROLE, BRANCH_EMPLOYEE_ROLE)
BRANCH_ROLES = (BRANCH_MANAGER_ROLE, BRANCH_EMPLOYEE_ROLE)


def guard_user_write(doc, method=None):
	if _is_unrestricted_context():
		return

	actor = _actor_class()
	if actor not in (OWNER_ROLE, ADMIN_ROLE):
		_deny("Only Owner or Admin can manage Kunal portal users.")

	_validate_user_scope(doc, actor)


def guard_user_delete(doc, method=None):
	if _is_unrestricted_context():
		return

	actor = _actor_class()
	if actor not in (OWNER_ROLE, ADMIN_ROLE):
		_deny("Only Owner or Admin can delete Kunal portal users.")

	if _is_builtin_user(doc.name):
		_deny("Built-in users can be managed only by Administrator.")

	existing_roles = _roles_for_user(doc.name)
	existing_profile = _role_profile_for_user(doc.name)
	if not _is_kunal_state(existing_roles, existing_profile):
		_deny("Only Kunal portal users can be managed here.")
	if actor == ADMIN_ROLE and _is_owner_state(existing_roles, existing_profile):
		_deny("Admin cannot manage Owner users.")


def guard_user_rename(doc, method=None, *args, **kwargs):
	guard_user_delete(doc, method)


def guard_role_write(doc, method=None):
	if _is_unrestricted_context():
		return

	actor = _actor_class()
	role_name = doc.get("role_name") or doc.name
	if actor not in (OWNER_ROLE, ADMIN_ROLE):
		_deny("Only Owner or Admin can manage Kunal roles.")
	if role_name not in KUNAL_ROLES:
		_deny("Only Kunal roles can be managed here.")
	if actor == ADMIN_ROLE and role_name == OWNER_ROLE:
		_deny("Admin cannot manage the Owner role.")


def guard_role_delete(doc, method=None):
	guard_role_write(doc, method)


def guard_role_profile_write(doc, method=None):
	if _is_unrestricted_context():
		return

	actor = _actor_class()
	profile_name = doc.get("role_profile") or doc.name
	proposed_roles = _roles_from_profile_doc(doc)

	if actor not in (OWNER_ROLE, ADMIN_ROLE):
		_deny("Only Owner or Admin can manage Kunal role profiles.")
	if profile_name not in KUNAL_ROLES:
		_deny("Only Kunal role profiles can be managed here.")
	if _has_non_kunal_roles(proposed_roles):
		_deny("Kunal role profiles cannot include System Manager or non-Kunal roles.")
	if actor == ADMIN_ROLE and (profile_name == OWNER_ROLE or OWNER_ROLE in proposed_roles):
		_deny("Admin cannot manage Owner role profile state.")


def guard_role_profile_delete(doc, method=None):
	guard_role_profile_write(doc, method)


def guard_user_permission_write(doc, method=None):
	if _is_unrestricted_context():
		return

	actor = _actor_class()
	if actor not in (OWNER_ROLE, ADMIN_ROLE):
		_deny("Only Owner or Admin can manage branch User Permissions.")

	_validate_user_permission_scope(doc, actor)


def guard_user_permission_delete(doc, method=None):
	guard_user_permission_write(doc, method)


def user_query(user=None):
	user = user or frappe.session.user
	actor = _actor_class(user)
	if _is_unrestricted_user(user):
		return None
	if actor == OWNER_ROLE:
		return _kunal_user_condition(include_owner=True)
	if actor == ADMIN_ROLE:
		return _kunal_user_condition(include_owner=False)
	return "1 = 0"


def user_permission_query(user=None):
	user = user or frappe.session.user
	actor = _actor_class(user)
	if _is_unrestricted_user(user):
		return None
	if actor == OWNER_ROLE:
		return f"{_table('User Permission')}.{_column('allow')} = {frappe.db.escape(PORTAL_BRANCH_DOCTYPE)}"
	if actor == ADMIN_ROLE:
		return f"""
			{_table('User Permission')}.{_column('allow')} = {frappe.db.escape(PORTAL_BRANCH_DOCTYPE)}
			and exists (
				select 1
				from {_table('Has Role')} has_role
				where has_role.parenttype = 'User'
					and has_role.parent = {_table('User Permission')}.{_column('user')}
					and has_role.role in ({_sql_values(BRANCH_ROLES)})
			)
			and not exists (
				select 1
				from {_table('Has Role')} owner_role
				where owner_role.parenttype = 'User'
					and owner_role.parent = {_table('User Permission')}.{_column('user')}
					and owner_role.role = {frappe.db.escape(OWNER_ROLE)}
			)
		"""
	return "1 = 0"


def role_query(user=None):
	user = user or frappe.session.user
	actor = _actor_class(user)
	if _is_unrestricted_user(user):
		return None
	if actor == OWNER_ROLE:
		return f"{_table('Role')}.{_column('name')} in ({_sql_values(KUNAL_ROLES)})"
	if actor == ADMIN_ROLE:
		return f"{_table('Role')}.{_column('name')} in ({_sql_values(ADMIN_ASSIGNABLE_ROLES)})"
	return "1 = 0"


def role_profile_query(user=None):
	user = user or frappe.session.user
	actor = _actor_class(user)
	if _is_unrestricted_user(user):
		return None
	if actor == OWNER_ROLE:
		return f"{_table('Role Profile')}.{_column('name')} in ({_sql_values(KUNAL_ROLES)})"
	if actor == ADMIN_ROLE:
		return f"{_table('Role Profile')}.{_column('name')} in ({_sql_values(ADMIN_ASSIGNABLE_ROLES)})"
	return "1 = 0"


def has_user_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if _is_unrestricted_user(user):
		return True

	actor = _actor_class(user)
	roles = _roles_from_user_doc(doc) or _roles_for_user(doc.name)
	profile = doc.get("role_profile_name") or _role_profile_for_user(doc.name)
	if actor == OWNER_ROLE:
		return _is_kunal_state(roles, profile)
	if actor == ADMIN_ROLE:
		return _is_kunal_state(roles, profile) and not _is_owner_state(roles, profile)
	return False


def has_user_permission_doc(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if _is_unrestricted_user(user):
		return True

	actor = _actor_class(user)
	if actor == OWNER_ROLE:
		return doc.allow == PORTAL_BRANCH_DOCTYPE and _is_kunal_user(doc.user)
	if actor == ADMIN_ROLE:
		return doc.allow == PORTAL_BRANCH_DOCTYPE and _is_branch_user(doc.user) and not _is_owner_user(doc.user)
	return False


def has_role_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if _is_unrestricted_user(user):
		return True

	role_name = doc.get("role_name") or doc.name
	actor = _actor_class(user)
	if actor == OWNER_ROLE:
		return role_name in KUNAL_ROLES
	if actor == ADMIN_ROLE:
		return role_name in ADMIN_ASSIGNABLE_ROLES
	return False


def has_role_profile_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if _is_unrestricted_user(user):
		return True

	profile_name = doc.get("role_profile") or doc.name
	actor = _actor_class(user)
	if actor == OWNER_ROLE:
		return profile_name in KUNAL_ROLES
	if actor == ADMIN_ROLE:
		return profile_name in ADMIN_ASSIGNABLE_ROLES
	return False


def get_all_roles():
	if _is_unrestricted_context():
		from frappe.core.doctype.user.user import get_all_roles as frappe_get_all_roles

		return frappe_get_all_roles()

	actor = _actor_class()
	if actor == OWNER_ROLE:
		return list(KUNAL_ROLES)
	if actor == ADMIN_ROLE:
		return list(ADMIN_ASSIGNABLE_ROLES)
	return []


def get_role_profile(role_profile):
	if _is_unrestricted_context():
		return frappe.get_doc("Role Profile", {"role_profile": role_profile}).roles

	actor = _actor_class()
	if actor == OWNER_ROLE and role_profile in KUNAL_ROLES:
		return frappe.get_doc("Role Profile", {"role_profile": role_profile}).roles
	if actor == ADMIN_ROLE and role_profile in ADMIN_ASSIGNABLE_ROLES:
		return frappe.get_doc("Role Profile", {"role_profile": role_profile}).roles
	_deny("You cannot access this role profile.")


def get_roles(arg=None):
	target_user = arg or frappe.form_dict.get("uid")
	if _is_unrestricted_context():
		return frappe.get_roles(target_user)

	actor = _actor_class()
	if actor == OWNER_ROLE and _is_kunal_user(target_user):
		return _filtered_roles_for_user(target_user, KUNAL_ROLES)
	if actor == ADMIN_ROLE and _is_kunal_user(target_user) and not _is_owner_user(target_user):
		return _filtered_roles_for_user(target_user, ADMIN_ASSIGNABLE_ROLES)
	_deny("You cannot access roles for this user.")


def reset_password(user):
	if not _is_unrestricted_context() and frappe.session.user != "Guest":
		actor = _actor_class()
		if actor == OWNER_ROLE:
			if not _is_kunal_user(user):
				_deny("Owner can reset passwords only for Kunal portal users.")
		elif actor == ADMIN_ROLE:
			if not _is_kunal_user(user) or _is_owner_user(user):
				_deny("Admin can reset passwords only for non-Owner Kunal portal users.")
		elif user != frappe.session.user:
			_deny("You cannot reset another user's password.")

	from frappe.core.doctype.user.user import reset_password as frappe_reset_password

	return frappe_reset_password(user)


def _validate_user_scope(doc, actor):
	if _is_builtin_user(doc.name):
		_deny("Built-in users can be managed only by Administrator.")

	existing_roles = _roles_for_user(doc.name)
	existing_profile = _role_profile_for_user(doc.name)
	proposed_roles = _roles_from_user_doc(doc)
	proposed_profile = doc.get("role_profile_name")

	existing_is_kunal = _is_kunal_state(existing_roles, existing_profile)
	proposed_is_kunal = _is_kunal_state(proposed_roles, proposed_profile)

	if not existing_is_kunal and not proposed_is_kunal:
		_deny("Only Kunal portal users can be managed here.")
	if _has_non_kunal_roles(proposed_roles):
		_deny("Kunal portal users cannot receive System Manager or non-Kunal roles.")

	if actor == OWNER_ROLE:
		if proposed_profile and proposed_profile not in KUNAL_ROLES:
			_deny("Owner can assign only Kunal role profiles here.")
		return

	if _is_owner_state(existing_roles, existing_profile) or _is_owner_state(proposed_roles, proposed_profile):
		_deny("Admin cannot manage Owner users.")
	if proposed_profile and proposed_profile not in ADMIN_ASSIGNABLE_ROLES:
		_deny("Admin can assign only non-Owner Kunal role profiles.")
	if any(role not in ADMIN_ASSIGNABLE_ROLES for role in proposed_roles):
		_deny("Admin can assign only non-Owner Kunal roles.")


def _validate_user_permission_scope(doc, actor):
	if doc.allow != PORTAL_BRANCH_DOCTYPE:
		_deny("Only Portal Branch User Permissions can be managed here.")
	if not doc.user:
		_deny("User Permission requires a user.")
	if not frappe.db.exists(PORTAL_BRANCH_DOCTYPE, doc.for_value):
		_deny("Portal Branch User Permission requires an existing Portal Branch.")

	if actor == OWNER_ROLE:
		if not _is_kunal_user(doc.user):
			_deny("Owner can manage User Permissions only for Kunal portal users.")
		return

	if not _is_branch_user(doc.user) or _is_owner_user(doc.user):
		_deny("Admin can manage Portal Branch User Permissions only for branch users.")


def _actor_class(user=None):
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if OWNER_ROLE in roles:
		return OWNER_ROLE
	if ADMIN_ROLE in roles:
		return ADMIN_ROLE
	if BRANCH_MANAGER_ROLE in roles:
		return BRANCH_MANAGER_ROLE
	if BRANCH_EMPLOYEE_ROLE in roles:
		return BRANCH_EMPLOYEE_ROLE
	return None


def _is_unrestricted_context():
	user = getattr(frappe.session, "user", None)
	return _is_unrestricted_user(user) or any(
		getattr(frappe.flags, flag, False)
		for flag in ("in_install", "in_migrate", "in_patch")
	)


def _is_unrestricted_user(user):
	return user in (None, "", "Administrator")


def _is_builtin_user(user):
	return user in ("Administrator", "Guest")


def _roles_from_user_doc(doc):
	return {
		row.role
		for row in doc.get("roles", [])
		if getattr(row, "role", None)
	}


def _roles_from_profile_doc(doc):
	return {
		row.role
		for row in doc.get("roles", [])
		if getattr(row, "role", None)
	}


def _roles_for_user(user):
	if not user or not frappe.db.exists("User", user):
		return set()
	return {
		row.role
		for row in frappe.get_all(
			"Has Role",
			filters={"parent": user, "parenttype": "User"},
			fields=["role"],
		)
	}


def _role_profile_for_user(user):
	if not user or not frappe.db.exists("User", user):
		return None
	return frappe.db.get_value("User", user, "role_profile_name")


def _is_kunal_user(user):
	return _is_kunal_state(_roles_for_user(user), _role_profile_for_user(user))


def _is_owner_user(user):
	return _is_owner_state(_roles_for_user(user), _role_profile_for_user(user))


def _is_branch_user(user):
	roles = _roles_for_user(user)
	profile = _role_profile_for_user(user)
	return bool(roles.intersection(BRANCH_ROLES) or profile in BRANCH_ROLES)


def _is_owner_state(roles, role_profile):
	return role_profile == OWNER_ROLE or OWNER_ROLE in roles


def _is_kunal_state(roles, role_profile):
	return bool(role_profile in KUNAL_ROLES or set(roles).intersection(KUNAL_ROLES))


def _has_non_kunal_roles(roles):
	return any(role not in KUNAL_ROLES for role in roles)


def _filtered_roles_for_user(user, allowed_roles):
	roles = frappe.get_roles(user)
	return [role for role in roles if role in allowed_roles]


def _kunal_user_condition(include_owner):
	user_table = _table("User")
	roles = KUNAL_ROLES if include_owner else ADMIN_ASSIGNABLE_ROLES
	role_condition = f"""
		exists (
			select 1
			from {_table('Has Role')} has_role
			where has_role.parenttype = 'User'
				and has_role.parent = {user_table}.{_column('name')}
				and has_role.role in ({_sql_values(roles)})
		)
	"""
	profile_condition = f"{user_table}.{_column('role_profile_name')} in ({_sql_values(roles)})"

	condition = f"({role_condition} or {profile_condition})"
	if include_owner:
		return condition
	return f"""
		{condition}
		and coalesce({user_table}.{_column('role_profile_name')}, '') != {frappe.db.escape(OWNER_ROLE)}
		and not exists (
			select 1
			from {_table('Has Role')} owner_role
			where owner_role.parenttype = 'User'
				and owner_role.parent = {user_table}.{_column('name')}
				and owner_role.role = {frappe.db.escape(OWNER_ROLE)}
		)
	"""


def _sql_values(values):
	return ", ".join(frappe.db.escape(value) for value in values)


def _table(doctype):
	quote = '"' if frappe.db.db_type == "postgres" else "`"
	return f"{quote}tab{doctype}{quote}"


def _column(fieldname):
	quote = '"' if frappe.db.db_type == "postgres" else "`"
	return f"{quote}{fieldname}{quote}"


def _deny(message):
	frappe.throw(message, frappe.PermissionError)
