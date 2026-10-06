import assert from 'node:assert/strict';
import test from 'node:test';

import { createMobileApi, mobileApiMode } from '../src/api/mobileApi.mjs';

test('mobile api uses fixture adapter when no Frappe call object is available', async () => {
  const api = createMobileApi({ call: null });

  assert.equal(mobileApiMode({ call: null }), 'mock');
  assert.equal((await api.allowedProductGroups('CUST-001')).length > 0, true);
  assert.equal((await api.currentSession({ 'Auth-Token': 'Bearer mock-customer-token' })).identity, 'CUST-001');
  assert.equal((await api.revokeToken({ 'Auth-Token': 'Bearer mock-customer-token' })).revoked, true);
  assert.equal((await api.updateCustomerProfile('CUST-001', { email_id: 'new@example.com' })).email_id, 'new@example.com');
  assert.equal((await api.customerAccessStatus('CUST-001')).customer_app_access, true);
});

test('mobile api uses live Frappe adapter when call object is available', async () => {
  const calls = [];
  const api = createMobileApi({
    call: {
      get: async (method, params) => {
        calls.push({ method, params });
        return {
          message: {
            success: true,
            data: {
              product_groups: [{ name: 'Cotton Fabric', group_name: 'Cotton Fabric', full_path: 'Cotton Fabric', product_group_logo: null }],
            },
          },
        };
      },
    },
  });

  const groups = await api.allowedProductGroups('CUST-001');

  assert.equal(mobileApiMode({ call: {} }), 'live');
  assert.equal(groups[0].name, 'Cotton Fabric');
  assert.equal(calls[0].method, 'kunal_enterprises.api.product_groups.allowed');
});

test('fixture submission preserves mixed optional godown allocations in history and detail', async () => {
  const api = createMobileApi({ call: null });
  const payload = { customer: 'CUST-001', sales_employee: 'SE-001', allocations: [
    { item: 'ITEM-COTTON-001', quantity: 2 },
    { item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 3, stock_shown_at_order_time: 12 },
  ] };
  const result = await api.submitOrder(payload);
  const detail = await api.orderDetail(result.order, { salesEmployee: 'SE-001' });
  assert.equal(detail.status, 'Placed');
  assert.equal(detail.items[0].requested_quantity, 5);
  assert.deepEqual(detail.godown_allocations.map((row) => [row.godown || null, row.requested_quantity]), [[null, 2], ['Main Godown', 3]]);
  const history = await api.orderHistory('CUST-001', 'SE-001');
  assert.equal(history.find((row) => row.name === result.order).total_quantity, 5);
});
