import assert from 'node:assert/strict';
import test from 'node:test';

import { createFrappeApiClient } from '../src/api/frappeClient.mjs';

function fakeCall(responseByMethod) {
  const calls = [];
  return {
    calls,
    call: {
      get: async (method, params) => {
        calls.push({ verb: 'get', method, params });
        return responseByMethod[method];
      },
      post: async (method, params) => {
        calls.push({ verb: 'post', method, params });
        return responseByMethod[method];
      },
    },
  };
}

test('frappe client submits orders through the backend order endpoint', async () => {
  const fake = fakeCall({
    'kunal_enterprises.api.orders.submit': {
      message: {
        success: true,
        data: {
          order: 'KE-26-05-0001',
          portal_reference_number: 'KE-26-05-0001',
          status: 'Placed',
        },
      },
    },
  });
  const client = createFrappeApiClient(fake.call);

  const result = await client.submitOrder({
    customer: 'CUST-001',
    allocations: [{ item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 2 }],
  });

  assert.equal(result.portal_reference_number, 'KE-26-05-0001');
  assert.deepEqual(fake.calls[0], {
    verb: 'post',
    method: 'kunal_enterprises.api.orders.submit',
    params: {
      customer: 'CUST-001',
      allocations: [{ item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 2 }],
    },
  });
});

test('frappe client loads allowed customers without exposing client code', async () => {
  const fake = fakeCall({
    'kunal_enterprises.api.sales_employees.allowed_customers': {
      message: {
        success: true,
        data: {
          customers: [
            {
              customer: 'CUST-001',
              customer_name: 'Asha Textiles',
              business_legal_name: 'Asha Textiles Pvt Ltd',
              client_code: 'ASHA-LEDGER-001',
            },
          ],
        },
      },
    },
  });
  const client = createFrappeApiClient(fake.call);

  const customers = await client.allowedCustomers('SE-001', 'asha');

  assert.equal(customers.length, 1);
  assert.equal(Object.hasOwn(customers[0], 'client_code'), false);
  assert.equal(fake.calls[0].method, 'kunal_enterprises.api.sales_employees.allowed_customers');
  assert.deepEqual(fake.calls[0].params, { sales_employee: 'SE-001', search: 'asha' });
});

test('frappe client loads customer access status through backend checklist endpoint', async () => {
  const fake = fakeCall({
    'kunal_enterprises.api.customer_access.status': {
      message: {
        success: true,
        data: {
          customer: 'CUST-001',
          customer_app_access: true,
          checklist: {
            mobile_verified: true,
            admin_approved: true,
            valid_client_code: true,
          },
        },
      },
    },
  });
  const client = createFrappeApiClient(fake.call);

  const status = await client.customerAccessStatus('CUST-001');

  assert.equal(status.customer_app_access, true);
  assert.deepEqual(fake.calls[0], {
    verb: 'get',
    method: 'kunal_enterprises.api.customer_access.status',
    params: { customer: 'CUST-001' },
  });
});

test('frappe client sends existing customer login OTP through the shared OTP endpoint', async () => {
  const fake = fakeCall({
    'kunal_enterprises.api.otp.send_otp': {
      message: {
        success: true,
        data: {
          mobile_number: '9000000001',
          identity_type: 'Customer',
          next_step: 'verify_otp',
        },
      },
    },
  });
  const client = createFrappeApiClient(fake.call);

  const response = await client.startCustomerOtp('9000000001');

  assert.equal(response.identity_type, 'Customer');
  assert.deepEqual(fake.calls[0], {
    verb: 'post',
    method: 'kunal_enterprises.api.otp.send_otp',
    params: {
      mobile_number: '9000000001',
      identity_type: 'Customer',
    },
  });
});

