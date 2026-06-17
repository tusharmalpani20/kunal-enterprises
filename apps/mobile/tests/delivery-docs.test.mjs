import assert from 'node:assert/strict';
import { readFileSync, statSync } from 'node:fs';
import test from 'node:test';

const deliveryAudit = readFileSync(new URL('../../../docs/11-delivery-audit.md', import.meta.url), 'utf8');
const rootReadme = readFileSync(new URL('../../../README.md', import.meta.url), 'utf8');
const backendReadme = readFileSync(new URL('../../../apps/kunal_enterprises/README.md', import.meta.url), 'utf8');
const verifyLocalScript = readFileSync(new URL('../../../scripts/verify-local.sh', import.meta.url), 'utf8');
const foundationDoc = readFileSync(new URL('../../../docs/08-local-frappe-foundation.md', import.meta.url), 'utf8');
const backendApiDoc = readFileSync(new URL('../../../docs/10-backend-api.md', import.meta.url), 'utf8');
const readinessChecklist = readFileSync(
	new URL('../../../docs/12-operational-readiness-checklist.md', import.meta.url),
	'utf8',
);
const mobileUiCoverage = readFileSync(new URL('../../../docs/13-mobile-ui-coverage.md', import.meta.url), 'utf8');
const mobileComponentConvention = readFileSync(
	new URL('../../../docs/14-mobile-component-convention.md', import.meta.url),
	'utf8',
);
const tallyPilotTemplate = readFileSync(
	new URL('../../../docs/15-tally-pilot-evidence-template.md', import.meta.url),
	'utf8',
);
const productionPilotSignoff = readFileSync(
	new URL('../../../docs/16-production-pilot-signoff.md', import.meta.url),
	'utf8',
);
const goalCompletionMatrix = readFileSync(
	new URL('../../../docs/17-goal-completion-matrix.md', import.meta.url),
	'utf8',
);

test('delivery audit documents required backend handoff evidence', () => {
	for (const phrase of [
		'Complete portal/backend implementation',
		'Order permission query hooks',
		'Local Frappe runtime',
		'HTTP/1.1 200 OK',
		'Passing test suite',
		'Ran 86 tests',
		'frappe.local.response\\["http_status_code"\\]',
		'API documentation',
		'Fixture and migration documentation',
		'Scheduler and manual job documentation',
		'Tally reference field proof',
		'Main Location mapping',
		'Seetarambagh mapping',
		'exact customer ledger filter',
		'godown-wise stock snapshot validation',
		'WhatsApp provider credentials',
		'production pilot sign-off',
	]) {
		assert.match(deliveryAudit, new RegExp(phrase, 'i'));
	}
});

test('root README documents both apps, verified commands, and release follow-up scope', () => {
	for (const phrase of [
		'goal/README.md',
		'apps/kunal_enterprises',
		'apps/mobile',
		'custom Frappe backend',
		'Expo / React Native app',
		'never reads Tally or the raw Tally PostgreSQL mirror',
		'/Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench',
		'kunal_enterprises.api.health.smoke',
		'run-tests --app kunal_enterprises',
		'bench serve --port 8000',
		'npm test',
		'npm run typecheck',
		'./scripts/verify-local.sh',
		'npx expo start --localhost --port 8081',
		'EXPO_PUBLIC_FRAPPE_BASE_URL=http://127.0.0.1:8000',
		'Mobile tests: `npm test` passes `103` tests',
		'docs/11-delivery-audit.md',
		'docs/16-production-pilot-signoff.md',
		'docs/17-goal-completion-matrix.md',
		'optional release/operations follow-up artifacts',
		'not blockers for the build goal',
	]) {
		assert.match(rootReadme, new RegExp(phrase, 'i'));
	}
});

