"""Real persisted conversion boundaries; every test rolls back all business records."""
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from kunal_enterprises.api import order_intake_processing as api
from kunal_enterprises.api.order_intake_conversation import messages
from kunal_enterprises.integrations import order_intake_learning as learning


class TestOrderIntakeProcessing(FrappeTestCase):
	def setUp(self):
		frappe.set_user('Administrator')
		self.ledger = frappe.get_doc(dict(doctype='Tally Customer Ledger', client_code=uuid4().hex,
			ledger_name='Processing synthetic ledger', is_active=1)).insert()
		self.customer = frappe.get_doc(dict(doctype='Customer', customer_name='Processing '+uuid4().hex,
			business_legal_name='Synthetic', onboarding_source='Tally', client_code=self.ledger.client_code)).insert()
		group = frappe.get_doc(dict(doctype='Tally Stock Group', group_name='Processing '+uuid4().hex, is_root=1)).insert()
		self.item = frappe.get_doc(dict(doctype='Tally Item', item_name='Processing '+uuid4().hex, root_stock_group=group.name, uom='NOS')).insert()
		self.godown = frappe.get_doc(dict(doctype='Tally Godown', godown_name='Processing '+uuid4().hex)).insert()
		account = frappe.get_doc(dict(doctype='WhatsApp Account', account_name='Processing '+uuid4().hex,
			phone_id=uuid4().hex, status='Active', auto_read_receipt=0)).insert(ignore_permissions=True)
		self.source = frappe.get_doc(dict(doctype='WhatsApp Message', type='Incoming', whatsapp_account=account.name,
			message='Synthetic order', message_id=uuid4().hex, content_type='text', **{'from':'919000000095'})).insert(ignore_permissions=True)
		self.doc = frappe.get_doc(dict(doctype='Order Intake Request', request_type='Order', customer=self.customer.name,
			whatsapp_account=account.name, sender_number='919000000095', customer_text='Synthetic customer',
			source_messages=[dict(message=self.source.name)], items=[dict(original_text='21317 MR', item=self.item.name,
			quantity=2, unit='NOS', godown=self.godown.name, warehouse_text='Synthetic depot', source_message=self.source.name)])).insert()
		self.pdf_patch = patch.object(api, 'create_pdf', self.fake_pdf); self.pdf_patch.start()

	def tearDown(self):
		self.pdf_patch.stop(); frappe.set_user('Administrator'); frappe.db.rollback()

	def fake_pdf(self, order):
		return frappe.get_doc(dict(doctype='Order PDF', order=order.name, customer=order.customer,
			status='Generated', generated_at=frappe.utils.now_datetime(), summary_text='Synthetic PDF')).insert(ignore_permissions=True)

	def convert(self):
		self.doc.reload()
		return api.convert(self.doc.name, str(self.doc.modified), messages(self.doc.name)['revision'])

	def test_conversion_and_duplicate_are_atomic_idempotent_without_messages(self):
		notifications = frappe.db.count('Order WhatsApp Notification')
		result = self.convert(); order = frappe.get_doc('Order', result['order']); self.doc.reload()
		self.assertEqual(order.order_intake_request, self.doc.name)
		self.assertEqual(order.items[0].requested_quantity, 2)
		self.assertEqual(order.godown_allocations[0].godown, self.godown.name)
		self.assertEqual(self.doc.reviewed_by, 'Administrator')
		self.assertEqual(frappe.db.count('Order PDF', {'order':order.name}), 1)
		self.assertGreater(frappe.db.count(learning.DT, {'source_order':order.name}), 0)
		self.assertEqual(api.convert(self.doc.name, 'stale', 'stale')['order'], order.name)
		self.assertEqual(frappe.db.count('Order PDF', {'order':order.name}), 1)
		self.assertEqual(frappe.db.count('Order WhatsApp Notification'), notifications)
		self.doc.reload(); self.doc.save()  # Harmless metadata saves remain possible.
		self.doc.items[0].quantity = 9
		with self.assertRaises(frappe.ValidationError): self.doc.save()

	def test_unknown_quantity_cannot_convert_even_with_a_positive_storage_value(self):
		self.doc.items[0].quantity_unknown = 1; self.doc.save()
		before = frappe.db.count('Order')
		with self.assertRaisesRegex(frappe.ValidationError, 'Confirm the requested quantity'):
			self.convert()
		self.assertEqual(frappe.db.count('Order'), before)
		self.doc.reload(); self.doc.items[0].quantity = 3; self.doc.save()
		self.assertFalse(self.doc.items[0].quantity_unknown)
		self.assertTrue(self.convert()['order'])

	def test_learning_failure_rolls_back_pdf_order_and_sequence(self):
		counts = {dt:frappe.db.count(dt) for dt in ('Order','Order PDF',learning.DT,'Order Reference Sequence')}
		def fail(*args):
			learning.record_confirmation(*args)
			raise RuntimeError('Synthetic failure after evidence')
		with patch.object(api,'record_confirmation',fail), self.assertRaises(RuntimeError): self.convert()
		self.doc.reload(); self.assertEqual(self.doc.status,'Pending Review'); self.assertFalse(self.doc.order)
		for dt,count in counts.items(): self.assertEqual(frappe.db.count(dt),count,dt)

	def test_actual_source_change_and_pending_proposals_block(self):
		revision=messages(self.doc.name)['revision']; modified=str(self.doc.modified)
		frappe.db.set_value('WhatsApp Message',self.source.name,'message','Changed',update_modified=False)
		with self.assertRaises(frappe.TimestampMismatchError): api.convert(self.doc.name,modified,revision)
		frappe.db.set_value('Order Intake Request', self.doc.name, 'proposed_updates', '[{"summary":"New quantity"}]')
		with self.assertRaises(frappe.ValidationError): self.convert()

	def test_required_tally_link_and_active_masters(self):
		frappe.db.set_value('Customer',self.customer.name,'client_code',None)
		# An arbitrary GUID alone is not the ledger connection used by Customer.
		frappe.db.set_value('Customer',self.customer.name,'tally_guid',uuid4().hex)
		with self.assertRaises(frappe.ValidationError): self.convert()
		frappe.db.set_value('Customer',self.customer.name,'client_code',self.ledger.client_code)
		frappe.db.set_value('Tally Customer Ledger',self.ledger.name,'is_active',0)
		with self.assertRaises(frappe.ValidationError): self.convert()
		frappe.db.set_value('Tally Customer Ledger',self.ledger.name,'is_active',1)
		frappe.db.set_value('Tally Godown',self.godown.name,'is_active',0)
		with self.assertRaises(frappe.ValidationError): self.convert()

	def test_blank_godown_unknown_sender_and_mobile_flags_are_not_blockers(self):
		frappe.db.set_value('Customer',self.customer.name,dict(status='Disabled',mobile_verified=0))
		employee=frappe.get_doc(dict(doctype='Sales Employee', sales_employee_name='Synthetic '+uuid4().hex,
			mobile_number='9'+str(uuid4().int)[:9],status='Disabled',mobile_verified=0)).insert()
		self.doc.sales_employee=employee.name
		self.doc.items[0].godown=None; self.doc.save()
		# No Customer phone matches this sender; portal confirmation remains valid.
		result=self.convert(); self.assertTrue(result['godown_assignment_pending'])

	def test_inquiries_resolve_without_order_and_can_be_reopened(self):
		self.doc.request_type='Stock Inquiry'; self.doc.save()
		counts={dt:frappe.db.count(dt) for dt in ('Order','Order PDF',learning.DT)}
		result=api.handle_inquiry(self.doc.name,str(self.doc.modified),messages(self.doc.name)['revision'])
		self.assertEqual(result['state'],'Resolved'); self.assertFalse(result['order'])
		self.assertEqual(api.handle_inquiry(self.doc.name,'stale','stale')['state'],'Resolved')
		for dt,count in counts.items(): self.assertEqual(frappe.db.count(dt),count)
		self.doc.reload(); self.doc.status='Pending Review'; self.doc.request_type='Order'; self.doc.save()
		self.assertTrue(self.convert()['order'])

	def test_mixed_or_unclear_cannot_convert_and_generic_links_are_protected(self):
		for kind in ('Mixed','Unclear','Price Inquiry'):
			self.doc.request_type=kind; self.doc.save()
			with self.assertRaises(frappe.ValidationError): self.convert()
		self.doc.order='fake'; self.doc.flags.ignore_links=True
		with self.assertRaises(frappe.ValidationError): self.doc.save()
		self.doc.reload(); self.doc.processed_at=frappe.utils.now_datetime()
		with self.assertRaises(frappe.PermissionError): self.doc.save()

	def test_cancelled_order_remains_linked_and_does_not_recreate(self):
		result=self.convert(); order=frappe.get_doc('Order',result['order'])
		order.status='Cancelled'; order.cancellation_reason='Synthetic'; order.save(ignore_permissions=True)
		self.assertEqual(api.convert(self.doc.name)['order'],order.name)
		self.assertEqual(frappe.db.count(learning.DT,{'source_order':order.name,'active':1}),0)

	def test_generic_order_cannot_forge_an_intake_link(self):
		from kunal_enterprises.integrations.order_intake_order import create_order
		with patch('kunal_enterprises.kunal_enterprises.doctype.order.order.Order._validate_intake_order_link'):
			order=create_order(self.doc)
		# Insert a second Order using the ordinary document API, with forged linkage.
		other=frappe.copy_doc(order); other.portal_reference_number='Synthetic-'+uuid4().hex
		with self.assertRaises(frappe.PermissionError): other.insert(ignore_permissions=True)

	def test_pdf_file_is_removed_on_failure_before_outer_rollback(self):
		from pathlib import Path
		from frappe.utils.file_manager import save_file
		from kunal_enterprises.api.orders import _build_plain_text_pdf
		from kunal_enterprises.integrations import order_intake_order as builder
		paths=[]
		def attachment(pdf,order,summary):
			file=save_file('Synthetic-'+uuid4().hex+'.pdf', _build_plain_text_pdf('Synthetic '+uuid4().hex), pdf.doctype,pdf.name,is_private=1)
			paths.append(Path(file.get_full_path())); self.assertTrue(paths[-1].exists())
			return file
		count=frappe.db.count('File')
		with patch.object(api,'create_pdf',builder.create_pdf), patch.object(builder,'_attach_order_pdf_file',attachment), patch.object(api,'record_confirmation',side_effect=RuntimeError('after PDF')):
			with self.assertRaises(RuntimeError): self.convert()
		self.assertEqual(len(paths),1); self.assertFalse(paths[0].exists())
		self.assertEqual(frappe.db.count('File'),count)

	def test_intake_pdf_keeps_customer_distinct_from_salesperson(self):
		from kunal_enterprises.integrations.order_intake_order import intake_pdf_summary
		from types import SimpleNamespace
		order = SimpleNamespace(customer=self.customer.name)
		with patch('kunal_enterprises.integrations.order_intake_order._build_customer_pdf_summary', return_value='Order: LOCAL-1\nPlaced by: Sales Person\nItems:\n- Material | Quantity: 2'):
			summary = intake_pdf_summary(order)
		self.assertIn('Customer: ' + self.customer.customer_name, summary)
		self.assertIn('Placed by: Sales Person', summary)
		self.assertIn('Order: LOCAL-1', summary)
		self.assertIn('Material | Quantity: 2', summary)

	def test_handled_inquiry_records_classification_correction_atomically(self):
		frappe.db.set_value('Order Intake Request', self.doc.name, 'ai_initial_values', '{"request_type":"Order"}')
		self.doc.reload(); self.doc.request_type = 'Stock Inquiry'
		self.doc.correction_reason = 'Customer asked about availability, not a booking'
		self.doc.save()
		before = frappe.db.count('Order')
		result = api.handle_inquiry(self.doc.name, str(self.doc.modified), messages(self.doc.name)['revision'])
		self.assertEqual(result['state'], 'Resolved')
		evidence = frappe.get_all('Order Intake Match Evidence', filters={'source_request': self.doc.name, 'kind': 'request_type'}, fields=['suggested_value', 'selected_master', 'correction_reason'])
		self.assertEqual(len(evidence), 1)
		self.assertEqual(evidence[0].suggested_value, 'Order')
		self.assertEqual(evidence[0].selected_master, 'Stock Inquiry')
		self.assertIn('availability', evidence[0].correction_reason)
		self.assertEqual(frappe.db.count('Order'), before)

	def test_inquiry_feedback_failure_does_not_mark_it_handled(self):
		self.doc.request_type = 'Stock Inquiry'; self.doc.save()
		with patch.object(api, 'record_inquiry_confirmation', side_effect=RuntimeError('Learning write failed')):
			with self.assertRaises(RuntimeError):
				api.handle_inquiry(self.doc.name, str(self.doc.modified), messages(self.doc.name)['revision'])
		self.assertEqual(self.doc.reload().status, 'Pending Review')
		self.assertFalse(self.doc.processed_at)

	def test_inactive_item_missing_godown_and_empty_selected_rows_block(self):
		frappe.db.set_value('Tally Item',self.item.name,'is_active',0)
		with self.assertRaises(frappe.ValidationError): self.convert()
		frappe.db.set_value('Tally Item',self.item.name,'is_active',1)
		frappe.db.set_value('Order Intake Item',self.doc.items[0].name,'godown','missing-godown')
		with self.assertRaises(frappe.DoesNotExistError): self.convert()
		frappe.db.set_value('Order Intake Item',self.doc.items[0].name,dict(godown=None,item=None))
		with self.assertRaises(frappe.ValidationError): self.convert()

	def test_guest_cannot_process_even_a_saved_request(self):
		frappe.set_user('Guest')
		with self.assertRaises(frappe.PermissionError): api.convert(self.doc.name)

	def test_converted_order_customer_salesperson_and_source_cannot_drift(self):
		result = self.convert()
		other = frappe.get_doc(dict(doctype='Customer', customer_name='Other '+uuid4().hex,
			business_legal_name='Synthetic', onboarding_source='Tally')).insert()
		for field, value in [('customer', other.name), ('sales_employee', 'different-salesperson'),
			('order_source', 'Sales Employee')]:
			order = frappe.get_doc('Order', result['order'])
			order.set(field, value)
			order.flags.ignore_links = True
			with self.assertRaises(frappe.ValidationError, msg=field):
				order.save(ignore_permissions=True)

	def test_order_coordinator_can_convert_and_read_own_result(self):
		from kunal_enterprises.tests import test_foundation as foundation
		user = foundation.TestOrderSubmission._create_role_user(self,
			'intake-process-'+uuid4().hex+'@example.com', 'Order Coordinator')
		frappe.set_user(user.name)
		result = self.convert()
		order = frappe.get_doc('Order', result['order'])
		order.check_permission('read')
		self.assertEqual(self.convert()['order'], order.name)

	def test_conversion_uses_current_locked_master_state_not_older_snapshot(self):
		# Simulate a commit between the transaction's first read and FOR UPDATE:
		# normal reads still see NOS/active, but the lock returns current values.
		get_doc = frappe.get_doc
		def inactive(*args, **kwargs):
			doc = get_doc(*args, **kwargs)
			if args[:2] == ('Tally Item', self.item.name) and kwargs.get('for_update'):
				doc.is_active = 0
			return doc
		with patch.object(frappe, 'get_doc', side_effect=inactive):
			with self.assertRaises(frappe.ValidationError): self.convert()
		self.doc.reload(); self.doc.items[0].unit = 'KG'; self.doc.save()
		def current_unit(*args, **kwargs):
			doc = get_doc(*args, **kwargs)
			if args[:2] == ('Tally Item', self.item.name) and kwargs.get('for_update'):
				doc.uom = 'KG'
			return doc
		with patch.object(frappe, 'get_doc', side_effect=current_unit):
			result = self.convert()
		self.assertEqual(frappe.get_doc('Order', result['order']).items[0].unit, 'KG')

	def test_natural_plural_unit_uses_same_canonical_stock_unit_without_conversion(self):
		frappe.db.set_value('Tally Item',self.item.name,'uom','SHEET')
		self.doc.items[0].unit='sheets';self.doc.save()
		result=self.convert();order=frappe.get_doc('Order',result['order'])
		self.assertEqual(order.items[0].unit,'SHEET')
		self.assertEqual(order.items[0].requested_quantity,2)

	def test_incoming_unit_labels_never_block_or_scale_quantities(self):
		frappe.db.set_value('Tally Item',self.item.name,'uom','SHEET')
		for index,label in enumerate(('nos','kg','pieces','sheets','square feet')):
			with self.subTest(label=label):
				point='unit_label_'+str(index);frappe.db.savepoint(point)
				try:
					self.doc.reload();self.doc.items[0].unit=label;self.doc.items[0].quantity=2.5;self.doc.save()
					result=self.convert();order=frappe.get_doc('Order',result['order'])
					self.assertEqual(order.items[0].unit,'SHEET')
					self.assertEqual(order.items[0].requested_quantity,2.5)
					self.assertEqual(order.godown_allocations[0].requested_quantity,2.5)
					self.assertEqual(self.doc.reload().items[0].unit,label)
				finally:
					frappe.db.rollback(save_point=point);frappe.db.release_savepoint(point)

	def test_different_labels_for_same_item_merge_only_numeric_quantities(self):
		self.doc.items[0].unit='kg'; self.doc.items[0].quantity=2.5
		self.doc.append('items',dict(original_text='21317 MR', item=self.item.name, quantity=1.5,
			unit='square feet', godown=self.godown.name, source_message=self.source.name))
		self.doc.save()
		result=self.convert(); order=frappe.get_doc('Order',result['order'])
		self.assertEqual(len(order.items),1)
		self.assertEqual(order.items[0].requested_quantity,4)
		self.assertEqual(order.items[0].unit,'NOS')
		self.assertEqual(len(order.godown_allocations),1)
		self.assertEqual(order.godown_allocations[0].requested_quantity,4)
		self.assertEqual([row.unit for row in self.doc.reload().items],['kg','square feet'])
