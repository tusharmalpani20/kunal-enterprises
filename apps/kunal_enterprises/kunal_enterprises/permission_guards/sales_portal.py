"""Bounded Desk access for linked sales users; mobile-token rules stay separate.

Keep list queries and direct-document checks on the same predicates. In
particular, an empty assignment table never means all customers in Desk.
"""
import frappe

ROLE = 'Sales Portal User'
PRIVILEGED = {'Owner', 'Admin', 'System Manager'}
BUSINESS_TYPES = ('Order', 'Order Intake Request', 'Quick Order Request')
READ_TYPES = (*BUSINESS_TYPES, 'Customer', 'Sales Employee', 'Tally Item', 'Tally Godown',
              'WhatsApp Message', 'WhatsApp Account', 'Order PDF', 'File')


def is_sales_user(user=None):
    user = user or frappe.session.user
    if user in ('Administrator', 'Guest'):
        return False
    roles = set(frappe.get_roles(user))
    return ROLE in roles and not roles.intersection(PRIVILEGED)


def employee_for_user(user=None):
    user = user or frappe.session.user
    if not is_sales_user(user):
        return None
    login = frappe.db.get_value('User', user, ['enabled', 'user_type'], as_dict=True)
    if not login or not login.enabled or login.user_type != 'System User':
        return None
    # Never pick one identity from corrupt legacy duplicate links.
    names = frappe.get_all('Sales Employee', filters={'portal_user': user, 'status': 'Active'},
                           pluck='name', limit_page_length=2)
    if len(names) != 1:
        return None
    return frappe.get_doc('Sales Employee', names[0])


def assigned_customers(employee):
    return tuple(sorted({row.customer for row in employee.get('assigned_customers') or [] if row.customer})) if employee else ()


def _table(doctype):
    quote = '"' if frappe.db.db_type == 'postgres' else '`'
    return quote + 'tab' + doctype + quote


def _column(name):
    quote = '"' if frappe.db.db_type == 'postgres' else '`'
    return quote + name + quote


def _in(value, names):
    return value + ' IN (' + ','.join(frappe.db.escape(name) for name in names) + ')' if names else '1=0'


def _business_condition(doctype, employee, alias=None):
    table = alias or _table(doctype)
    return '(' + table + '.sales_employee=' + frappe.db.escape(employee.name) + ' OR ' + _in(table + '.customer', assigned_customers(employee)) + ')'


def _message_condition(employee, alias=None):
    from kunal_enterprises.integrations.customer_contacts import normalize_phone, phone_sql
    table = alias or _table('WhatsApp Message')
    sender = phone_sql(table + '.' + _column('from'), international=True)
    own = normalize_phone(employee.mobile_number, strict=False)
    # Compare current master numbers, not cached intake_customer metadata:
    # assignments and contact ownership may have changed since capture.
    customers = _in('c.name', assigned_customers(employee))
    phone = phone_sql('c.mobile_number')
    contact = phone_sql('cc.mobile_number')
    exists = (f'EXISTS (SELECT 1 FROM {_table("Customer")} c WHERE {customers} AND '
              f'({phone}={sender} OR EXISTS (SELECT 1 FROM {_table("Customer Contact")} cc '
              f"WHERE cc.parent=c.name AND cc.parenttype='Customer' AND cc.parentfield='contacts' AND {contact}={sender})))")
    matching_number = f"({sender}={frappe.db.escape(own)} OR {exists})" if own else exists
    return f"({table}.type='Incoming' AND {sender}<>'' AND {matching_number})"


def _account_condition(employee, alias=None):
    table = alias or _table('WhatsApp Account')
    return f'EXISTS (SELECT 1 FROM {_table("WhatsApp Message")} sm WHERE sm.whatsapp_account={table}.name AND {_message_condition(employee,"sm")})'


def _pdf_condition(employee, alias=None):
    table = alias or _table('Order PDF')
    return f'EXISTS (SELECT 1 FROM {_table("Order")} so WHERE so.name={table}.{_column("order")} AND {_business_condition("Order", employee, "so")})'


def _file_condition(employee):
    table = _table('File')
    conditions = []
    for doctype in (*BUSINESS_TYPES, 'WhatsApp Message', 'Order PDF'):
        predicate = (_business_condition(doctype, employee, 'sd') if doctype in BUSINESS_TYPES else
                     '('+_message_condition(employee, 'sd')+' OR '+evidence_message_condition(employee, 'sd')+')' if doctype == 'WhatsApp Message' else _pdf_condition(employee, 'sd'))
        conditions.append(f'({table}.attached_to_doctype={frappe.db.escape(doctype)} AND EXISTS '
                          f'(SELECT 1 FROM {_table(doctype)} sd WHERE sd.name={table}.attached_to_name AND {predicate}))')
    return '(' + ' OR '.join(conditions) + ')'


