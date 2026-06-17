import assert from 'node:assert/strict';
import test from 'node:test';

import {
  activeIdentityForMode,
  bootstrapStoredSession,
  canUseProtectedMobileApi,
  logoutAndRevokeSession,
  refreshStoredSession,
  restoredSessionRoute,
} from '../src/domain/sessionFlow.mjs';
import { loadSession, saveSession } from '../src/storage/mobileStorage.mjs';

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
  };
}

test('stored mobile session refreshes against backend current session', async () => {
  const storage = memoryStorage();
  await saveSession(storage, {
    accessToken: 'token-123',
    identityType: 'Customer',
    identity: 'CUST-001',
  });
  const calls = [];

  const result = await refreshStoredSession({
    storage,
    currentSession: async (headers) => {
      calls.push(headers);
      return {
        identity_type: 'Customer',
        identity: 'CUST-001',
        customer: 'CUST-001',
      };
    },
  });

  assert.equal(result.valid, true);
  assert.deepEqual(result.session, {
    accessToken: 'token-123',
    identityType: 'Customer',
    identity: 'CUST-001',
  });
  assert.deepEqual(calls, [{ 'Auth-Token': 'Bearer token-123' }]);
});

test('auth bootstrap can validate stored session before exposing it', async () => {
  const storage = memoryStorage();
  await saveSession(storage, {
    accessToken: 'token-123',
    identityType: 'Customer',
    identity: 'CUST-001',
  });
  const updates = [];

  const result = await bootstrapStoredSession({
    storage,
    currentSession: async () => ({ identity: 'CUST-001' }),
    applySession: (session) => updates.push(session),
  });

  assert.equal(result.valid, true);
  assert.equal(updates[0].accessToken, 'token-123');
});

test('auth bootstrap does not expose invalid stored session', async () => {
  const storage = memoryStorage();
  await saveSession(storage, {
    accessToken: 'stale-token',
    identityType: 'Customer',
    identity: 'CUST-001',
  });
  const updates = [];

  const result = await bootstrapStoredSession({
    storage,
    currentSession: async () => {
      throw new Error('Invalid or inactive token');
    },
    applySession: (session) => updates.push(session),
  });

  assert.equal(result.valid, false);
  assert.deepEqual(updates, []);
  assert.equal(await loadSession(storage), null);
});

test('invalid stored mobile session is cleared on refresh failure', async () => {
  const storage = memoryStorage();
  await saveSession(storage, {
    accessToken: 'stale-token',
    identityType: 'Customer',
    identity: 'CUST-001',
  });

  const result = await refreshStoredSession({
    storage,
    currentSession: async () => {
      throw new Error('Invalid or inactive token');
    },
  });

  assert.equal(result.valid, false);
  assert.equal(result.session, null);
  assert.equal(await loadSession(storage), null);
});

test('logout revokes backend token before clearing local session', async () => {
  const storage = memoryStorage();
  await saveSession(storage, {
    accessToken: 'token-123',
    identityType: 'Sales Employee',
    identity: 'SE-001',
  });
  const calls = [];

  await logoutAndRevokeSession({
    storage,
    revokeToken: async (headers) => {
      calls.push(headers);
      return { revoked: true };
    },
  });

  assert.deepEqual(calls, [{ 'Auth-Token': 'Bearer token-123' }]);
  assert.equal(await loadSession(storage), null);
});

test('active identity comes from the stored session for the current mode', () => {
  assert.equal(
    activeIdentityForMode({
      mode: 'Customer',
      session: { identityType: 'Customer', identity: 'CUST-LIVE-001' },
      fallback: 'CUST-001',
    }),
    'CUST-LIVE-001',
  );
  assert.equal(
    activeIdentityForMode({
      mode: 'Sales Employee',
      session: { identityType: 'Sales Employee', identity: 'SE-LIVE-001' },
      fallback: 'SE-001',
    }),
    'SE-LIVE-001',
  );
  assert.equal(
    activeIdentityForMode({
      mode: 'Customer',
      session: { identityType: 'Sales Employee', identity: 'SE-LIVE-001' },
      fallback: 'CUST-001',
    }),
    'CUST-001',
  );
});

test('protected mobile APIs require a session for the active mode', () => {
  assert.equal(canUseProtectedMobileApi({ mode: 'Customer', session: null }), false);
  assert.equal(
    canUseProtectedMobileApi({
      mode: 'Customer',
      session: { identityType: 'Sales Employee', identity: 'SE-001', accessToken: 'token-se' },
    }),
    false,
  );
  assert.equal(
    canUseProtectedMobileApi({
      mode: 'Customer',
      session: { identityType: 'Customer', identity: 'CUST-001', accessToken: 'token-customer' },
    }),
    true,
  );
});

test('restored sessions route directly to the right signed-in screen', () => {
  assert.deepEqual(restoredSessionRoute(null), { mode: 'Customer', step: 'auth' });
  assert.deepEqual(
    restoredSessionRoute({
      identityType: 'Customer',
      identity: 'CUST-001',
      accessToken: 'token-customer',
    }),
    { mode: 'Customer', step: 'groups' },
  );
  assert.deepEqual(
    restoredSessionRoute({
      identityType: 'Sales Employee',
      identity: 'SE-001',
      accessToken: 'token-se',
    }),
    { mode: 'Sales Employee', step: 'customer' },
  );
});
