"""Sales corrections and approval use real saves, scope and persisted audit fields."""
import json
from uuid import uuid4
import frappe
from frappe.tests.utils import FrappeTestCase
from kunal_enterprises.api.sales_portal_intake import correct, approve, customer_query
from kunal_enterprises.api.order_intake_processing import convert


class TestSalesPortalIntake(FrappeTestCase):
    def setUp(self):
        frappe.set_user('Administrator')
        self.tag = 'sales-review-' + uuid4().hex[:10]
        self.user = frappe.get_doc(dict(doctype='User', email=self.tag+'@example.com',
            first_name=self.tag, user_type='System User', send_welcome_email=0,
            roles=[dict(role='Sales Portal User')])).insert(ignore_permissions=True)
        self.customer = frappe.get_all('Customer', fields=['name'], limit=1)[0].name
        self.other_customer = frappe.get_all('Customer', filters={'name':['!=',self.customer]}, fields=['name'], limit=1)[0].name
        self.employee = frappe.get_doc(dict(doctype='Sales Employee', sales_employee_name=self.tag,
            mobile_number='8'+str(uuid4().int)[:9], portal_user=self.user.name,
            assigned_customers=[dict(customer=self.customer)])).insert()
        self.doc = frappe.get_doc(dict(doctype='Order Intake Request', customer=self.customer,
            sales_employee=self.employee.name, items=[dict(original_text='Synthetic evidence', quantity=2)])).insert()

    def tearDown(self):
        frappe.set_user('Administrator')
        frappe.db.rollback()

    def edits(self, **changes):
        row = self.doc.items[0]
        return [dict(row_key=row.row_key, item=row.item or '', godown=row.godown or '', quantity=changes.get('quantity',row.quantity))]

    def sales(self):
        frappe.set_user(self.user.name)

    def test_sales_save_and_approval_keep_evidence_and_record_actor(self):
        original = self.doc.items[0].original_text
        self.sales()
        correct(self.doc.name,str(self.doc.modified),self.customer,self.edits(quantity=5))
        self.doc.reload()
        approve(self.doc.name,str(self.doc.modified))
        self.doc.reload()
        self.assertEqual(self.doc.items[0].quantity,5)
        self.assertEqual(self.doc.items[0].original_text,original)
        self.assertEqual(self.doc.sales_approved_by,self.user.name)
        self.assertTrue(self.doc.sales_approved_at)
        self.assertEqual(self.doc.sales_approval_status,'Approved')
        self.assertEqual(len(json.loads(self.doc.sales_approval_history)),1)
        approve(self.doc.name,str(self.doc.modified))
        self.doc.reload()
        self.assertEqual(len(json.loads(self.doc.sales_approval_history)),1)
        correct(self.doc.name,str(self.doc.modified),self.customer,self.edits(quantity=6))
        self.doc.reload()
        self.assertEqual(self.doc.sales_approval_status,'Needs Reapproval')
        self.assertEqual(self.doc.sales_approved_by,self.user.name)
        approve(self.doc.name,str(self.doc.modified))
        self.doc.reload()
        self.assertEqual(self.doc.sales_approval_status,'Approved')
        self.assertEqual(len(json.loads(self.doc.sales_approval_history)),2)

    def test_admin_change_invalidates_but_cannot_forge_sales_approval(self):
        self.sales(); approve(self.doc.name,str(self.doc.modified))
        frappe.set_user('Administrator'); self.doc.reload()
        # Browser JSON represents timestamps as strings, unlike DB datetime values.
        self.doc.sales_approved_at=str(self.doc.sales_approved_at)
        self.doc.items[0].quantity=7; self.doc.save()
        self.assertEqual(self.doc.sales_approval_status,'Needs Reapproval')
        self.doc.sales_approved_by='Administrator'
        with self.assertRaises(frappe.PermissionError): self.doc.save()

    def test_unassigned_customer_and_forged_rows_are_rejected(self):
        self.sales()
        with self.assertRaises(frappe.PermissionError):
            correct(self.doc.name,str(self.doc.modified),self.other_customer,self.edits())
        rows=self.edits(); rows[0]['original_text']='forged'
        with self.assertRaises(frappe.ValidationError):
            correct(self.doc.name,str(self.doc.modified),self.customer,rows)
        with self.assertRaises(frappe.ValidationError):
            correct(self.doc.name,str(self.doc.modified),self.customer,[])
        names={row[0] for row in customer_query('Customer','','name',0,40,{})}
        self.assertEqual(names,{self.customer})

    def test_direct_save_conversion_stale_and_disabled_identity_are_denied(self):
        self.sales()
        self.doc.items[0].quantity=999
        with self.assertRaises(frappe.PermissionError): self.doc.save()
        with self.assertRaises(frappe.PermissionError): convert(self.doc.name)
        with self.assertRaises(frappe.TimestampMismatchError): approve(self.doc.name,'stale')
        frappe.set_user('Administrator')
        self.employee.status='Disabled'; self.employee.save()
        self.sales()
        with self.assertRaises(frappe.PermissionError): approve(self.doc.name,str(self.doc.modified))

    def test_own_request_not_assigned_still_visible_but_reassignment_is_limited(self):
        frappe.set_user('Administrator')
        self.doc.customer=self.other_customer; self.doc.save()
        self.sales()
        correct(self.doc.name,str(self.doc.modified),self.customer,self.edits(quantity=3))
        self.doc.reload()
        self.assertEqual(self.doc.customer,self.customer)

    def add_legacy_allocation(self):
        # Represent a persisted pre-simplification request, without asking the
        # current UI/controller to author the intentionally read-only old tables.
        godown = frappe.get_all('Tally Godown', pluck='name', limit=1)[0]
        warehouse = self.doc.append('warehouses', dict(row_key=uuid4().hex,
            original_text='Historic dispatch', godown=godown))
        warehouse.db_insert()
        allocation = self.doc.append('allocations', dict(item_row_key=self.doc.items[0].row_key,
            warehouse_row_key=warehouse.row_key, quantity=9))
        allocation.db_insert()
        frappe.db.set_value('Order Intake Request', self.doc.name, 'layout_simplified', 0, update_modified=False)
        self.doc.reload()
        return godown

    def test_first_approval_records_final_normalized_legacy_values(self):
        from kunal_enterprises.api.sales_portal_intake import fingerprint
        self.doc.items[0].quantity=0
        self.doc.save()
        godown=self.add_legacy_allocation()
        self.sales()
        approve(self.doc.name, str(self.doc.modified))
        self.doc.reload()
        self.assertEqual(self.doc.items[0].quantity,9)
        self.assertEqual(self.doc.items[0].godown,godown)
        self.assertEqual(self.doc.sales_approval_status,'Approved')
        self.assertEqual(self.doc.sales_approval_fingerprint,fingerprint(self.doc))
        self.assertEqual(json.loads(self.doc.sales_approval_history)[-1]['fingerprint'],fingerprint(self.doc))

    def test_admin_legacy_normalization_invalidates_existing_approval(self):
        self.doc.items[0].quantity=0
        self.doc.save()
        self.sales()
        approve(self.doc.name,str(self.doc.modified))
        frappe.set_user('Administrator')
        self.doc.reload()
        self.add_legacy_allocation()
        self.doc.save()
        self.assertEqual(self.doc.items[0].quantity,9)
        self.assertEqual(self.doc.sales_approval_status,'Needs Reapproval')
        self.assertEqual(self.doc.sales_approved_by,self.user.name)

    def test_own_unknown_customer_can_keep_blank_while_correcting_quantity(self):
        self.doc.customer = None
        self.doc.save()
        self.employee.set('assigned_customers', [])
        self.employee.save()
        self.sales()
        correct(self.doc.name,str(self.doc.modified),'',self.edits(quantity=4))
        self.doc.reload()
        self.assertFalse(self.doc.customer)
        self.assertEqual(self.doc.items[0].quantity,4)

    def test_partial_correction_preserves_unknown_quantity_until_number_is_supplied(self):
        self.doc.items[0].quantity_unknown=1
        self.doc.items[0].quantity=0
        self.doc.save()
        self.sales()
        correct(self.doc.name,str(self.doc.modified),self.customer,self.edits(quantity=None))
        self.doc.reload()
        self.assertTrue(self.doc.items[0].quantity_unknown)
        self.assertEqual(self.doc.items[0].quantity,0)
        correct(self.doc.name,str(self.doc.modified),self.customer,self.edits(quantity=3))
        self.doc.reload()
        self.assertFalse(self.doc.items[0].quantity_unknown)
        self.assertEqual(self.doc.items[0].quantity,3)