def _condition(doctype, employee):
    if not employee:
        return '1=0'
    if doctype in BUSINESS_TYPES:
        return _business_condition(doctype, employee)
    if doctype == 'Customer':
        return _in(_table(doctype) + '.name', assigned_customers(employee))
    if doctype == 'Sales Employee':
        return _table(doctype) + '.name=' + frappe.db.escape(employee.name)
    if doctype == 'WhatsApp Message':
        return _message_condition(employee)
    if doctype == 'WhatsApp Account':
        return _account_condition(employee)
    if doctype == 'Order PDF':
        return _pdf_condition(employee)
    if doctype == 'File':
        return _file_condition(employee)
    # Catalogues are shared lookup data needed for the allowed intake editors.
    return ''


def _query(doctype, user=None):
    if is_sales_user(user):
        return _condition(doctype, employee_for_user(user))
    return None


def orders_query(user=None):
    if is_sales_user(user):
        return _query('Order', user)
    from kunal_enterprises.permission_query_conditions.orders import get_permission_query_conditions
    return get_permission_query_conditions(user)


def intake_query(user=None): return _query('Order Intake Request', user)
def quick_orders_query(user=None): return _query('Quick Order Request', user)
def customer_query(user=None): return _query('Customer', user)
def employee_query(user=None): return _query('Sales Employee', user)
def messages_query(user=None): return _query('WhatsApp Message', user)
def accounts_query(user=None): return _query('WhatsApp Account', user)
def pdf_query(user=None): return _query('Order PDF', user)
def files_query(user=None): return _query('File', user)
def items_query(user=None): return _query('Tally Item', user)
def godowns_query(user=None): return _query('Tally Godown', user)


def can_access(doc, user=None):
    """Scope only; this does not grant DocPerm or authorize any write."""
    if not is_sales_user(user):
        return True
    employee = employee_for_user(user)
    if not employee or doc.doctype not in READ_TYPES:
        return False
    if doc.doctype in BUSINESS_TYPES:
        return doc.get('sales_employee') == employee.name or doc.get('customer') in assigned_customers(employee)
    if doc.doctype == 'Customer':
        return doc.name in assigned_customers(employee)
    if doc.doctype == 'Sales Employee':
        return doc.name == employee.name
    if doc.doctype in ('Tally Item', 'Tally Godown'):
        return True
    # Evaluate the identical list predicate for message/account/file/PDF reads.
    predicate = _condition(doc.doctype, employee)
    return bool(doc.name and frappe.db.sql(f'SELECT name FROM {_table(doc.doctype)} WHERE name=%s AND ({predicate})', (doc.name,)))


def has_permission(doc, user=None, permission_type=None, ptype=None, **kwargs):
    if not is_sales_user(user):
        return None
    operation = ptype or permission_type or 'read'
    if operation == 'write' and doc.doctype == 'Order Intake Request' and frappe.flags.sales_portal_write and can_access(doc, user):
        return True
    if operation not in ('read', 'select') and not (operation == 'print' and doc.doctype in ('Order', 'Order PDF')):
        frappe.throw('Sales portal access is read-only outside the intake review actions.', frappe.PermissionError)
    if not can_access(doc, user):
        # A False hook result can be reopened by Frappe DocShare fallback.
        frappe.throw('This record is outside your sales portal scope.', frappe.PermissionError)
    return True


def order_permission(doc, user=None, permission_type=None, ptype=None, **kwargs):
    if is_sales_user(user):
        return has_permission(doc, user, permission_type, ptype)
    from kunal_enterprises.permission_query_conditions.orders import has_permission as existing
    return existing(doc, user=user, permission_type=ptype or permission_type)


def deny_generic_mutations(doc, user=None, permission_type=None, ptype=None, **kwargs):
    if not is_sales_user(user):
        return None
    operation = ptype or permission_type or 'read'
    if doc.doctype == 'Order Intake Request' and frappe.flags.sales_portal_write:
        return None
    # Narrow intake edits/approvals go through the dedicated audited endpoint,
    # never generic document saves even if another business role is added.
    if doc.doctype not in READ_TYPES and frappe.get_meta(doc.doctype).module == 'Kunal Enterprises':
        frappe.throw('This area is not available to sales portal users.', frappe.PermissionError)
    if operation not in ('read', 'select') and not (operation == 'print' and doc.doctype in ('Order', 'Order PDF')):
        frappe.throw('Sales portal access is read-only outside the intake review actions.', frappe.PermissionError)
    return None


