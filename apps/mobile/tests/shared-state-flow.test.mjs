import assert from 'node:assert/strict';
import test from 'node:test';

import {
  apiErrorMessage,
  classifyApiFailure,
  detectStockChanges,
  requestBanner,
  requestStateFromTiming,
} from '../src/domain/sharedStateFlow.mjs';

test('request timing distinguishes loading from slow request', () => {
  assert.equal(requestStateFromTiming({ isLoading: true, elapsedMs: 400 }).kind, 'loading');
  assert.equal(requestStateFromTiming({ isLoading: true, elapsedMs: 1800 }).kind, 'slow');
  assert.equal(requestStateFromTiming({ isLoading: false, elapsedMs: 200 }).kind, 'idle');
});

test('api failures classify no network, expired session, access removed, and validation errors', () => {
  assert.equal(classifyApiFailure({ message: 'Network request failed' }).kind, 'no_network');
  assert.equal(classifyApiFailure({ message: 'Invalid or inactive token' }).kind, 'expired_session');
  assert.equal(classifyApiFailure({ message: 'Customer App Access is not active' }).kind, 'access_removed');
  assert.equal(classifyApiFailure({ message: 'Order Quantity must be positive' }).kind, 'validation_error');
});

test('api failures unwrap nested Frappe error messages', () => {
  const failure = classifyApiFailure({
    message: {
      success: false,
      message: 'Unable to verify customer OTP',
      error: { message: 'Invalid or expired OTP Code' },
    },
  });

  assert.equal(failure.kind, 'validation_error');
  assert.equal(failure.message, 'Invalid or expired OTP Code');
  assert.equal(apiErrorMessage({ message: {} }), 'Request failed');
});

test('stock changes since screen load are reported as confirmation notes', () => {
  const changes = detectStockChanges(
    [{ item: 'ITEM-COTTON-001', godown: 'Main Godown', stockShownAtOrderTime: 12 }],
    [{ item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 8 }],
  );

  assert.equal(changes.length, 1);
  assert.match(changes[0], /changed from 12 to 8/);
});

test('state banner gives user-facing labels without exposing internals', () => {
  assert.equal(requestBanner({ kind: 'no_network' }).title, 'No network');
  assert.equal(requestBanner({ kind: 'expired_session' }).action, 'Log in again');
  assert.equal(requestBanner({ kind: 'access_removed' }).title, 'Access changed');
});
