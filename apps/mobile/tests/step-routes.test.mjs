import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { navigationActionForStep, routeForStep, stepForRoute } from '../src/flow/stepRoutes.mjs';

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const STEPS = ['auth', 'pending', 'customer', 'groups', 'summary', 'success', 'history', 'detail', 'profile'];

// Maps the URL each step routes to onto the expo-router file that serves it.
// Route groups (auth)/(app) are not part of the URL, so we resolve them here.
const ROUTE_FILES = {
  '/sign-in': 'app/(auth)/sign-in.tsx',
  '/pending': 'app/(auth)/pending.tsx',
  '/customer': 'app/(app)/customer.tsx',
  '/order': 'app/(app)/order.tsx',
  '/summary': 'app/(app)/summary.tsx',
  '/success': 'app/(app)/success.tsx',
  '/history': 'app/(app)/history.tsx',
  '/detail': 'app/(app)/detail.tsx',
  '/profile': 'app/(app)/profile.tsx',
};

test('every step resolves to a route file that actually exists', () => {
  for (const step of STEPS) {
    const route = routeForStep(step);
    const file = ROUTE_FILES[route];
    assert.ok(file, `no route file mapped for ${step} (${route})`);
    assert.ok(existsSync(join(projectRoot, file)), `missing route file ${file} for step ${step}`);
  }
});

test('every step maps to a route and back to itself', () => {
  for (const step of STEPS) {
    const route = routeForStep(step);
    assert.equal(typeof route, 'string');
    assert.ok(route.startsWith('/'), `route for ${step} should be absolute: ${route}`);
    assert.equal(stepForRoute(route), step, `round trip failed for ${step}`);
  }
});

test('unknown routes resolve to the auth step', () => {
  assert.equal(stepForRoute('/'), 'auth');
  assert.equal(stepForRoute('/nonsense'), 'auth');
});

test('entering or returning to an auth surface replaces the stack', () => {
  // signing out / expired session from anywhere in the app
  assert.equal(navigationActionForStep('groups', 'auth'), 'replace');
  assert.equal(navigationActionForStep('profile', 'pending'), 'replace');
  // bootstrapping straight into pending
  assert.equal(navigationActionForStep('auth', 'pending'), 'replace');
});

test('crossing from the auth surface into the app replaces the stack', () => {
  // sign-in success should not leave the sign-in screen on the back stack
  assert.equal(navigationActionForStep('auth', 'groups'), 'replace');
  assert.equal(navigationActionForStep('auth', 'customer'), 'replace');
});

test('completing an order replaces so it cannot be re-reviewed by going back', () => {
  assert.equal(navigationActionForStep('summary', 'success'), 'replace');
});

test('drilling down within a section pushes a normal back-stack entry', () => {
  assert.equal(navigationActionForStep('groups', 'summary'), 'navigate');
  assert.equal(navigationActionForStep('customer', 'groups'), 'navigate');
  assert.equal(navigationActionForStep('summary', 'groups'), 'navigate');
  assert.equal(navigationActionForStep('history', 'detail'), 'navigate');
});

test('switching between top-level sections replaces instead of stacking (tab behavior)', () => {
  // Order ↔ History ↔ Profile are tabs, not a drill-down stack
  assert.equal(navigationActionForStep('groups', 'history'), 'replace');
  assert.equal(navigationActionForStep('groups', 'profile'), 'replace');
  assert.equal(navigationActionForStep('profile', 'groups'), 'replace');
  assert.equal(navigationActionForStep('history', 'profile'), 'replace');
  // Even when switching tabs from a drilled-in screen
  assert.equal(navigationActionForStep('summary', 'history'), 'replace');
  assert.equal(navigationActionForStep('detail', 'groups'), 'replace');
});
