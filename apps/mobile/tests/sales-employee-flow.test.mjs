import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildSalesEmployeeOrderPayload,
  filterAllowedCustomers,
  salesEmployeeOrderGuard,
  sanitizeCustomerForSalesEmployee,
  salesEmployeeHistory,
} from '../src/domain/salesEmployeeFlow.mjs';

const customers = [
  {
    customer: 'CUST-001',
    customer_name: 'Asha Textiles',
    business_legal_name: 'Asha Textiles Pvt Ltd',
    client_code: 'ASHA-LEDGER-001',
  },
  {
    customer: 'CUST-002',
    customer_name: 'Bharat Stores',
    business_legal_name: 'Bharat Stores LLP',
    client_code: 'BHARAT-LEDGER-002',
  },
];

test('sales employee search can match client code but never displays it', () => {
  const results = filterAllowedCustomers(customers, 'ledger-001').map(sanitizeCustomerForSalesEmployee);

  assert.equal(results.length, 1);
  assert.equal(results[0].customer, 'CUST-001');
  assert.equal(results[0].customer_name, 'Asha Textiles');
  assert.equal(results[0].business_legal_name, 'Asha Textiles Pvt Ltd');
  assert.equal(Object.hasOwn(results[0], 'client_code'), false);
});

test('sales employee order payload includes selected customer and optional internal note', () => {
	const payload = buildSalesEmployeeOrderPayload({
		salesEmployee: 'SE-001',
		customer: 'CUST-001',
		note: 'Send through main dispatch desk',
		allocations: [
			{
				item: 'ITEM-COTTON-001',
				godown: 'Main Godown',
				quantity: 3,
				stockShownAtOrderTime: 12,
				stockSnapshotAt: '2026-05-21 14:11:06',
			},
		],
	});

	assert.equal(payload.sales_employee, 'SE-001');
	assert.equal(payload.customer, 'CUST-001');
	assert.equal(payload.sales_employee_note, 'Send through main dispatch desk');
	assert.equal(payload.allocations.length, 1);
	assert.equal(payload.allocations[0].stock_shown_at_order_time, 12);
	assert.equal(payload.allocations[0].stock_snapshot_at, '2026-05-21 14:11:06');
	assert.equal(Object.hasOwn(payload.allocations[0], 'stockShownAtOrderTime'), false);
});

test('sales employee submit routes back to customer selection until a customer is selected', () => {
  assert.deepEqual(
    salesEmployeeOrderGuard({
      selectedCustomer: null,
      allocations: [{ item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 3 }],
    }),
    {
      canSubmit: false,
      step: 'customer',
      state: { kind: 'validation_error', message: 'Select a Customer before ordering.' },
    },
  );

  assert.deepEqual(
    salesEmployeeOrderGuard({
      selectedCustomer: { customer: 'CUST-001', customer_name: 'Asha Textiles' },
      allocations: [{ item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 3 }],
    }),
    {
      canSubmit: true,
      step: 'summary',
      state: { kind: 'idle' },
    },
  );
});

test('sales employee history only includes orders placed by that employee', () => {
  const history = salesEmployeeHistory(
    [
      { name: 'KE-26-05-0001', sales_employee: 'SE-001', customer: 'CUST-001' },
      { name: 'KE-26-05-0002', sales_employee: 'SE-002', customer: 'CUST-001' },
      { name: 'KE-26-05-0003', sales_employee: 'SE-001', customer: 'CUST-002' },
    ],
    'SE-001',
  );

  assert.deepEqual(
    history.map((order) => order.name),
    ['KE-26-05-0001', 'KE-26-05-0003'],
  );
});
