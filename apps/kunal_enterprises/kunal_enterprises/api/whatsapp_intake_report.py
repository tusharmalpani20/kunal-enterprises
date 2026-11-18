"""Read-only reporting over the received-message cohort and its verified links."""

from datetime import date, datetime, timedelta

import frappe
from frappe.utils import today

from kunal_enterprises.api.whatsapp_inbox import _sender_expression, message_context
from kunal_enterprises.integrations.customer_contacts import phone_sql
from kunal_enterprises.permission_guards.sales_portal import employee_for_user, is_sales_user, scope_condition
from kunal_enterprises.permission_query_conditions.orders import BRANCH_EMPLOYEE_VISIBLE_STATUSES

ROLES = {"Owner", "Admin", "System Manager", "Order Coordinator", "Sales Portal User", "Branch Manager", "Branch Employee"}
BRANCH = {"Branch Manager", "Branch Employee"}
GLOBAL = {"Owner", "Admin", "System Manager"}
TYPES = ("Order", "Stock Inquiry", "Price Inquiry", "Mixed", "Unclear", "Original type unknown")
COVERAGE = {
    "linked": "Linked to intake", "skipped": "Duplicate", "review": "Needs review",
    "failed": "Failed", "waiting": "Waiting to process",
}
REASONS = {
    "linked": "Linked to a visible intake request.", "skipped": "Duplicate message.",
    "review": "Review the intake result or check the message link.",
    "failed": "Preparing, processing or downloading this message needs attention.",
    "waiting": "Intake processing is pending.",
}
DIMENSIONS = {
    "account": ("WhatsApp Account", "account_name", "m.account"),
    "sales_employee": ("Sales Employee", "sales_employee_name", "ms.employee"),
    "godown": ("Tally Godown", "godown_name", "d.godown"),
    "customer": ("Customer", "customer_name", "i.customer"),
    "item": ("Tally Item", "item_name", "d.item"),
}
PAGE_SIZE = 50
UNASSIGNED = "__unassigned__"


def _access():
    user = frappe.session.user
    roles = set(frappe.get_roles(user))
    if user == "Guest" or (user != "Administrator" and not roles.intersection(ROLES)):
        frappe.throw("WhatsApp Intake Report access is not permitted.", frappe.PermissionError)
    if user == "Administrator" or roles.intersection(GLOBAL):
        return "overall", roles
    if is_sales_user():
        if not employee_for_user():
            frappe.throw("An active Sales Employee link is required.", frappe.PermissionError)
        return "sales", roles
    if "Order Coordinator" in roles:
        return "reviewer", roles
    return "godown", roles


def _filters(filters):
    try:
        supplied = frappe.parse_json(filters) if isinstance(filters, str) else filters
        supplied = {} if supplied is None else supplied
        if not isinstance(supplied, dict) or any(not isinstance(value, str) or len(value) > 140 for value in supplied.values()):
            raise ValueError
        end = date.fromisoformat(supplied.get("to_date") or today())
        start = date.fromisoformat(supplied.get("from_date") or end.replace(day=1).isoformat())
        if not 0 <= (end - start).days <= 365:
            raise ValueError
        stop = end + timedelta(days=1)
    except (ValueError, TypeError, OverflowError):
        frappe.throw("Choose a valid received date range of up to 366 days.")
    clean = {key: value for key, value in supplied.items()
             if key in {*DIMENSIONS, "metric", "request_type", "group", "message"} and value}
    return clean, {"start": start.isoformat(), "stop": stop.isoformat()}


def _list_query(doctype, fields, *, mandatory_sales=False):
    """Reuse standard read permissions and fence the existing sales share fallback."""
    query = frappe.get_list(doctype, fields=fields, order_by="", limit_page_length=0, run=False)
    if not query:
        return "SELECT " + ", ".join(fields) + f" FROM `tab{doctype}` WHERE 1=0"
    if mandatory_sales:
        # This subquery is compiled before the report's bound parameters are set.
        predicate = scope_condition(doctype).replace(f"`tab{doctype}`.", "permitted.")
        query = f"SELECT permitted.* FROM ({query}) permitted WHERE {predicate}"
    return query.replace("%", "%%")