test('frappe client resends OTP through the backend resend endpoint', async () => {
  const fake = fakeCall({
    'kunal_enterprises.api.otp.resend_otp': {
      message: {
        success: true,
        data: {
          mobile_number: '9000000101',
          identity_type: 'Sales Employee',
          next_step: 'verify_otp',
          cooldown_seconds: 45,
        },
      },
    },
  });
  const client = createFrappeApiClient(fake.call);

  const response = await client.resendOtp('9000000101', 'Sales Employee');

  assert.equal(response.identity_type, 'Sales Employee');
  assert.deepEqual(fake.calls[0], {
    verb: 'post',
    method: 'kunal_enterprises.api.otp.resend_otp',
    params: {
      mobile_number: '9000000101',
      identity_type: 'Sales Employee',
    },
  });
});

test('frappe client unwraps backend errors from the response envelope', async () => {
  const fake = fakeCall({
    'kunal_enterprises.api.product_groups.allowed': {
      message: {
        success: false,
        message: 'Unable to load allowed Product Groups',
        error: { message: 'Customer App Access is not active' },
      },
    },
  });
  const client = createFrappeApiClient(fake.call);

  await assert.rejects(
    () => client.allowedProductGroups('CUST-001'),
    /Customer App Access is not active/,
  );
});

test('frappe client refreshes and revokes mobile sessions through SDK-level auth headers', async () => {
 const fake = fakeCall({
    'kunal_enterprises.api.token_verification.current_session': {
      message: {
        success: true,
        data: {
          identity_type: 'Customer',
          identity: 'CUST-001',
        },
      },
    },
    'kunal_enterprises.api.token_verification.revoke_token': {
      message: {
        success: true,
        data: {
          revoked: true,
        },
      },
    },
  });
  const client = createFrappeApiClient(fake.call);

  const session = await client.currentSession();
  const revoked = await client.revokeToken();

  assert.equal(session.identity, 'CUST-001');
  assert.equal(revoked.revoked, true);
  assert.deepEqual(fake.calls, [
    {
      verb: 'get',
      method: 'kunal_enterprises.api.token_verification.current_session',
      params: undefined,
    },
    {
      verb: 'post',
      method: 'kunal_enterprises.api.token_verification.revoke_token',
      params: undefined,
    },
  ]);
});

test('frappe client updates customer profile through allowed profile endpoint', async () => {
  const fake = fakeCall({
    'kunal_enterprises.api.profile.update_customer_profile': {
      message: {
        success: true,
        data: {
          customer: 'CUST-001',
          email_id: 'new@example.com',
          date_of_birth: '1990-01-02',
        },
      },
    },
  });
  const client = createFrappeApiClient(fake.call);

  const profile = await client.updateCustomerProfile('CUST-001', {
    email_id: 'new@example.com',
    date_of_birth: '1990-01-02',
  });

  assert.equal(profile.email_id, 'new@example.com');
  assert.deepEqual(fake.calls[0], {
    verb: 'post',
    method: 'kunal_enterprises.api.profile.update_customer_profile',
    params: {
      customer: 'CUST-001',
      payload: {
        email_id: 'new@example.com',
        date_of_birth: '1990-01-02',
      },
    },
  });
});

test('frappe client normalizes godown stock order for mobile display', async () => {
  const fake = fakeCall({
    'kunal_enterprises.api.product_groups.item_stock': {
      message: {
        success: true,
        data: {
          godowns: [
            { item: 'ITEM-COTTON-001', godown: 'Zero Godown', quantity: 0 },
            { item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 8 },
          ],
        },
      },
    },
  });
  const client = createFrappeApiClient(fake.call);

  const rows = await client.itemStock('CUST-001', 'ITEM-COTTON-001');

  assert.deepEqual(rows.map((row) => row.godown), ['Main Godown', 'Zero Godown']);
});

test('frappe client passes sales employee context to item and stock access APIs', async () => {
  const fake = fakeCall({
    'kunal_enterprises.api.product_groups.items': {
      message: {
        success: true,
        data: {
          items: [{ name: 'ITEM-COTTON-001', item_name: 'Cotton 40s', root_stock_group: 'Cotton Fabric' }],
        },
      },
    },
    'kunal_enterprises.api.product_groups.item_stock': {
      message: {
        success: true,
        data: {
          godowns: [{ item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 8 }],
        },
      },
    },
  });
  const client = createFrappeApiClient(fake.call);

  await client.allowedItems('CUST-001', 'Cotton Fabric', 'SE-001');
  await client.itemStock('CUST-001', 'ITEM-COTTON-001', 'SE-001');

  assert.deepEqual(fake.calls, [
    {
      verb: 'get',
      method: 'kunal_enterprises.api.product_groups.items',
      params: {
        customer: 'CUST-001',
        product_group: 'Cotton Fabric',
        sales_employee: 'SE-001',
      },
    },
    {
      verb: 'get',
      method: 'kunal_enterprises.api.product_groups.item_stock',
      params: {
        customer: 'CUST-001',
        item: 'ITEM-COTTON-001',
        sales_employee: 'SE-001',
      },
    },
  ]);
});

