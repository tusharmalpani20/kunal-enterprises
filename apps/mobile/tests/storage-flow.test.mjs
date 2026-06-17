import assert from 'node:assert/strict';
import test from 'node:test';

import {
  cartKeyForOrderContext,
  cartOwnerKeyForSession,
  clearAllCarts,
  clearCart,
  clearSession,
  ensureCartOwner,
  listSalesEmployeeDraftCarts,
  loadCart,
  loadSession,
  saveCart,
  saveSession,
} from '../src/storage/mobileStorage.mjs';

function memoryStorage() {
  const values = new Map();
  return {
    values,
    async getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    async setItem(key, value) {
      values.set(key, value);
    },
    async removeItem(key) {
      values.delete(key);
    },
    async getAllKeys() {
      return [...values.keys()];
    },
    async multiRemove(keys) {
      keys.forEach((key) => values.delete(key));
    },
  };
}

test('mobile session token is persisted and can be cleared on logout', async () => {
  const storage = memoryStorage();

  await saveSession(storage, {
    accessToken: 'token-123',
    identityType: 'Customer',
    identity: 'CUST-001',
  });

  assert.deepEqual(await loadSession(storage), {
    accessToken: 'token-123',
    identityType: 'Customer',
    identity: 'CUST-001',
  });

  await clearSession(storage);
  assert.equal(await loadSession(storage), null);
});

test('local cart persists quantity-only allocations between app launches', async () => {
  const storage = memoryStorage();
  const cart = [
    {
      item: 'ITEM-COTTON-001',
      itemName: 'Cotton 40s',
      godown: 'Main Godown',
      quantity: 4,
      stockShownAtOrderTime: 12,
      stockSnapshotAt: '2026-05-19 12:05:00',
    },
  ];

  await saveCart(storage, 'Customer:CUST-001', cart);

  assert.deepEqual(await loadCart(storage, 'Customer:CUST-001'), cart);
  assert.deepEqual(await loadCart(storage, 'Sales Employee:SE-001:CUST-001'), []);
});

test('cart storage key is scoped by viewer and selected customer context', () => {
  assert.equal(
    cartKeyForOrderContext({
      mode: 'Customer',
      customer: 'CUST-001',
    }),
    'Customer:CUST-001',
  );
  assert.equal(
    cartKeyForOrderContext({
      mode: 'Sales Employee',
      salesEmployee: 'SE-001',
      selectedCustomer: 'CUST-001',
    }),
    'Sales Employee:SE-001:CUST-001',
  );
  assert.equal(
    cartKeyForOrderContext({
      mode: 'Sales Employee',
      salesEmployee: 'SE-001',
      selectedCustomer: '',
    }),
    null,
  );
});

test('local cart can be cleared after final order placement', async () => {
  const storage = memoryStorage();
  const cartKey = 'Customer:CUST-001';
  await saveCart(storage, cartKey, [
    {
      item: 'ITEM-COTTON-001',
      itemName: 'Cotton 40s',
      godown: 'Main Godown',
      quantity: 4,
      stockShownAtOrderTime: 12,
    },
  ]);

  await clearCart(storage, cartKey);

  assert.deepEqual(await loadCart(storage, cartKey), []);
});

test('cart drafts are preserved only for the same logged-in owner', async () => {
  const storage = memoryStorage();
  const customerOwner = cartOwnerKeyForSession({ identityType: 'Customer', identity: 'CUST-001' });
  const otherOwner = cartOwnerKeyForSession({ identityType: 'Customer', identity: 'CUST-002' });

  assert.equal(customerOwner, 'Customer:CUST-001');
  assert.deepEqual(await ensureCartOwner(storage, customerOwner), { changed: false });
  await saveCart(storage, 'Customer:CUST-001', [{ item: 'ITEM-001', godown: 'Main', quantity: 1 }]);
  assert.equal((await ensureCartOwner(storage, customerOwner)).changed, false);
  assert.equal((await loadCart(storage, 'Customer:CUST-001')).length, 1);

  assert.deepEqual(await ensureCartOwner(storage, otherOwner), { changed: true });
  assert.deepEqual(await loadCart(storage, 'Customer:CUST-001'), []);
});

test('logout can clear every locally saved cart draft', async () => {
  const storage = memoryStorage();
  await saveCart(storage, 'Customer:CUST-001', [{ item: 'ITEM-001', godown: 'Main', quantity: 1 }]);
  await saveCart(storage, 'Sales Employee:SE-001:CUST-001', [{ item: 'ITEM-002', godown: 'Branch', quantity: 2 }]);

  await clearAllCarts(storage);

  assert.deepEqual(await loadCart(storage, 'Customer:CUST-001'), []);
  assert.deepEqual(await loadCart(storage, 'Sales Employee:SE-001:CUST-001'), []);
});

test('sales employee draft carts can be listed by selected customer context', async () => {
  const storage = memoryStorage();
  await saveCart(storage, 'Sales Employee:SE-001:CUST-002', [
    { item: 'ITEM-002', godown: 'Branch', quantity: 2 },
    { item: 'ITEM-003', godown: 'Main', quantity: 3 },
  ]);
  await saveCart(storage, 'Sales Employee:SE-001:CUST-001', [
    { item: 'ITEM-001', godown: 'Main', quantity: 1 },
  ]);
  await saveCart(storage, 'Sales Employee:SE-002:CUST-003', [
    { item: 'ITEM-004', godown: 'Main', quantity: 7 },
  ]);
  await saveCart(storage, 'Customer:CUST-004', [
    { item: 'ITEM-005', godown: 'Main', quantity: 9 },
  ]);

  assert.deepEqual(await listSalesEmployeeDraftCarts(storage, 'SE-001'), [
    { customer: 'CUST-001', rowCount: 1, totalQuantity: 1 },
    { customer: 'CUST-002', rowCount: 2, totalQuantity: 5 },
  ]);
});