def setup():
    """Reapply explicit read-only grants on install/migrate, including upstream types."""
    if not frappe.db.exists('Role', ROLE):
        return
    from frappe.permissions import setup_custom_perms
    from kunal_enterprises.permission_guards.whatsapp import _set_permission
    for doctype in READ_TYPES:
        if not frappe.db.exists('DocType', doctype):
            continue
        setup_custom_perms(doctype)
        grants = {'select'} if doctype in ('Tally Item', 'Tally Godown') else {'read', 'select'}
        if doctype in ('Order', 'Order PDF'):
            grants.add('print')
        _set_permission(doctype, ROLE, 0, grants)
        frappe.clear_cache(doctype=doctype)


def scope_condition(doctype, user=None, alias=None):
    """Mandatory SQL scope for APIs that wrap a Frappe-generated list query."""
    if not is_sales_user(user):
        return ''
    employee = employee_for_user(user)
    if not employee:
        return '1=0'
    if alias and doctype == 'WhatsApp Message':
        return _message_condition(employee, alias)
    if alias and doctype in BUSINESS_TYPES:
        return _business_condition(doctype, employee, alias)
    if doctype not in READ_TYPES and frappe.get_meta(doctype).module == 'Kunal Enterprises':
        return '1=0'
    return _condition(doctype, employee)



SEARCH_METHODS = frozenset({'frappe.desk.search.search_link', 'frappe.desk.search.search_widget'})
SALES_SEARCH_QUERIES = {
    'Customer': {'kunal_enterprises.api.sales_portal_intake.customer_query'},
    'Tally Item': {'kunal_enterprises.api.sales_portal_intake.master_query'},
    'Tally Godown': {'kunal_enterprises.api.sales_portal_intake.master_query'},
    # The framework User query uses get_list and keeps its existing User scope.
    'User': {'frappe.core.doctype.user.user.user_query'},
}


def _guard_link_lookup(method, form):
    doctype = form.get('doctype')
    if method in SEARCH_METHODS:
        # In this Frappe version this client-controlled flag sets the entire
        # DatabaseQuery to ignore_permissions, bypassing our row scope too.
        form.ignore_user_permissions = 0
        query = form.get('query')
        if not query:
            defaults = frappe.get_hooks('standard_queries') or {}
            configured = defaults.get(doctype) or []
            query = configured[-1] if isinstance(configured, (list, tuple)) and configured else configured
        if query and (not isinstance(query, str) or query not in SALES_SEARCH_QUERIES.get(doctype, set())):
            frappe.throw('This custom lookup is not available to sales portal users.', frappe.PermissionError)
    if method in {'frappe.desk.search.get_link_title', 'frappe.client.validate_link'} and doctype:
        if doctype in READ_TYPES or frappe.get_meta(doctype).module == 'Kunal Enterprises':
            # Both upstream helpers can reveal names/titles before a scoped
            # query. Select permission also supports our select-only catalogues.
            frappe.get_doc(doctype, form.get('docname')).check_permission('select')

def guard_list_shares():
    """Do not let Frappe's legacy DocShare OR reopen a forbidden list record.

    Standard permission hooks narrow ordinary lists. If unrelated User
    Permissions cause Frappe to add shared rows after that narrowing, this
    explicit filter remains outside that OR. Preserve existing share records.
    """
    if not is_sales_user():
        return
    from kunal_enterprises.permission_guards.exports import _request_target, _canonical_method, LIST_METHODS
    method, arguments = _request_target(frappe.request, frappe.form_dict)
    method = _canonical_method(method)
    _guard_link_lookup(method, frappe.form_dict)
    methods = LIST_METHODS | {'frappe.api.v1.document_list', 'frappe.api.v2.document_list',
        'frappe.client.get_count', 'frappe.client.get_value', 'frappe.desk.reportview.get_count',
        'frappe.desk.reportview.get_stats', 'frappe.desk.reportview.get_sidebar_stats',
        'frappe.desk.reportview.get_filter_dashboard_data'}
    if method not in methods:
        return
    form = frappe.form_dict
    doctype = arguments.get('doctype') or form.get('doctype') or form.get('dt')
    if not doctype or (doctype not in READ_TYPES and frappe.get_meta(doctype).module != 'Kunal Enterprises'):
        return
    shared = frappe.get_all('DocShare', filters={'share_doctype': doctype, 'read': 1},
        or_filters={'user': frappe.session.user, 'everyone': 1}, pluck='share_name')
    if not shared:
        return
    predicate = scope_condition(doctype)
    if not predicate:
        return
    outside = frappe.db.sql(f'SELECT name FROM {_table(doctype)} WHERE name IN %(names)s AND NOT COALESCE(({predicate}), FALSE)',
                           {'names': tuple(shared)}, pluck=True)
    if not outside:
        return
    raw_filters = form.get('filters') or '[]'
    try:
        filters = frappe.parse_json(raw_filters)
    except (ValueError, TypeError):
        filters = raw_filters
    if isinstance(filters, str):
        filters = [[doctype, 'name', '=', filters]]
    if isinstance(filters, dict):
        filters = [[doctype, key, *(value if isinstance(value, (list, tuple)) else ['=', value])]
                   for key, value in filters.items()]
    if not isinstance(filters, list):
        frappe.throw('Invalid list filters.', frappe.PermissionError)
    filters.append([doctype, 'name', 'not in', outside])
    form.filters = frappe.as_json(filters)