test('frappe client normalizes live order history and detail for mobile safety', async () => {
  const fake = fakeCall({
    'kunal_enterprises.api.orders.history': {
      message: {
        success: true,
        data: {
          orders: [
            {
              name: 'KE-26-05-0001',
              portal_reference_number: 'KE-26-05-0001',
              status: 'Manual Review',
              total_quantity: 4,
              total_amount: 1200,
              tax_amount: 216,
            },
          ],
        },
      },
    },
    'kunal_enterprises.api.orders.detail': {
      message: {
        success: true,
        data: {
          name: 'KE-26-05-0001',
          portal_reference_number: 'KE-26-05-0001',
          status: 'Manual Review',
          sales_employee_note: 'Call before dispatch',
          manual_review_reason: 'Customer mismatch',
          client_code: 'ASHA-LEDGER-001',
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
              price: 300,
              amount: 1200,
            },
          ],
        },
      },
    },
  });
  const client = createFrappeApiClient(fake.call);

  const history = await client.orderHistory('CUST-001');
  const detail = await client.orderDetail('KE-26-05-0001', { customer: 'CUST-001' });

  assert.equal(history[0].display_status, 'Under Review');
  assert.equal(Object.hasOwn(history[0], 'total_amount'), false);
  assert.equal(Object.hasOwn(history[0], 'tax_amount'), false);
  assert.equal(detail.display_status, 'Under Review');
  assert.equal(Object.hasOwn(detail, 'sales_employee_note'), false);
  assert.equal(Object.hasOwn(detail, 'manual_review_reason'), false);
  assert.equal(Object.hasOwn(detail, 'client_code'), false);
  assert.equal(detail.placed_by_label, 'Ravi Sales');
  assert.equal(detail.items[0].item_name, 'Cotton Roll');
  assert.equal(detail.godown_allocations[0].item_name, 'Cotton Roll');
  assert.equal(Object.hasOwn(detail.godown_allocations[0], 'price'), false);
  assert.equal(Object.hasOwn(detail.godown_allocations[0], 'amount'), false);
});

test('frappe client can request sales employee order history without a customer filter', async () => {
  const fake = fakeCall({
    'kunal_enterprises.api.orders.history': {
      message: {
        success: true,
        data: {
          orders: [
            {
              name: 'KE-26-05-0001',
              portal_reference_number: 'KE-26-05-0001',
              status: 'Placed',
              sales_employee: 'SE-001',
              customer: 'CUST-001',
              customer_name: 'Asha Textiles',
            },
            {
              name: 'KE-26-05-0002',
              portal_reference_number: 'KE-26-05-0002',
              status: 'Placed',
              sales_employee: 'SE-001',
              customer: 'CUST-002',
              customer_name: 'Bharat Stores',
            },
          ],
        },
      },
    },
  });
  const client = createFrappeApiClient(fake.call);

  const history = await client.orderHistory(undefined, 'SE-001', { limit: 21, offset: 20 });

  assert.deepEqual(
    history.map((order) => order.customer),
    ['CUST-001', 'CUST-002'],
  );
  assert.deepEqual(
    history.map((order) => order.customer_name),
    ['Asha Textiles', 'Bharat Stores'],
  );
  assert.deepEqual(fake.calls[0], {
    verb: 'get',
    method: 'kunal_enterprises.api.orders.history',
    params: {
      customer: undefined,
      sales_employee: 'SE-001',
      limit: 21,
      offset: 20,
    },
  });
});