def _report_source(doctype, fields):
    return "SELECT " + ", ".join(f"`{col}`" for col in fields) + f" FROM `tab{doctype}`"


def _sales_map():
    employee = phone_sql("e.mobile_number")
    customer = phone_sql("c.mobile_number")
    contact = phone_sql("cc.mobile_number")
    sender = phone_sql("m.`from`", international=True)
    return f"""
        employee_numbers AS (
            SELECT e.name employee, {employee} phone FROM `tabSales Employee` e
            UNION
            SELECT a.parent, {customer}
            FROM `tabSales Employee Assigned Customer` a JOIN `tabCustomer` c ON c.name=a.customer
            WHERE a.parenttype='Sales Employee' AND a.parentfield='assigned_customers'
            UNION
            SELECT a.parent, {contact}
            FROM `tabSales Employee Assigned Customer` a JOIN `tabCustomer Contact` cc ON cc.parent=a.customer
            WHERE a.parenttype='Sales Employee' AND a.parentfield='assigned_customers'
              AND cc.parenttype='Customer' AND cc.parentfield='contacts'
        ), message_sales AS (
            SELECT DISTINCT m.name message, n.employee FROM dated_messages m
            JOIN employee_numbers n ON n.phone={sender} WHERE n.phone<>''
        )
    """