def other_business_query(user=None, doctype=None):
    # A second business role must not widen the dedicated sales portal area.
    if is_sales_user(user) and doctype and doctype not in READ_TYPES and frappe.get_meta(doctype).module == 'Kunal Enterprises':
        return '1=0'
    return None


def deny_side_effect_write(doc, method=None):
    """Frappe collaboration helpers may save with ignore_permissions=True."""
    if not is_sales_user():
        return
    if doc.doctype == 'File' and frappe.flags.sales_portal_preview_write:
        if doc.is_private and doc.attached_to_doctype == 'WhatsApp Message' and doc.attached_to_name:
            source = frappe.get_doc('WhatsApp Message', doc.attached_to_name)
            if _can_read_source_attachment(source):
                return
    if doc.doctype == 'Comment' and frappe.flags.sales_portal_write:
        if doc.reference_doctype == 'Order Intake Request' and doc.comment_type in ('Edit', 'Info'):
            request = frappe.get_doc('Order Intake Request', doc.reference_name)
            if can_access(request):
                return
    frappe.throw('Sales portal users can only change intake selections and sales approval.', frappe.PermissionError)


# These helpers write straight to database fields or delete without a Document
# lifecycle. Document events alone cannot protect their alternate entry points.
SIDE_EFFECT_METHODS = frozenset({
    'frappe.desk.form.utils.add_comment', 'frappe.desk.form.utils.update_comment',
    'frappe.desk.form.utils.update_comment_publicity',
    'frappe.desk.doctype.tag.tag.add_tag', 'frappe.desk.doctype.tag.tag.add_tags',
    'frappe.desk.doctype.tag.tag.remove_tag', 'frappe.desk.doctype.tag.tag.get_tagged_docs',
    'frappe.desk.like.toggle_like', 'frappe.desk.like.remove_like',
    'frappe.desk.form.document_follow.follow_document', 'frappe.desk.form.document_follow.unfollow_document',
})


def guard_side_effect_request():
    if not is_sales_user():
        return
    from kunal_enterprises.permission_guards.exports import _request_target, _canonical_method
    method, _ = _request_target(frappe.request, frappe.form_dict)
    method = _canonical_method(method)
    # Socket.IO authorizes room joins through these HTTP endpoints. A 200
    # containing False still joins a room in this version, so deny with 403.
    if method == 'frappe.realtime.can_subscribe_doctype' or (
        method == 'frappe.realtime.can_subscribe_doc' and frappe.form_dict.get('doctype') == 'WhatsApp Account'):
        frappe.throw('Sales portal updates are restricted to individual permitted records.', frappe.PermissionError)
    if method in SIDE_EFFECT_METHODS:
        frappe.throw('Sales portal users can only change intake selections and sales approval.', frappe.PermissionError)


def evidence_message_condition(employee, alias='sd'):
    """An exact source on a readable intake may be read without opening its chat."""
    from kunal_enterprises.integrations.customer_contacts import phone_sql
    request_sender = phone_sql('sir.sender_number', international=True)
    source_sender = phone_sql(alias + '.' + _column('from'), international=True)
    return (f"({alias}.type='Incoming' AND {source_sender}<>'' AND EXISTS (SELECT 1 FROM {_table('Order Intake Source Message')} sism "
            f"JOIN {_table('Order Intake Request')} sir ON sir.name=sism.parent "
            f"WHERE sism.parenttype='Order Intake Request' AND sism.parentfield='source_messages' "
            f"AND sism.message={alias}.name AND sir.whatsapp_account={alias}.whatsapp_account "
            f"AND {request_sender}={source_sender} AND {_business_condition('Order Intake Request', employee, 'sir')}))")


