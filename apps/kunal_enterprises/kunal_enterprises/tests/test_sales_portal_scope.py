"""Sales scope is enforced for lists, direct reads, source phones and files."""
from uuid import uuid4
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from kunal_enterprises.permission_guards import sales_portal as scope
from kunal_enterprises.tests import test_foundation as foundation


class TestSalesPortalScope(FrappeTestCase):
    def setUp(self):
        frappe.set_user('Administrator')
        self.user = foundation.TestOrderSubmission._create_role_user(self,
            'sales-scope-' + uuid4().hex + '@example.com', scope.ROLE).name
        self.employee = frappe.get_doc(dict(doctype='Sales Employee', sales_employee_name='Scope QA',
            mobile_number='9' + str(uuid4().int)[:9], portal_user=self.user)).insert()
        self.party = frappe.get_doc(dict(doctype='Customer', customer_name='Assigned ' + uuid4().hex,
            business_legal_name='Scope QA', mobile_number='8' + str(uuid4().int)[:9],
            contacts=[dict(contact_name='Purchasing', mobile_number='7' + str(uuid4().int)[:9])])).insert()
        self.employee.append('assigned_customers', dict(customer=self.party.name))
        self.employee.save()
        self.account = frappe.get_doc(dict(doctype='WhatsApp Account', account_name='Scope ' + uuid4().hex,
            phone_id=uuid4().hex, status='Active')).insert(ignore_permissions=True)

    def tearDown(self):
        frappe.set_user('Administrator')
        frappe.db.rollback()

    def record(self, doctype, **values):
        doc = frappe.get_doc(dict(doctype=doctype, name=values.pop('name', 'scope-' + uuid4().hex), **values))
        doc.db_insert()
        return doc

    def test_own_and_assigned_business_records_only_in_lists_and_direct_reads(self):
        for doctype in scope.BUSINESS_TYPES:
            own = self.record(doctype, sales_employee=self.employee.name)
            assigned = self.record(doctype, customer=self.party.name)
            other = self.record(doctype)
            frappe.set_user(self.user)
            with self.subTest(doctype=doctype):
                names = frappe.get_list(doctype, pluck='name', limit_page_length=0)
                self.assertIn(own.name, names)
                self.assertIn(assigned.name, names)
                self.assertNotIn(other.name, names)
                self.assertTrue(own.has_permission('read'))
                self.assertTrue(assigned.has_permission('read'))
                with self.assertRaises(frappe.PermissionError):
                    other.check_permission('read')
                with self.assertRaises(frappe.PermissionError):
                    own.check_permission('write')
            frappe.set_user('Administrator')

    def test_empty_assignments_disabled_employee_and_unlinked_user_fail_closed(self):
        assigned = self.record('Order', customer=self.party.name)
        own = self.record('Order', sales_employee=self.employee.name)
        self.employee.set('assigned_customers', [])
        self.employee.save()
        frappe.set_user(self.user)
        names = frappe.get_list('Order', pluck='name', limit_page_length=0)
        self.assertIn(own.name, names)
        self.assertNotIn(assigned.name, names)
        frappe.set_user('Administrator')
        self.employee.status = 'Disabled'
        self.employee.save()
        frappe.set_user(self.user)
        self.assertEqual(frappe.get_list('Order', pluck='name', limit_page_length=0), [])
        self.assertIsNone(scope.employee_for_user())
        frappe.set_user('Administrator')
        self.employee.portal_user = None
        self.employee.save()
        frappe.set_user(self.user)
        self.assertIsNone(scope.employee_for_user())

    def test_inbox_uses_own_primary_and_additional_customer_phones(self):
        from kunal_enterprises.integrations.customer_contacts import normalize_phone
        visible = [normalize_phone(self.employee.mobile_number), normalize_phone(self.party.mobile_number),
                   normalize_phone(self.party.contacts[0].mobile_number)]
        messages = [self.record('WhatsApp Message', type='Incoming', whatsapp_account=self.account.name,
                    **{'from': phone}) for phone in visible]
        hidden = self.record('WhatsApp Message', type='Incoming', whatsapp_account=self.account.name,
                             **{'from': '919000000000'})
        outgoing = self.record('WhatsApp Message', type='Outgoing', whatsapp_account=self.account.name,
                               **{'from': visible[0]})
        frappe.set_user(self.user)
        names = frappe.get_list('WhatsApp Message', pluck='name', limit_page_length=0)
        self.assertTrue({doc.name for doc in messages}.issubset(names))
        self.assertNotIn(hidden.name, names)
        self.assertNotIn(outgoing.name, names)
        self.assertTrue(scope.can_access(self.account))
        from kunal_enterprises.api.whatsapp_inbox import conversations, messages as inbox_messages
        chats = conversations(self.account.name)
        self.assertEqual({row['sender'] for row in chats['conversations']}, set(visible))
        history = inbox_messages(self.account.name, visible[0])
        self.assertEqual([row['name'] for row in history['messages']], [messages[0].name])
        with self.assertRaises(frappe.PermissionError):
            hidden.check_permission('read')

    def test_file_scope_does_not_trust_public_or_owner_shortcuts(self):
        own = self.record('Order', sales_employee=self.employee.name)
        other = self.record('Order')
        files = [self.record('File', file_name=doc.name+'.pdf', file_url='/private/files/'+doc.name+'.pdf',
            is_private=1, attached_to_doctype='Order', attached_to_name=doc.name, owner=self.user)
            for doc in (own, other)]
        frappe.set_user(self.user)
        self.assertTrue(files[0].has_permission('read'))
        self.assertTrue(files[0].is_downloadable())
        self.assertFalse(files[1].is_downloadable())
        with patch.object(files[0], 'save_file') as save_file, self.assertRaises(frappe.PermissionError):
            files[0].optimize_file()
        save_file.assert_not_called()
        with self.assertRaises(frappe.PermissionError):
            files[1].check_permission('read')
        names = frappe.get_list('File', pluck='name', limit_page_length=0)
        self.assertIn(files[0].name, names)
        self.assertNotIn(files[1].name, names)

    def test_legacy_share_cannot_restore_direct_read_and_http_list_gets_mandatory_filter(self):
        other = self.record('Order', status='Manual Review')
        self.record('Order', status='Placed', sales_employee=self.employee.name, customer=self.party.name)
        frappe.share.add_docshare('Order', other.name, self.user, read=1, flags={'ignore_share_permission': True})
        frappe.get_doc(dict(doctype='User Permission', user=self.user, allow='Customer', for_value=self.party.name)).insert(ignore_permissions=True)
        frappe.set_user(self.user)
        with self.assertRaises(frappe.PermissionError):
            other.check_permission('read')
        self.assertTrue(scope.is_sales_user())
        self.assertTrue(frappe.get_all('DocShare', filters={'share_doctype':'Order', 'read':1}, or_filters={'user':self.user,'everyone':1}, pluck='share_name'))
        self.assertTrue(frappe.db.sql('SELECT name FROM `tabOrder` WHERE name=%s AND NOT COALESCE(('+scope.scope_condition('Order')+'), FALSE)', (other.name,)))
        from frappe.desk.reportview import get_sidebar_stats
        for method in ('frappe.client.get_list', 'frappe.desk.reportview.get_sidebar_stats',
                       'frappe.desk.reportview.get_filter_dashboard_data'):
            with self.subTest(route=method):
                form = frappe._dict(doctype='Order', filters='[]')
                with patch('kunal_enterprises.permission_guards.exports._request_target',
                           return_value=(method, {})), \
                     patch.object(frappe.local, 'form_dict', form, create=True), \
                     patch.object(frappe.local, 'request', frappe._dict(), create=True):
                    scope.guard_list_shares()
                filters = frappe.parse_json(form.filters)
                self.assertIn(['Order', 'name', 'not in', [other.name]], filters)
                self.assertNotIn(other.name, frappe.get_list('Order', filters=filters, pluck='name'))
                if method.endswith('get_sidebar_stats'):
                    counts = get_sidebar_stats('["status"]', 'Order', filters=form.filters)['stats']['status']
                    self.assertEqual(dict(counts), {'Placed': 1})
                elif method.endswith('get_filter_dashboard_data'):
                    # The unused upstream dashboard wrapper supplies invalid raw
                    # SQL filters in this Frappe version. Verify its mandatory
                    # scope at the actual grouped-list boundary instead.
                    counts = frappe.get_list('Order', fields=['status', 'count(*)'],
                        filters=filters, group_by='status', as_list=True)
                    self.assertEqual(dict(counts), {'Placed': 1})

    def test_an_extra_business_role_does_not_widen_sales_portal_areas(self):
        user = frappe.get_doc('User', self.user)
        user.append('roles', dict(role='Branch Manager'))
        user.save()
        branch = self.record('Portal Branch', branch_name='Out of sales scope')
        frappe.set_user(self.user)
        try:
            names = frappe.get_list('Portal Branch', pluck='name')
        except frappe.PermissionError:
            names = []
        self.assertNotIn(branch.name, names)
        with self.assertRaises(frappe.PermissionError):
            branch.check_permission('read')

    def test_ignore_permission_collaboration_helpers_cannot_add_comments_or_files(self):
        own = self.record('Order', sales_employee=self.employee.name)
        frappe.set_user(self.user)
        from frappe.desk.form.utils import add_comment
        with self.assertRaises(frappe.PermissionError):
            add_comment('Order', own.name, 'Forbidden comment', self.user, 'QA')
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc(dict(doctype='File', file_name='forbidden-sales-upload.txt',
                content=b'blocked', is_private=1, attached_to_doctype='Order',
                attached_to_name=own.name)).insert(ignore_permissions=True)
        self.assertFalse(frappe.db.exists('Comment', {'reference_doctype':'Order',
            'reference_name':own.name, 'content':'Forbidden comment'}))

    def test_navigation_skips_an_unrelated_order_between_two_visible_orders(self):
        prefix = 'navigation-' + uuid4().hex
        first = self.record('Order', name=prefix+'1', sales_employee=self.employee.name)
        self.record('Order', name=prefix+'2')
        third = self.record('Order', name=prefix+'3', customer=self.party.name)
        frappe.set_user(self.user)
        self.assertEqual(scope.get_next('Order', first.name, 0, sort_order='asc', sort_field='name'), third.name)
        self.assertEqual(scope.get_next('Order', third.name, 1, sort_order='asc', sort_field='name'), first.name)

    def test_intake_evidence_files_do_not_open_the_whole_other_sender_chat(self):
        source = self.record('WhatsApp Message', type='Incoming', whatsapp_account=self.account.name,
                             **{'from': '919000000077'})
        unrelated = self.record('WhatsApp Message', type='Incoming', whatsapp_account=self.account.name,
                                **{'from': '919000000077'})
        request = frappe.get_doc(dict(doctype='Order Intake Request', customer=self.party.name,
            source='WhatsApp', whatsapp_account=self.account.name, sender_number='919000000077',
            source_messages=[dict(message=source.name)])).insert()
        files = [self.record('File', file_name=doc.name+'.png', file_url='/private/files/'+doc.name+'.png',
            is_private=1, attached_to_doctype='WhatsApp Message', attached_to_name=doc.name)
            for doc in (source, unrelated)]
        frappe.set_user(self.user)
        self.assertTrue(scope.can_read_intake_source(source, request))
        self.assertFalse(scope.can_read_intake_source(unrelated, request))
        self.assertTrue(files[0].has_permission('read'))
        with self.assertRaises(frappe.PermissionError):
            files[1].check_permission('read')
        self.assertNotIn(source.name, frappe.get_list('WhatsApp Message', pluck='name'))
        with self.assertRaises(frappe.PermissionError):
            source.check_permission('read')

    def test_aggregate_realtime_rooms_cannot_disclose_unrelated_record_ids(self):
        frappe.set_user(self.user)
        for method, doctype in (('frappe.realtime.can_subscribe_doctype', 'Order'),
                               ('frappe.realtime.can_subscribe_doc', 'WhatsApp Account')):
            with self.subTest(method=method), \
                 patch('kunal_enterprises.permission_guards.exports._request_target', return_value=(method, {})), \
                 patch.object(frappe.local, 'form_dict', frappe._dict(doctype=doctype), create=True), \
                 patch.object(frappe.local, 'request', frappe._dict(), create=True):
                with self.assertRaises(frappe.PermissionError):
                    scope.guard_side_effect_request()

    def test_mixed_business_roles_do_not_enable_legacy_review_or_processing_actions(self):
        from kunal_enterprises.api import quick_orders, order_controls
        user = frappe.get_doc('User', self.user)
        user.append('roles', dict(role='Order Coordinator'))
        user.append('roles', dict(role='Godown Allocator'))
        user.save()
        quick = self.record('Quick Order Request', sales_employee=self.employee.name,
            customer=self.party.name, status='Pending Review', text='Read-only quick request')
        order = self.record('Order', sales_employee=self.employee.name, customer=self.party.name, status='Placed')
        frappe.set_user(self.user)
        for action, args in ((quick_orders.start_review, (quick.name,)),
                             (quick_orders.reject, (quick.name, 'Not allowed')),
                             (order_controls.mark_processing, (order.name,))):
            with self.subTest(action=action.__name__):
                result = action(*args)
                self.assertFalse(result['success'])
                self.assertEqual(result['http_status_code'], 403)
        self.assertEqual(frappe.db.get_value('Quick Order Request', quick.name, 'status'), 'Pending Review')
        self.assertEqual(frappe.db.get_value('Order', order.name, 'status'), 'Placed')
        self.assertFalse(frappe.db.get_value('Quick Order Request', quick.name, 'reviewed_by'))

    def test_business_lifecycle_denies_ignore_permissions_and_client_flags(self):
        own = self.record('Order', sales_employee=self.employee.name, status='Placed')
        quick = self.record('Quick Order Request', sales_employee=self.employee.name,
            customer=self.party.name, status='Pending Review', text='Read-only')
        intake = frappe.get_doc(dict(doctype='Order Intake Request', customer=self.party.name,
            sales_employee=self.employee.name)).insert()
        frappe.set_user(self.user)
        for doc in (own, quick, intake):
            with self.subTest(doctype=doc.doctype):
                doc.flags.ignore_validate = True
                doc.flags.sales_portal_write = True
                doc.flags.in_quick_order_transition = True
                if doc.doctype == 'Order Intake Request':
                    doc.customer = None
                else:
                    doc.status = 'Processing' if doc.doctype == 'Order' else 'In Review'
                with self.assertRaises(frappe.PermissionError):
                    doc.save(ignore_permissions=True)
        self.assertEqual(frappe.db.get_value('Order', own.name, 'status'), 'Placed')
        self.assertEqual(frappe.db.get_value('Quick Order Request', quick.name, 'status'), 'Pending Review')
        self.assertEqual(frappe.db.get_value('Order Intake Request', intake.name, 'customer'), self.party.name)

    def test_portal_link_loses_access_if_login_becomes_a_website_user(self):
        frappe.db.set_value('User', self.user, 'user_type', 'Website User')
        frappe.set_user(self.user)
        self.assertIsNone(scope.employee_for_user())
        self.assertEqual(frappe.get_list('Order', pluck='name'), [])

    def test_generic_link_search_cannot_disable_sales_scope(self):
        from frappe.desk.search import search_link, search_widget
        tag = 'search-scope-' + uuid4().hex
        self.party.customer_name = tag + ' assigned'
        self.party.save()
        other = self.record('Customer', customer_name=tag + ' hidden', business_legal_name=tag)
        frappe.set_user(self.user)
        for method, search in (('frappe.desk.search.search_link', search_link),
                               ('frappe.desk.search.search_widget', search_widget)):
            with self.subTest(method=method):
                form = frappe._dict(doctype='Customer', txt=tag, ignore_user_permissions=1)
                with patch('kunal_enterprises.permission_guards.exports._request_target', return_value=(method, {})), \
                     patch.object(frappe.local, 'form_dict', form, create=True), \
                     patch.object(frappe.local, 'request', frappe._dict(), create=True):
                    scope.guard_list_shares()
                self.assertFalse(form.ignore_user_permissions)
                rows = search('Customer', tag, ignore_user_permissions=form.ignore_user_permissions)
                names = {row['value'] if isinstance(row, dict) else row[0] for row in rows}
                self.assertEqual(names, {self.party.name})
                self.assertNotIn(other.name, names)

    def test_generic_search_cannot_dispatch_arbitrary_whitelisted_queries(self):
        frappe.set_user(self.user)
        form = frappe._dict(doctype='Customer', query='frappe.core.doctype.user.user.user_query')
        with patch('kunal_enterprises.permission_guards.exports._request_target',
                   return_value=('frappe.desk.search.search_link', {})), \
             patch.object(frappe.local, 'form_dict', form, create=True), \
             patch.object(frappe.local, 'request', frappe._dict(), create=True), \
             self.assertRaises(frappe.PermissionError):
            scope.guard_list_shares()
        # The narrow customer picker remains available through the same dispatcher.
        form.query = 'kunal_enterprises.api.sales_portal_intake.customer_query'
        with patch('kunal_enterprises.permission_guards.exports._request_target',
                   return_value=('frappe.desk.search.search_link', {})), \
             patch.object(frappe.local, 'form_dict', form, create=True), \
             patch.object(frappe.local, 'request', frappe._dict(), create=True):
            scope.guard_list_shares()

    def test_link_title_and_validation_do_not_reveal_unrelated_records(self):
        other = self.record('Customer', customer_name='Hidden customer title')
        frappe.set_user(self.user)
        for method in ('frappe.desk.search.get_link_title', 'frappe.client.validate_link'):
            form = frappe._dict(doctype='Customer', docname=other.name)
            with self.subTest(method=method), \
                 patch('kunal_enterprises.permission_guards.exports._request_target', return_value=(method, {})), \
                 patch.object(frappe.local, 'form_dict', form, create=True), \
                 patch.object(frappe.local, 'request', frappe._dict(), create=True), \
                 self.assertRaises(frappe.PermissionError):
                scope.guard_list_shares()
            form.docname=self.party.name
            with patch('kunal_enterprises.permission_guards.exports._request_target', return_value=(method, {})), \
                 patch.object(frappe.local, 'form_dict', form, create=True), \
                 patch.object(frappe.local, 'request', frappe._dict(), create=True):
                scope.guard_list_shares()