def _cohort(filters, params, scope, roles, *, sales_map=False):
    """Build each result from the same deduplicated, permission-scoped cohort."""
    sales = scope == "sales"
    branch = scope == "godown"
    message_fields = ["name", "creation", "intake_received_at", "type", "whatsapp_account", "from",
                      "profile_name", "intake_status", "intake_ai_state", "intake_media_state", "intake_prepare_state"]
    intake_fields = ["name", "source", "whatsapp_account", "sender_number", "customer", "sales_employee",
                     "status", "request_type", "ai_initial_values", "order"]
    order_fields = ["name", "customer", "sales_employee", "order_intake_request", "status"]
    if branch:
        # The report exposes only source evidence for requests with a permitted
        # godown. Branch roles do not otherwise have access to the Inbox.
        message_sql = _report_source("WhatsApp Message", message_fields)
        intake_sql = _report_source("Order Intake Request", intake_fields)
        order_sql = _list_query("Order", order_fields)
        params["viewer"] = frappe.session.user
        allowed = """
            JOIN `tabBranch Godown Mapping` bg ON bg.godown=g.godown AND bg.is_active=1
            JOIN `tabPortal Branch` pb ON pb.name=bg.portal_branch AND pb.is_active=1
            JOIN `tabUser Permission` up ON up.allow='Portal Branch' AND up.for_value=pb.name AND up.user=%(viewer)s
        """
        branch_order = ""
        if "Branch Manager" not in roles:
            params["order_statuses"] = BRANCH_EMPLOYEE_VISIBLE_STATUSES
            branch_order = "AND (i.converted_order IS NULL OR i.order_status IN %(order_statuses)s)"
        account_scope = ""
    else:
        message_sql = _list_query("WhatsApp Message", message_fields, mandatory_sales=sales)
        if scope == "overall" and not frappe.has_permission("Order Intake Request", "read"):
            # The report can count linked intakes for a System Manager with
            # report access but without standalone Intake Request access.
            intake_sql = _report_source("Order Intake Request", intake_fields)
        else:
            intake_sql = _list_query("Order Intake Request", intake_fields, mandatory_sales=sales)
        order_sql = _list_query("Order", order_fields, mandatory_sales=sales)
        account_sql = _list_query("WhatsApp Account", ["name"])
        missing_account = "" if sales else "COALESCE(m.whatsapp_account,'')='' OR "
        account_scope = f"AND ({missing_account}m.whatsapp_account IN (SELECT name FROM ({account_sql}) permitted_accounts))"
        allowed = ""
        branch_order = ""

    message_where = ["m.type='Incoming'"]
    if filters.get("account"):
        params["account"] = filters["account"]
        message_where.append("m.whatsapp_account=%(account)s")
    # Keep the normal non-null receive-time predicate indexable; creation
    # is only a fallback for incoming records created before intake capture.
    message_where.append("""((m.intake_received_at >= %(start)s AND m.intake_received_at < %(stop)s)
        OR (m.intake_received_at IS NULL AND m.creation >= %(start)s AND m.creation < %(stop)s))""")
    need_sales = sales_map or bool(filters.get("sales_employee"))
    if filters.get("sales_employee"):
        params["sales_employee"] = filters["sales_employee"]
        sales_filter = "WHERE EXISTS (SELECT 1 FROM message_sales ms WHERE ms.message=m.name AND ms.employee=%(sales_employee)s)"
    else:
        sales_filter = ""

    selection = []
    for key in ("customer", "item", "godown"):
        if filters.get(key):
            params[key] = "" if key == "godown" and filters[key] == UNASSIGNED else filters[key]
            selection.append({"customer": "i.customer", "item": "d.item", "godown": "COALESCE(d.godown,'')"}[key] + f"=%({key})s")
    unassigned = filters.get("godown") == UNASSIGNED
    if unassigned:
        selection.append("NOT EXISTS (SELECT 1 FROM dimensions g WHERE g.intake=i.name AND COALESCE(g.godown,'')<>'')")
    matches = " AND ".join(selection) or "1=1"
    restrict_messages = "WHERE EXISTS (SELECT 1 FROM matched_links x WHERE x.message=m.name)" if selection or branch else ""
    if unassigned and not branch and not (filters.get("customer") or filters.get("item")):
        restrict_messages += " OR NOT EXISTS (SELECT 1 FROM verified_links v WHERE v.message=m.name)"
    valid_types = ", ".join(frappe.db.escape(key) for key in TYPES[:-1])
    initial_type = """CASE WHEN JSON_VALID(i.ai_initial_values)=1
        THEN JSON_UNQUOTE(JSON_EXTRACT(i.ai_initial_values, '$.request_type')) END"""
    return f"""
        WITH dated_messages AS (
            SELECT m.*, m.whatsapp_account account, COALESCE(m.intake_received_at,m.creation) received_at
            FROM ({message_sql}) m WHERE {' AND '.join(message_where)} {account_scope}
        ),
        {(_sales_map() + ',') if need_sales else ''}
        message_base AS (SELECT m.* FROM dated_messages m {sales_filter}),
        linked_sources AS (
            SELECT DISTINCT m.name message, s.parent intake
            FROM message_base m JOIN `tabOrder Intake Source Message` s ON s.message=m.name
            WHERE s.parenttype='Order Intake Request' AND s.parentfield='source_messages'
        ),
        intake_base AS (
            SELECT i.*, o.name converted_order, o.status order_status,
                   CASE WHEN ({initial_type}) IN ({valid_types}) THEN ({initial_type})
                        ELSE 'Original type unknown' END original_type
            FROM ({intake_sql}) i
            LEFT JOIN ({order_sql}) o ON o.name=i.`order` AND o.order_intake_request=i.name AND o.customer=i.customer
                AND i.status='Converted to Order'
            WHERE i.source='WhatsApp' AND EXISTS (SELECT 1 FROM linked_sources s WHERE s.intake=i.name)
        ),
        verified_links AS (
            SELECT s.message,s.intake FROM linked_sources s
            JOIN message_base m ON m.name=s.message
            JOIN intake_base i ON i.name=s.intake AND i.whatsapp_account=m.account
                AND ({_sender_expression('m')})<>'' AND
                ({_sender_expression('m')})=({_sender_expression('i').replace('i.`from`', 'i.sender_number')})
        ),
        locations AS (
            SELECT i.name intake, g.item, g.godown FROM intake_base i
            JOIN `tabOrder Godown Allocation` g ON g.parent=i.converted_order
                AND g.parenttype='Order' AND g.parentfield='godown_allocations'
            UNION
            SELECT i.name, t.item, t.godown FROM intake_base i
            JOIN `tabOrder Intake Item` t ON t.parent=i.name
                AND t.parenttype='Order Intake Request' AND t.parentfield='items'
            WHERE i.converted_order IS NULL AND i.status<>'Converted to Order'
            UNION
            SELECT i.name, t.item, '' FROM intake_base i
            JOIN `tabOrder Item` t ON t.parent=i.converted_order AND t.parenttype='Order' AND t.parentfield='items'
            WHERE NOT EXISTS (SELECT 1 FROM `tabOrder Godown Allocation` g WHERE g.parent=i.converted_order
                AND g.parenttype='Order' AND g.parentfield='godown_allocations' AND g.item=t.item AND COALESCE(g.godown,'')<>'')
        ),
        dimensions AS (
            SELECT DISTINCT g.intake,g.item,g.godown FROM locations g JOIN intake_base i ON i.name=g.intake
            {allowed} WHERE 1=1 {branch_order}
        ),
        matched_links AS (
            SELECT DISTINCT v.message,v.intake FROM verified_links v JOIN intake_base i ON i.name=v.intake
            LEFT JOIN dimensions d ON d.intake=i.name
            WHERE {matches} {'AND d.intake IS NOT NULL' if branch else ''}
        ),
        intakes AS (
            SELECT i.* FROM intake_base i WHERE EXISTS (SELECT 1 FROM matched_links x WHERE x.intake=i.name)
        ),
        messages AS (
            SELECT m.*,
                CASE WHEN m.intake_status='Duplicate' THEN 'skipped'
                     WHEN m.intake_media_state='Failed' OR m.intake_prepare_state='Needs Attention'
                          OR m.intake_ai_state='Needs Attention' THEN 'failed'
                     WHEN m.intake_ai_state='Unresolved' OR m.intake_status='Needs Attention' THEN 'review'
                     WHEN EXISTS (SELECT 1 FROM matched_links x WHERE x.message=m.name) THEN 'linked'
                     WHEN m.intake_ai_state='Drafted' THEN 'review'
                     ELSE 'waiting' END coverage,
                CASE WHEN m.intake_ai_state IN ('Drafted','Unresolved')
                     OR EXISTS (SELECT 1 FROM matched_links x WHERE x.message=m.name) THEN 1 ELSE 0 END processed
            FROM message_base m {restrict_messages}
        )
    """