def can_read_intake_source(source, doc, user=None):
    from kunal_enterprises.kunal_enterprises.doctype.order_intake_request.order_intake_request import _sender_key
    sender = _sender_key(source.get('from'))
    return bool(doc.doctype == 'Order Intake Request' and can_access(doc, user) and source.type == 'Incoming'
        and source.whatsapp_account == doc.whatsapp_account
        and sender and sender == _sender_key(doc.sender_number)
        and source.name in {row.message for row in doc.get('source_messages') or []})


def _can_read_source_attachment(source):
    if can_access(source):
        return True
    employee = employee_for_user()
    if not employee:
        return False
    return bool(frappe.db.sql(f'SELECT sd.name FROM {_table("WhatsApp Message")} sd WHERE sd.name=%s AND '
        + evidence_message_condition(employee), (source.name,)))


@frappe.whitelist()
def get_next(doctype, value, prev, filters=None, sort_order='desc', sort_field='modified'):
    """The framework navigation helper uses unscoped Query Builder in this version."""
    from frappe.desk.form.utils import get_next as existing, _sort_field_fallback
    if not is_sales_user():
        return existing(doctype, value, prev, filters, sort_order, sort_field)
    if doctype not in READ_TYPES or sort_order.lower() not in ('asc', 'desc') or str(prev) not in ('0', '1'):
        frappe.throw('Invalid sales portal navigation.', frappe.PermissionError)
    meta = frappe.get_meta(doctype)
    if sort_field not in ('name', 'modified', 'creation', 'modified_by', 'owner', 'idx', 'docstatus') and not meta.get_field(sort_field):
        frappe.throw('Invalid navigation sort field.')
    if meta.get_field(sort_field) and (meta.get_field(sort_field).permlevel or meta.get_field(sort_field).fieldtype == 'Password'):
        frappe.throw('This navigation sort field is not permitted.', frappe.PermissionError)
    if meta.get_field(sort_field) and meta.get_field(sort_field).fieldtype in ('Table', 'Table MultiSelect', 'HTML', 'Section Break', 'Column Break', 'Tab Break'):
        frappe.throw('Invalid navigation sort field.')
    doc = frappe.get_doc(doctype, value)
    doc.check_permission('read')
    scope_fields = (('sales_employee', 'customer') if doctype in BUSINESS_TYPES else
        {'WhatsApp Message': ('type', 'from', 'whatsapp_account'), 'Order PDF': ('order',),
         'File': ('attached_to_doctype', 'attached_to_name')}.get(doctype, ()))
    base = frappe.get_list(doctype, fields=list(dict.fromkeys(('name', sort_field, *scope_fields))),
        filters=frappe.parse_json(filters) if isinstance(filters, str) else filters,
        order_by='', limit_page_length=0, run=False)
    predicate = scope_condition(doctype).replace(_table(doctype)+'.', 'nav.')
    column = 'nav.' + _column(sort_field)
    fallback = _sort_field_fallback(doctype, sort_field)
    current = doc.get(sort_field)
    if fallback is not None:
        column = f'COALESCE({column}, {frappe.db.escape(fallback)})'
        current = fallback if current is None else current
    backwards = int(prev) == (sort_order.lower() == 'asc')
    comparison, direction = ('<', 'DESC') if backwards else ('>', 'ASC')
    rows = frappe.db.sql(f'SELECT nav.name FROM ({base}) nav WHERE ({predicate}) AND '
        f'({column} {comparison} %s OR ({column}=%s AND nav.name {comparison} %s)) '
        f'ORDER BY {column} {direction}, nav.name {direction} LIMIT 1', (current, current, value))
    return rows[0][0] if rows else None


def guard_business_write(doc, method=None):
    """Legacy role actions often save with ignore_permissions=True.

    Authorization must therefore survive the Document permission bypass, and
    only the dedicated intake endpoint's thread-local flag can open a write.
    Client-supplied doc.flags (transition/conversion/ignore_validate) cannot.
    """
    if not is_sales_user():
        return
    if (doc.doctype == 'Order Intake Request' and frappe.flags.sales_portal_write
            and not doc.is_new() and can_access(doc)):
        return
    frappe.throw('Sales portal users cannot modify Orders or Quick Orders outside intake review actions.',
                 frappe.PermissionError)