test('local verification script reruns backend and mobile checks', () => {
	assert.equal((statSync(new URL('../../../scripts/verify-local.sh', import.meta.url)).mode & 0o111) !== 0, true);
	for (const phrase of [
		'set -euo pipefail',
		'BENCH_DIR="/Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench"',
		'SITE_NAME="kunal.localhost"',
		'execute kunal_enterprises.api.health.smoke',
		'run-tests --app kunal_enterprises',
		'npm audit --omit=dev',
		'npm test',
		'npm run typecheck',
	]) {
		assert.match(verifyLocalScript, new RegExp(phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'));
	}
	assert.match(rootReadme, /\.\/scripts\/verify-local\.sh/);
	assert.match(deliveryAudit, /\.\/scripts\/verify-local\.sh/);
	assert.match(goalCompletionMatrix, /scripts\/verify-local\.sh/);
});

test('backend app README documents app-specific bench handoff', () => {
	for (const phrase of [
		'Kunal Enterprises Frappe App',
		'Customer signup',
		'Sales Employee OTP login',
		'Product Group, item, godown stock, order submission',
		'Quantity-only Orders',
		'Tally master, stock snapshot, voucher sync entry points',
		'must not read the raw Tally PostgreSQL mirror',
		'/Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench',
		'/Volumes/a909SSD/Development/Kunal-Enterprises/ke-frappe-bench/apps/kunal_enterprises -> /Volumes/a909SSD/Development/Kunal-Enterprises/kunal-enterprises/apps/kunal_enterprises',
		'bench --site kunal.localhost migrate',
		'kunal_enterprises.api.health.smoke',
		'run-tests --app kunal_enterprises',
		'bench serve --port 8000',
		'Installed apps: `frappe`, `kunal_enterprises`, `frappe_whatsapp`',
		'Ran 86 tests',
		'docs/10-backend-api.md',
		'docs/16-production-pilot-signoff.md',
	]) {
		assert.match(backendReadme, new RegExp(phrase, 'i'));
	}
});

test('goal completion matrix maps prompts to evidence and optional follow-up', () => {
	for (const phrase of [
		'Goal Completion Matrix',
		'goal/README.md',
		'Goal 1 Frappe foundation',
		'Goal 2 Frappe portal/backend API',
		'Goal 3 Expo mobile app',
		'Production pilot',
		'Tally/WhatsApp live proof',
		'bench --site kunal.localhost execute kunal_enterprises.api.health.smoke',
		'Backend suite passes `Ran 86 tests` / `OK`',
		'API response envelopes and HTTP status codes',
		'npx expo start --localhost --port 8081',
		'npm test` passes `103` tests',
		'npm audit --omit=dev` reports `found 0 vulnerabilities`',
		'Optional Release Follow-Up',
		'Production pilot sign-off',
		'Tally portal reference field proof',
		'WhatsApp provider proof',
		'Tally/WhatsApp operational proof is excluded from this goal',
		'build goal is complete',
	]) {
		assert.match(goalCompletionMatrix, new RegExp(phrase, 'i'));
	}
	assert.match(deliveryAudit, /docs\/17-goal-completion-matrix\.md/);
});

test('foundation documentation includes current local server response evidence', () => {
	for (const phrase of [
		'bench serve --port 8000',
		'curl -I http://127.0.0.1:8000',
		'HTTP/1.1 200 OK',
		'X-Page-Name: login',
		'frappe 15.103.3',
		'frappe_whatsapp 1.0.7',
	]) {
		assert.match(foundationDoc, new RegExp(phrase, 'i'));
	}
});

test('delivery audit documents required mobile handoff evidence', () => {
	for (const phrase of [
		'Runnable Expo mobile app',
		'UI screen coverage',
		'Mobile component convention',
		'Expo launch instructions',
		'Mobile test results',
		'passed `103` tests',
		'Backend environment configuration',
		'remaining operational setup assumptions',
		'npm run typecheck',
		'tsc --noEmit` passed',
		'Metro `Metro waiting on exp://127.0.0.1:8081`',
		'HTTP/1.1 200 OK` from `http://127.0.0.1:8081',
	]) {
		assert.match(deliveryAudit, new RegExp(phrase, 'i'));
	}
});

test('delivery audit maps goal prompts to acceptance coverage', () => {
	for (const phrase of [
		'Acceptance Coverage',
		'01-install-frappe-and-run.md',
		'test_smoke_reports_postgres_and_required_apps',
		'02-build-frappe-portal-and-backend-api.md',
		'Portal Branch `User Permission`',
		'Manual Review reason codes',
		'03-build-mobile-app.md',
		'Customer signup form fields without fixture defaults',
		'Customer signup required-field validation',
		'backend OTP resend after cooldown scoped to the same auth identity',
		'invalid order quantity validation before cart insertion',
		'protected API gating until the active mode has a valid session',
		'Product Group/item/stock filtering through the selected Customer plus Sales Employee API context',
		'godown stock ordering and sync timestamp display',
		'Frappe SDK handle cleanup without access token',
		'blocks raw Tally mirror access',
	]) {
		assert.match(deliveryAudit, new RegExp(phrase, 'i'));
	}
});

test('backend API documentation covers Goal 2 request response and scheduler scope', () => {
	for (const phrase of [
		'Response Envelope',
		'"http_status_code": 200',
		'Validation/business-rule errors return `400`',
		'Auth-Token: Bearer <access_token>',
		'guest-whitelisted',
		'without Desk login',
		'Start Customer Signup',
		'Verify Customer OTP',
		'Allowed Customers',
		'Allowed Product Groups',
		'Submit Order',
		'Customer order request',
		'Sales Employee order request',
		'Order History',
		'Order Detail',
		'Get Profile',
		'Update Customer Profile',
		'Branch Visible Orders',
		'not trusted as proof of authorization',
		'current Frappe session user',
		'for_value = branch',
		'Branch Employee Mark Processing',
		'Cancel Order',
		'Partially Close Order',
		'Resolve Manual Review',
		'Sync Masters Now',
		'Sync Stock Now',
		'Sync Vouchers Now',
		'Run Reconciliation Now',
		'Scheduler Entry Points',
		'kunal_enterprises.cron.tally_sync.sync_tally_masters',
		'kunal_enterprises.cron.tally_sync.sync_stock_snapshots',
		'kunal_enterprises.cron.tally_sync.sync_tally_vouchers',
		'kunal_enterprises.cron.reconciliation.run_reconciliation',
		'CUSTOMER_CLIENT_CODE_MISMATCH',
		'EXTRA_VOUCHER_ITEM',
		'OVER_FULFILLMENT',
		'AMBIGUOUS_DUPLICATE_MOVEMENT',
	]) {
		assert.match(backendApiDoc, new RegExp(phrase, 'i'));
	}
});

test('operational readiness checklist defines evidence required to close external Tally gates', () => {
	for (const phrase of [
		'Required Confirmations',
		'Tally portal reference field',
		'trn_voucher.reference_number',
		'System action after confirmation',
		'Main Location branch mapping',
		'Seetarambagh interpretation',
		'Customer ledger import filter',
		'Customer.client_code = mst_ledger.alias',
		'Godown-wise stock snapshot',
		'Tally-computed stock-by-godown snapshot',
		'WhatsApp provider credentials',
		'Pilot Gate',
		'Production Gate',
	]) {
		assert.match(readinessChecklist, new RegExp(phrase, 'i'));
	}
	assert.match(deliveryAudit, /docs\/12-operational-readiness-checklist\.md/);
	assert.match(readinessChecklist, /docs\/15-tally-pilot-evidence-template\.md/);
	assert.match(deliveryAudit, /docs\/15-tally-pilot-evidence-template\.md/);
});

test('production pilot sign-off template covers optional release evidence', () => {
	for (const phrase of [
		'Production Pilot Sign-Off',
		'optional document',
		'optional Tally and WhatsApp operational proof checklist',
		'Pilot Metadata',
		'Preflight Evidence',
		'Backend migration completed on target site',
		'Mobile app points to target Frappe base URL',
		'Pilot Customers have active Customer App Access',
		'Customer Flow Evidence',
		'Customer signup submits name, business/legal name, GSTIN, mobile number, email ID, date of birth, and date of anniversary',
		'Final Customer order submit',
		'Sales Employee Flow Evidence',
		'Customer search by name/business name/Client Code',
		'Results reflect selected Customer plus Sales Employee effective access',
		'Failure-State Evidence',
		'No network or backend unavailable during final submit',
		'Expired or invalid token',
		'Stock changed since screen loaded',
		'Final Decision',
		'Accept for controlled production use',
		'not a blocker for the current build goal',
	]) {
		assert.match(productionPilotSignoff, new RegExp(phrase, 'i'));
	}
	assert.match(deliveryAudit, /docs\/16-production-pilot-signoff\.md/);
});

test('Tally pilot evidence template includes SQL capture steps and production sign-off gates', () => {
	for (const phrase of [
		'Tally Pilot Evidence Template',
		'Pilot Run Metadata',
		'Portal Reference Field Proof',
		'from trn_voucher',
		'where reference_number =',
		'Voucher Line Match Proof',
		'join trn_inventory',
		'Customer Ledger Filter Proof',
		'from mst_ledger',
		'Godown And Branch Mapping Proof',
		'from mst_godown',
		'Godown-Wise Stock Snapshot Proof',
		'rpt_stock_godown_balance',
		'WhatsApp Provider Proof',
		'"tabMobile OTP"',
		'"tabOrder WhatsApp Notification"',
		'Production Sign-Off',
	]) {
		assert.match(tallyPilotTemplate, new RegExp(phrase, 'i'));
	}
});

test('mobile UI coverage maps Goal 3 screens and shared states to implementation', () => {
	for (const phrase of [
		'Mobile UI Coverage',
		'apps/mobile/app/index.tsx',
		'Customer Screens',
		'Login/signup entry',
		'Login/Signup selector',
		'Customer signup',
		'Existing Customer OTP login',
		'api.startCustomerOtp',
		'Pending approval/access',
		'Product Group list',
		'Item list/search',
		'Item stock by godown',
		'Cart/order summary',
		'Order success',
		'Order history',
		'Order detail/status',
		'Profile',
		'Sales Employee Screens',
		'Customer selection/search',
		'Optional internal note',
		'Sales Employee order history',
		'Read-only profile',
		'Shared States',
		'No network',
		'Expired/invalid session',
		'Disabled/access removed',
		'Backend validation error',
		'Stock changed since screen loaded',
		'Order submission failure',
	]) {
		assert.match(mobileUiCoverage, new RegExp(phrase, 'i'));
	}
	assert.match(deliveryAudit, /docs\/13-mobile-ui-coverage\.md/);
});

test('mobile component convention documents React Native Reusables exception and local primitives', () => {
	for (const phrase of [
		'Mobile Component Convention',
		'react-native-reusables',
		'not available as a published runtime package',
		'@react-native-reusables/cli',
		'React Native primitives',
		'lucide-react-native',
		'Workspace',
		'RowButton',
		'Pressable',
		'TextInput',
		'package.json',
	]) {
		assert.match(mobileComponentConvention, new RegExp(phrase, 'i'));
	}
	assert.match(mobileUiCoverage, /docs\/14-mobile-component-convention\.md/);
	assert.match(deliveryAudit, /docs\/14-mobile-component-convention\.md/);
});