def _page(cte, sql, params, cursor, keys, *, newest_first=False):
    """Continue after the last sort key even when new records reach the first page."""
    params = {**params, "limit": PAGE_SIZE + 1}
    columns = [f"`{key}`" for key in keys]
    predicate = ""
    if cursor not in (None, ""):
        try:
            if not isinstance(cursor, str) or len(cursor) > 2048:
                raise ValueError
            values = frappe.parse_json(cursor)
            if not isinstance(values, list) or len(values) != len(keys) or not all(isinstance(value, str) for value in values):
                raise ValueError
            if keys[0] == "received_at" and datetime.fromisoformat(values[0]).tzinfo is not None:
                raise ValueError
        except (TypeError, ValueError):
            frappe.throw("Invalid report page.")
        after = [f"after_{key}" for key in keys]
        params.update(zip(after, values))
        placeholders = [f"%({name})s" for name in after]
        operator = "<" if newest_first else ">"
        predicate = f"WHERE ({', '.join(columns)}) {operator} ({', '.join(placeholders)})"
    direction = "DESC" if newest_first else "ASC"
    ordering = ", ".join(f"{column} {direction}" for column in columns)
    rows = frappe.db.sql(cte + f"SELECT * FROM ({sql}) report_page {predicate} ORDER BY {ordering} LIMIT %(limit)s",
                         params, as_dict=True)
    token = frappe.as_json([str(rows[PAGE_SIZE - 1][key]) for key in keys]) if len(rows) > PAGE_SIZE else None
    return {"rows": rows[:PAGE_SIZE], "next_cursor": token}


