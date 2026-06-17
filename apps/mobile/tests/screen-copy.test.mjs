import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { orderHeaderSubtitle, pendingAccessMessage } from '../src/domain/screenCopy.mjs';

function assertNoInternalAccessTerms(text) {
  assert.equal(/client code/i.test(text), false);
  assert.equal(/ledger/i.test(text), false);
}

test('customer-facing access copy hides internal Client Code terminology', () => {
  assertNoInternalAccessTerms(orderHeaderSubtitle({ mode: 'Customer' }));
  assertNoInternalAccessTerms(pendingAccessMessage());
});

test('sales employee customer selection copy explains search without displaying Client Code', () => {
	const subtitle = orderHeaderSubtitle({ mode: 'Sales Employee', selectedCustomer: null });

	assert.match(subtitle, /Select a Customer/);
	assertNoInternalAccessTerms(subtitle);
});

test('sales employee selected customer copy stays concise', () => {
	const subtitle = orderHeaderSubtitle({
		mode: 'Sales Employee',
		selectedCustomer: { customer_name: 'HELLO' },
	});

	assert.equal(subtitle, 'HELLO selected.');
	assert.doesNotMatch(subtitle, /Internal note/i);
});

test('visible mobile UI copy does not mention pricing fields', () => {
	const source = readFileSync(new URL('../app/index.tsx', import.meta.url), 'utf8');
	const visibleCopy = [
		...source.matchAll(/<Text[^>]*>([^<{]+)<\/Text>/g),
		...source.matchAll(/title="([^"]+)"/g),
		...source.matchAll(/detail=\{`([^`]+)`\}/g),
	].map((match) => match[1]);

	for (const copy of visibleCopy) {
		assert.equal(/\b(price|rate|tax|value|amount|discount)\b/i.test(copy), false, copy);
	}
});

test('customer signup screen captures required fields without fixture defaults', () => {
	const source = readFileSync(new URL('../app/index.tsx', import.meta.url), 'utf8');

	for (const label of [
		'Customer Name',
		'Business / Legal Name',
		'GSTIN',
		'Email ID',
		'Date of Birth',
		'Date of Anniversary',
	]) {
		assert.match(source, new RegExp(label.replace('/', '\\/')));
	}

	for (const fixtureValue of ['Asha Textiles', '27ABCDE1234F1Z5', 'asha@example.com']) {
		assert.equal(source.includes(fixtureValue), false, fixtureValue);
	}

	assert.match(source, /customerName: signupCustomerName/);
	assert.match(source, /businessLegalName: signupBusinessLegalName/);
	assert.match(source, /emailId: signupEmailId/);
});
