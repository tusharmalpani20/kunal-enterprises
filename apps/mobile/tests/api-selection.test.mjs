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
              product_groups: [{ name: 'Cotton Fabric', group_name: 'Cotton Fabric', full_path: 'Cotton Fabric' }],
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