def _summary(cte, params, scope):
    counts = frappe.db.sql(cte + """
        SELECT coverage, COUNT(*) total, SUM(processed) processed FROM messages GROUP BY coverage
    """, params, as_dict=True)
    types = frappe.db.sql(cte + """
        SELECT original_type, COUNT(*) intakes, COUNT(DISTINCT converted_order) orders
        FROM intakes GROUP BY original_type
    """, params, as_dict=True)
    grouped = {row.coverage: row.total for row in counts}
    by_type = {row.original_type: row for row in types}
    return {
        "scope": scope,
        "totals": {
            "received": sum(grouped.values()), "processed": sum(int(row.processed) for row in counts),
            "unaccounted": sum(grouped.get(k, 0) for k in ("review", "failed", "waiting")),
            "intakes": sum(row.intakes for row in types), "orders": sum(row.orders for row in types),
        },
        "coverage": [{"key": k, "label": label, "count": grouped.get(k, 0)} for k, label in COVERAGE.items()],
        "types": [{"key": k, "label": k, "intakes": by_type.get(k, {}).get("intakes", 0),
                   "orders": by_type.get(k, {}).get("orders", 0)} for k in TYPES if k in by_type],
    }


def _options(cte, params, field, search, cursor):
    doctype, label, value = DIMENSIONS[field]
    sources = {
        "account": "messages m",
        "sales_employee": "messages m JOIN message_sales ms ON ms.message=m.name",
        "godown": "intakes i JOIN dimensions d ON d.intake=i.name",
        "customer": "intakes i",
        "item": "intakes i JOIN dimensions d ON d.intake=i.name",
    }
    row_filter = ""
    if field == "godown" and "item" in params:
        row_filter = "AND d.item=%(item)s"
    if field == "item" and "godown" in params:
        row_filter = "AND COALESCE(d.godown,'')=%(godown)s"
    params["search"] = "%" + search.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
    return _page(cte, f"""
        SELECT DISTINCT {value} value, COALESCE(NULLIF(t.{label},''), {value}) label
        FROM {sources[field]} LEFT JOIN `tab{doctype}` t ON t.name={value}
        WHERE COALESCE({value},'')<>'' {row_filter} AND
            ({value} LIKE %(search)s ESCAPE '!' OR t.{label} LIKE %(search)s ESCAPE '!')
    """, params, cursor, ("label", "value"))


def _breakdown(cte, params, field, cursor):
    if field == "sales_employee":
        membership = "SELECT ms.message,ms.employee member FROM message_sales ms"
        if "sales_employee" in params:
            membership += " WHERE ms.employee=%(sales_employee)s"
    else:
        membership = """SELECT DISTINCT x.message,d.godown member FROM matched_links x
            JOIN dimensions d ON d.intake=x.intake WHERE COALESCE(d.godown,'')<>''"""
        if "godown" in params:
            membership += " AND d.godown=%(godown)s"
    doctype, label, _ = DIMENSIONS[field]
    # Count using the same per-member intake associations as the drill-down.
    item_filter = " AND d.item=%(item)s" if "item" in params else ""
    if field == "godown" and item_filter:
        membership += item_filter
    member_intake = ("AND EXISTS (SELECT 1 FROM dimensions d WHERE d.intake=i.name AND d.godown=b.member"
                     + item_filter + ")") if field == "godown" else ""
    return _page(cte + f", membership AS ({membership})", f"""
        SELECT b.member name, COALESCE(NULLIF(t.{label},''),b.member) label,
            COUNT(DISTINCT m.name) received, COUNT(DISTINCT i.name) intakes,
            COUNT(DISTINCT i.converted_order) orders,
            COUNT(DISTINCT CASE WHEN m.coverage IN ('review','failed','waiting') THEN m.name END) unaccounted
        FROM membership b JOIN messages m ON m.name=b.message
        LEFT JOIN matched_links x ON x.message=m.name
        LEFT JOIN intakes i ON i.name=x.intake {member_intake}
        LEFT JOIN `tab{doctype}` t ON t.name=b.member
        GROUP BY b.member,t.{label}
    """, params, cursor, ("label", "name"))


