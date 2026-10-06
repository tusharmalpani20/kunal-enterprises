import assert from 'node:assert/strict';
import test from 'node:test';
import { canUseQuickOrders, createQuickOrderSubmitter, loadQuickOrderLinkedOrder, quickOrderTextForSubmit } from '../src/domain/quickOrderFlow.mjs';
import { mockApi } from '../src/api/mockApi.mjs';
import { createFrappeApiClient } from '../src/api/frappeClient.mjs';

test('quick orders are available only to verified customer sessions', () => {
  const session = { identityType: 'Customer', identity: 'CUST-1', accessToken: 'customer-token' };
  assert.equal(canUseQuickOrders({ mode: 'Customer', session }), true);
  assert.equal(canUseQuickOrders({ mode: 'Sales Employee', session }), false);
  assert.equal(canUseQuickOrders({ mode: 'Customer', session: { identityType: 'Sales Employee', accessToken: 'sales-token' } }), false);
  assert.equal(canUseQuickOrders({ mode: 'Customer', session: null }), false);
});

test('quick order text keeps meaningful multiline text and rejects empty or excessive requests', () => {
  assert.equal(quickOrderTextForSubmit('  2 cotton rolls\n3 lining rolls  '), '2 cotton rolls\n3 lining rolls');
  assert.throws(() => quickOrderTextForSubmit(' \n '), /Describe/);
  assert.throws(() => quickOrderTextForSubmit('x'.repeat(5001)), /5000/);
});

test('concurrent quick order taps submit once and failures allow retry without fabricated success', async () => {
  let resolve;
  let calls = 0;
  const submit = createQuickOrderSubmitter(async (text) => {
    calls++;
    assert.equal(text, '2 rolls');
    return new Promise((done) => { resolve = done; });
  });
  const first = submit('2 rolls');
  assert.equal(await submit('2 rolls'), null);
  assert.equal(calls, 1);
  resolve({ name: 'QO-1', status: 'Pending Review' });
  assert.equal((await first).name, 'QO-1');
  let attempts = 0;
  const retry = createQuickOrderSubmitter(async () => {
    if (!attempts++) throw new Error('Network request failed');
    return { name: 'QO-2' };
  });
  await assert.rejects(retry('2 rolls'), /Network/);
  assert.equal((await retry('2 rolls')).name, 'QO-2');
});

test('live quick order adapter preserves review statuses and linked order while using customer scope', async () => {
  const calls = [];
  const request = { name: 'QO-1', text: '2 cotton rolls', status: 'Converted to Order', order: 'ORDER-1', portal_reference_number: 'KE-SO-1' };
  const api = createFrappeApiClient({
    post: async (method, params) => { calls.push({ method, params }); return { message: { success: true, data: request } }; },
    get: async (method, params) => { calls.push({ method, params }); return { message: { success: true, data: method.endsWith('.history') ? { requests: [request], has_more: false, next_offset: 1 } : request } }; },
  });
  assert.equal((await api.quickOrderSubmit('2 cotton rolls', 'CUST-1')).name, 'QO-1');
  assert.equal((await api.quickOrderHistory('CUST-1', { limit: 20, offset: 0 })).requests[0].status, 'Converted to Order');
  assert.equal((await api.quickOrderDetail('QO-1', 'CUST-1')).order, 'ORDER-1');
  assert.deepEqual(calls, [
    { method: 'kunal_enterprises.api.quick_orders.submit', params: { text: '2 cotton rolls', customer: 'CUST-1' } },
    { method: 'kunal_enterprises.api.quick_orders.history', params: { customer: 'CUST-1', limit: 20, offset: 0 } },
    { method: 'kunal_enterprises.api.quick_orders.detail', params: { request: 'QO-1', customer: 'CUST-1' } },
  ]);
});


test('fixture quick order history and detail preserve original text and customer ownership', async () => {
  const request = await mockApi.quickOrderSubmit('2 rolls\nCall before dispatch', 'CUST-QUICK-1');
  assert.equal(request.status, 'Pending Review');
  const history = await mockApi.quickOrderHistory('CUST-QUICK-1', { limit: 20, offset: 0 });
  assert.deepEqual(history.requests.map((row) => row.name), [request.name]);
  assert.equal(history.has_more, false);
  assert.equal((await mockApi.quickOrderDetail(request.name, 'CUST-QUICK-1')).text, '2 rolls\nCall before dispatch');
  assert.deepEqual((await mockApi.quickOrderHistory('CUST-OTHER')).requests, []);
  await assert.rejects(mockApi.quickOrderDetail(request.name, 'CUST-OTHER'), /not found/);
});

test('fixture quick order pagination returns remaining requests once and ends with a null offset', async () => {
  for (let index = 0; index < 21; index++) await mockApi.quickOrderSubmit(`${index + 1} rolls`, 'CUST-QUICK-PAGES');
  const first = await mockApi.quickOrderHistory('CUST-QUICK-PAGES', { limit: 20, offset: 0 });
  assert.equal(first.requests.length, 20);
  assert.equal(first.has_more, true);
  assert.equal(first.next_offset, 20);
  const second = await mockApi.quickOrderHistory('CUST-QUICK-PAGES', { limit: 20, offset: first.next_offset });
  assert.equal(second.requests.length, 1);
  assert.equal(second.has_more, false);
  assert.equal(second.next_offset, null);
  assert.equal(new Set([...first.requests, ...second.requests].map((row) => row.name)).size, 21);
});

test('quick order access requires a customer identity as well as a token', () => {
  assert.equal(canUseQuickOrders({ mode: 'Customer', session: { identityType: 'Customer', accessToken: 'token' } }), false);
});


test('linked order results and errors are discarded after leaving the account or request screen', async () => {
  let resolve;
  let current = true;
  const pending = loadQuickOrderLinkedOrder({ order: 'ORDER-1', customer: 'CUST-1',
    loadOrder: async (order, options) => {
      assert.equal(order, 'ORDER-1');
      assert.deepEqual(options, { customer: 'CUST-1' });
      return new Promise((done) => { resolve = done; });
    }, isCurrent: () => current });
  current = false;
  resolve({ name: 'ORDER-1', customer: 'CUST-1' });
  assert.equal(await pending, null);
  assert.equal(await loadQuickOrderLinkedOrder({ order: 'ORDER-1', customer: 'CUST-1',
    loadOrder: async () => { throw new Error('Invalid or inactive token'); }, isCurrent: () => false }), null);
  await assert.rejects(loadQuickOrderLinkedOrder({ order: 'ORDER-1', customer: 'CUST-1',
    loadOrder: async () => { throw new Error('Network request failed'); }, isCurrent: () => true }), /Network/);
  assert.deepEqual(await loadQuickOrderLinkedOrder({ order: 'ORDER-1', customer: 'CUST-1',
    loadOrder: async () => ({ name: 'ORDER-1' }), isCurrent: () => true }), { name: 'ORDER-1' });
});
