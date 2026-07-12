import assert from 'node:assert/strict';
import test from 'node:test';

import {
  customerOrderDetailForMobile,
  customerProfileForMobile,
	editableCustomerProfilePatch,
	loadProfileForMobile,
	orderDetailForMobile,
	orderSummaryForMobile,
	orderPlacedByLabel,
	groupGodownAllocationsForMobile,
	saveCustomerProfileForMobile,
	salesEmployeeProfileForMobile,
} from '../src/domain/profileHistoryFlow.mjs';

test('godown allocations are grouped by godown while preserving item rows', () => {
  const groups = groupGodownAllocationsForMobile([
    { item: 'ITEM-2', item_name: 'Second', godown: 'Kukatpally', requested_quantity: 2 },
    { item: 'ITEM-1', item_name: 'First', godown: 'Goshamahal', requested_quantity: 1 },
    { item: 'ITEM-3', item_name: 'Third', godown: 'Kukatpally', requested_quantity: 4 },
  ]);

  assert.deepEqual(groups.map((group) => group.godown), ['Goshamahal', 'Kukatpally']);
  assert.deepEqual(groups[1].rows.map((row) => row.item), ['ITEM-2', 'ITEM-3']);
});

test('customer profile hides client code and only allows editable date and email fields', () => {
  const profile = customerProfileForMobile({
    customer: 'CUST-001',
    customer_name: 'Asha Textiles',
    business_legal_name: 'Asha Textiles Pvt Ltd',
    mobile_number: '9000000001',
    email_id: 'asha@example.com',
    date_of_birth: '1990-01-02',
    date_of_anniversary: '2015-03-04',
    customer_app_access: true,
    client_code: 'ASHA-LEDGER-001',
  });

  assert.equal(profile.customer_name, 'Asha Textiles');
  assert.deepEqual(profile.editable_fields, ['email_id', 'date_of_birth', 'date_of_anniversary']);
  assert.equal(Object.hasOwn(profile, 'client_code'), false);

  assert.deepEqual(
    editableCustomerProfilePatch({
      email_id: 'new@example.com',
      date_of_birth: '1990-01-02',
      customer_name: 'Should Not Patch',
    }),
    {
      email_id: 'new@example.com',
      date_of_birth: '1990-01-02',
    },
  );
});

test('sales employee profile is read only', () => {
  const profile = salesEmployeeProfileForMobile({
    sales_employee: 'SE-001',
    sales_employee_name: 'Ravi Sales',
    mobile_number: '9000000101',
    employee_code: 'EMP-01',
    status: 'Active',
  });

  assert.equal(profile.sales_employee_name, 'Ravi Sales');
	assert.deepEqual(profile.editable_fields, []);
});

test('profile load and save failures become recoverable access states', async () => {
	const load = await loadProfileForMobile({
		identityType: 'Customer',
		identity: 'CUST-001',
		getProfile: async () => {
			throw new Error('Customer App Access is not active');
		},
	});
	const save = await saveCustomerProfileForMobile({
		customer: 'CUST-001',
		patch: {
			email_id: 'new@example.com',
			customer_name: 'Blocked Patch',
		},
		updateCustomerProfile: async (_customer, patch) => {
			assert.deepEqual(patch, { email_id: 'new@example.com' });
			throw new Error('Customer App Access is not active');
		},
	});

	assert.equal(load.ok, false);
	assert.equal(load.state.kind, 'access_removed');
	assert.equal(save.ok, false);
	assert.equal(save.state.kind, 'access_removed');
});

test('order summaries map manual review to under review', () => {
  const summary = orderSummaryForMobile({
    name: 'KE-26-05-0001',
    portal_reference_number: 'KE-26-05-0001',
    status: 'Manual Review',
    total_quantity: 4,
  });

  assert.equal(summary.display_status, 'Under Review');
});

