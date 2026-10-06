import test from 'node:test';
import assert from 'node:assert/strict';
import { createMobileApi } from '../src/api/mobileApi.mjs';

test('customer combined feed retains request type and converted source while sales uses legacy feed', async () => {
  const calls = [];
  const api = createMobileApi({ call: {
    get: async (method, params) => {
      calls.push({ method, params });
      return { message: { success: true, data: { orders: [
        { name: 'QOR-1', portal_reference_number: 'QOR-1', entry_type: 'quick_order', quick_order_request: 'QOR-1', status: 'Pending Review' },
        { name: 'ORDER-1', entry_type: 'order', quick_order_request: 'QOR-2', status: 'Placed' },
      ] } } };
    },
  } });
  const rows = await api.orderHistory('CUSTOMER-1', undefined, { includeQuickOrders: true, limit: 21, offset: 20 });
  assert.equal(calls[0].params.include_quick_orders, 1);
  assert.equal(calls[0].params.offset, 20);
  assert.equal(rows[0].entry_type, 'quick_order');
  assert.equal(rows[1].quick_order_request, 'QOR-2');
  await api.orderHistory(undefined, 'SALES-1');
  assert.equal('include_quick_orders' in calls[1].params, false);
});

test('fixture combined feed includes own requests once with shared pagination and isolates customers', async () => {
  const api = createMobileApi({ call: null });
  const request = await api.quickOrderSubmit('Item A, 3', 'CUST-001');
  await api.quickOrderSubmit('Private text', 'OTHER-CUSTOMER');
  const first = await api.orderHistory('CUST-001', undefined, { includeQuickOrders: true, limit: 1 });
  const second = await api.orderHistory('CUST-001', undefined, { includeQuickOrders: true, limit: 1, offset: 1 });
  assert.equal(first[0].name, request.name);
  assert.equal(first[0].entry_type, 'quick_order');
  assert.notEqual(second[0]?.name, request.name);
  assert.equal(first.some(row => row.text === 'Private text'), false);
  const legacy = await api.orderHistory('CUST-001');
  assert.equal(legacy.some(row => row.entry_type === 'quick_order'), false);
});