def _reason(row):
    if row.coverage == "failed":
        if row.intake_media_state == "Failed":
            return "Attachment download failed."
        if row.intake_prepare_state == "Needs Attention":
            return "Message preparation needs attention."
        return "Intake processing needs attention."
    if row.coverage == "review" and row.intake_ai_state == "Drafted":
        return "Check the linked intake or missing message link."
    if row.coverage == "review" and row.intake_ai_state == "Unresolved":
        return "Processing finished with questions to review."
    return REASONS[row.coverage]


def _message_detail(cte, params, filters, scope, roles):
    params["message"] = filters.get("message")
    rows = frappe.db.sql(cte + """
        SELECT name, account, `from` sender, profile_name, received_at, coverage,
               intake_media_state,intake_prepare_state,intake_ai_state
        FROM messages WHERE name=%(message)s
    """, params, as_dict=True)
    if not rows:
        frappe.throw("This message is outside the report view.", frappe.PermissionError)
    row = rows[0]
    if scope == "godown":
        # A single source can contain orders or lines for multiple godowns.
        # Only show original text if every linked intake and line is in scope.
        from kunal_enterprises.api.whatsapp_inbox import _display_text
        outside_scope = frappe.db.sql(cte + """
            SELECT 1 FROM verified_links v WHERE v.message=%(message)s AND (
                NOT EXISTS (SELECT 1 FROM dimensions d WHERE d.intake=v.intake)
                OR EXISTS (SELECT 1 FROM locations l WHERE l.intake=v.intake AND NOT EXISTS (
                    SELECT 1 FROM dimensions d WHERE d.intake=l.intake
                        AND d.item <=> l.item AND d.godown <=> l.godown
                ))
            ) LIMIT 1
        """, params)
        source = frappe.get_doc("WhatsApp Message", row.name)
        kind = source.get("intake_original_type") or source.content_type
        target = {
            "name": row.name, "sender_name": row.profile_name or "",
            "received_at": str(row.received_at), "content_type": kind,
            "text": ("Message preview is restricted for this godown." if outside_scope else
                     _display_text(source) if kind == "text" else "Attachment preview is restricted for this godown."),
        }
        result = {"target": target, "messages": [target], "context_only": True}
    elif row.account and row.sender:
        result = message_context(row.account, row.sender, row.name)
        result["sender"] = row.sender
    else:
        from types import SimpleNamespace
        from kunal_enterprises.api.order_intake_conversation import _message
        source = frappe.get_doc("WhatsApp Message", row.name)
        source.check_permission("read")
        target = _message(source, SimpleNamespace(name=None), {row.name}, {})
        result = {"target": target, "messages": [target], "context_only": True}
    can_retry = False
    if row.intake_media_state == "Failed" and not is_sales_user() and (
        frappe.session.user == "Administrator" or roles.intersection({"Owner", "Admin", "Order Coordinator"})
    ):
        source = frappe.get_doc("WhatsApp Message", row.name)
        can_retry = bool(source.get("intake_media_id") and source.has_permission("read") and source.has_permission("write"))
    result.update(account=row.account, status=COVERAGE[row.coverage], reason=_reason(row), can_retry_attachment=can_retry)
    return result


