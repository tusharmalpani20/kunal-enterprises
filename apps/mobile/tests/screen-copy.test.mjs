import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { orderHeaderSubtitle, pendingAccessMessage } from '../src/domain/screenCopy.mjs';

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));

function filesUnder(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? filesUnder(path) : [path];
  });
}

function combinedMobileSource() {
  return filesUnder(join(projectRoot, 'app'))
    .concat(filesUnder(join(projectRoot, 'src')))
    .filter((file) => /\.(mjs|ts|tsx)$/.test(file))
    .map((file) => readFileSync(file, 'utf8'))
    .join('\n');
}

function assertNoInternalAccessTerms(text) {
  assert.equal(/client code/i.test(text), false);
  assert.equal(/ledger/i.test(text), false);
}

test('customer-facing access copy hides internal Client Code terminology', () => {
  assertNoInternalAccessTerms(orderHeaderSubtitle({ mode: 'Customer' }));
  assertNoInternalAccessTerms(pendingAccessMessage());
});

test('sales employee customer selection copy explains search without exposing access terms', () => {
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

test('sales employee customer cards do not display Client Code', () => {
	const source = readFileSync(new URL('../app/(app)/customer.tsx', import.meta.url), 'utf8');

	assert.doesNotMatch(source, /customer\.client_code/);
});

test('visible mobile UI copy does not mention pricing fields', () => {
	const source = combinedMobileSource();
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
	const flowSource = readFileSync(new URL('../src/flow/OrderFlowProvider.tsx', import.meta.url), 'utf8');
	// The signup UI surface: the sign-in route holds the labels/inputs and the
	// provider holds the signup field state + payload construction.
	const uiSource = readFileSync(new URL('../app/(auth)/sign-in.tsx', import.meta.url), 'utf8') + '\n' + flowSource;

	for (const label of [
		'Customer Name',
		'Business / Legal Name',
		'GSTIN',
		'Email ID',
		'Date of Birth',
		'Date of Anniversary',
	]) {
		assert.match(uiSource, new RegExp(label.replace('/', '\\/')));
	}

	for (const fixtureValue of ['Asha Textiles', '27ABCDE1234F1Z5', 'asha@example.com']) {
		assert.equal(uiSource.includes(fixtureValue), false, fixtureValue);
	}

	assert.match(flowSource, /customerName: signupCustomerName/);
	assert.match(flowSource, /businessLegalName: signupBusinessLegalName/);
	assert.match(flowSource, /emailId: signupEmailId/);
});

test('sign-in OTP actions expose a loading state while a request is in flight', () => {
	const signInSource = readFileSync(new URL('../app/(auth)/sign-in.tsx', import.meta.url), 'utf8');
	const flowSource = readFileSync(new URL('../src/flow/OrderFlowProvider.tsx', import.meta.url), 'utf8');

	assert.match(signInSource, /otpRequestLoading/);
	assert.match(signInSource, /otpVerificationLoading/);
	assert.match(signInSource, /disabled=\{otpActionLoading/);
	assert.match(signInSource, /Sending OTP/);
	assert.match(signInSource, /Verifying OTP/);
	assert.match(signInSource, /editable=\{!signupDetailsReadOnly && !otpActionLoading\}/);
	assert.match(signInSource, /disabled=\{signupDetailsReadOnly \|\| otpActionLoading\}/);
	assert.match(flowSource, /otpRequestInFlightRef/);
	assert.match(flowSource, /otpVerificationInFlightRef/);
	assert.match(flowSource, /const \[otpCode, setOtpCode\] = useState\(''\);/);
});