test('customer order detail hides sales employee note and stock internals', () => {
  const detail = customerOrderDetailForMobile({
    name: 'KE-26-05-0001',
    status: 'Placed',
    sales_employee_note: 'Call before dispatch',
    client_code: 'ASHA-LEDGER-001',
    godown_allocations: [
      {
        item: 'ITEM-COTTON-001',
        godown: 'Main Godown',
        requested_quantity: 4,
        stock_shown_at_order_time: 12,
      },
    ],
  });

  assert.equal(Object.hasOwn(detail, 'sales_employee_note'), false);
  assert.equal(Object.hasOwn(detail, 'client_code'), false);
  assert.equal(Object.hasOwn(detail.godown_allocations[0], 'stock_shown_at_order_time'), false);
});

test('order history and detail remove monetary fields before mobile rendering', () => {
  const summary = orderSummaryForMobile({
    name: 'KE-26-05-0001',
    portal_reference_number: 'KE-26-05-0001',
    status: 'Placed',
    total_quantity: 4,
    total_amount: 1200,
    tax_amount: 216,
    discount_value: 50,
  });
  const detail = customerOrderDetailForMobile({
    name: 'KE-26-05-0001',
    portal_reference_number: 'KE-26-05-0001',
    status: 'Placed',
    total_quantity: 4,
    rate: 300,
    godown_allocations: [
      {
        item: 'ITEM-COTTON-001',
        godown: 'Main Godown',
        requested_quantity: 4,
        price: 300,
      },
    ],
  });

  assert.equal(Object.hasOwn(summary, 'total_amount'), false);
  assert.equal(Object.hasOwn(summary, 'tax_amount'), false);
  assert.equal(Object.hasOwn(summary, 'discount_value'), false);
  assert.equal(Object.hasOwn(detail, 'rate'), false);
  assert.equal(Object.hasOwn(detail.godown_allocations[0], 'price'), false);
});

test('customer order detail labels self-placed and sales-employee-placed orders', () => {
  assert.equal(orderPlacedByLabel({ placed_by_identity_type: 'Customer' }, 'Customer'), 'You');
  assert.equal(
    orderPlacedByLabel(
      {
        placed_by_identity_type: 'Sales Employee',
        sales_employee_name: 'Ravi Sales',
      },
      'Customer',
    ),
    'Ravi Sales',
  );
  assert.equal(
    orderPlacedByLabel(
      {
        placed_by_identity_type: 'Sales Employee',
        sales_employee_name: 'Ravi Sales',
      },
      'Sales Employee',
    ),
    'You',
  );
});

test('order detail keeps friendly item names for summary and godown rows', () => {
  const detail = orderDetailForMobile(
    {
      name: 'KE-26-05-0001',
      status: 'Placed',
      placed_by_identity_type: 'Sales Employee',
      placed_by_name: 'Ravi Sales',
      items: [
        {
          item: 'ITEM-COTTON-001',
          item_name: 'Cotton Roll',
          root_stock_group: 'Cotton',
          unit: 'PCS',
          requested_quantity: 4,
        },
      ],
      godown_allocations: [
        {
          item: 'ITEM-COTTON-001',
          item_name: 'Cotton Roll',
          unit: 'PCS',
          godown: 'Main Godown',
          requested_quantity: 4,
        },
      ],
    },
    { viewerIdentityType: 'Customer' },
  );

  assert.equal(detail.placed_by_label, 'Ravi Sales');
  assert.equal(detail.items[0].item_name, 'Cotton Roll');
  assert.equal(detail.godown_allocations[0].item_name, 'Cotton Roll');
});

test('sales employee order detail labels orders placed by that employee as you', () => {
  const detail = orderDetailForMobile(
    {
      name: 'KE-26-05-0001',
      status: 'Placed',
      placed_by_identity_type: 'Sales Employee',
      sales_employee_name: 'Ravi Sales',
      sales_employee_note: 'Call before dispatch',
      godown_allocations: [
        {
          item: 'ITEM-COTTON-001',
          godown: 'Main Godown',
          requested_quantity: 4,
          stock_shown_at_order_time: 12,
        },
      ],
    },
    { viewerIdentityType: 'Sales Employee' },
  );

  assert.equal(detail.placed_by_label, 'You');
  assert.equal(Object.hasOwn(detail, 'sales_employee_note'), true);
  assert.equal(Object.hasOwn(detail.godown_allocations[0], 'stock_shown_at_order_time'), false);
});