@frappe.whitelist(methods=["GET"])
def read(filters=None, view="summary", cursor=None, search=None, field=None):
    """Return a summary, bounded drill-down or permitted conversation context."""
    scope, roles = _access()
    clean, params = _filters(filters)
    if view not in ("summary", "messages", "intakes", "message", "options", "breakdown"):
        frappe.throw("Invalid report view.")
    if view == "options":
        if not isinstance(field, str) or field not in DIMENSIONS:
            frappe.throw("Invalid report filter.")
        clean.pop(field, None)
    group = clean.get("group")
    if view == "breakdown" and group not in ("sales_employee", "godown"):
        frappe.throw("Invalid report grouping.")
    if scope in {"sales", "godown"}:
        # Sales logins have a fixed phone scope. Godown roles can see scoped
        # intake evidence, but cannot resolve global sales assignments.
        clean.pop("sales_employee", None)
        if view == "options" and field == "sales_employee":
            if scope == "godown":
                return {"rows": [], "next_cursor": None}
            employee = employee_for_user()
            matches = str(search or "").casefold() in f"{employee.name} {employee.sales_employee_name}".casefold()
            rows = [{"value": employee.name, "label": employee.sales_employee_name}] if matches and not cursor else []
            return {"rows": rows, "next_cursor": None}
        if view == "breakdown" and group == "sales_employee":
            return {"rows": [], "next_cursor": None}
    cte = _cohort(clean, params, scope, roles, sales_map=field == "sales_employee" or group == "sales_employee")
    if view == "summary":
        return _summary(cte, params, scope)
    if view == "options":
        result = _options(cte, params, field, str(search or "")[:100], cursor)
        if field == "godown" and scope != "godown" and not cursor and (
            not search or str(search).lower() in "unassigned godown"
        ):
            result["rows"].insert(0, frappe._dict(value=UNASSIGNED, label="Unassigned godown"))
        return result
    if view == "breakdown":
        return _breakdown(cte, params, group, cursor)
    if view == "message":
        return _message_detail(cte, params, clean, scope, roles)
    if view == "intakes":
        conditions = ["1=1"]
        if clean.get("metric") == "orders":
            conditions.append("i.converted_order IS NOT NULL")
        if clean.get("request_type"):
            params["request_type"] = clean["request_type"]
            conditions.append("i.original_type=%(request_type)s")
        can_open_intake = scope != "godown" and frappe.has_permission("Order Intake Request", "read")
        return _page(cte, f"""
            SELECT i.name,i.request_type,i.original_type,i.customer,c.customer_name,i.converted_order AS `order`,
                   {int(can_open_intake)} can_open_intake,
                   CASE WHEN i.converted_order IS NOT NULL THEN 1 ELSE 0 END can_open_order
            FROM intakes i LEFT JOIN `tabCustomer` c ON c.name=i.customer
            WHERE {' AND '.join(conditions)}
        """, params, cursor, ("name",), newest_first=True)
    metric = clean.get("metric", "received")
    if metric not in ("received", "processed", "unaccounted", *COVERAGE):
        frappe.throw("Invalid message total.")
    params["metric"] = metric
    condition = {"received": "1=1", "processed": "processed=1",
                 "unaccounted": "coverage IN ('review','failed','waiting')"}.get(metric, "coverage=%(metric)s")
    sender_name = "profile_name" if scope == "godown" else "COALESCE(NULLIF(profile_name,''),`from`)"
    result = _page(cte, f"""
        SELECT name,received_at,{sender_name} sender_name,account,coverage,
               intake_media_state,intake_prepare_state,intake_ai_state
        FROM messages WHERE {condition}
    """, params, cursor, ("received_at", "name"), newest_first=True)
    for row in result["rows"]:
        row.update(status=COVERAGE[row.coverage], reason=_reason(row))
    return result
