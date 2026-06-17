import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const reactNativeFontWeights = new Set([
  'normal',
  'bold',
  '100',
  '200',
  '300',
  '400',
  '500',
  '600',
  '700',
  '800',
  '900',
]);

test('React Native styles use TypeScript-compatible font weights', () => {
  const source = readFileSync(join(projectRoot, 'app/index.tsx'), 'utf8');
  const invalidWeights = [...source.matchAll(/fontWeight:\s*['"]([^'"]+)['"]/g)]
    .map((match) => match[1])
    .filter((weight) => !reactNativeFontWeights.has(weight));

  assert.deepEqual(invalidWeights, []);
});

test('mobile source only uses the Frappe API boundary, not raw Tally mirror access', () => {
  const sourceFiles = filesUnder(join(projectRoot, 'app'))
    .concat(filesUnder(join(projectRoot, 'src')))
    .filter((file) => /\.(mjs|ts|tsx)$/.test(file));
  const forbiddenPatterns = [
    /\bpostgres(?:ql)?\b/i,
    /\btrn_[a-z0-9_]+\b/i,
    /\brpt_[a-z0-9_]+\b/i,
    /\bfrom\s+['"]pg['"]/,
    /\bfrom\s+['"]postgres['"]/,
    /\bfetch\s*\(/,
    /\bXMLHttpRequest\b/,
  ];
  const violations = sourceFiles.flatMap((file) => {
    const source = readFileSync(file, 'utf8');
    return forbiddenPatterns
      .filter((pattern) => pattern.test(source))
      .map((pattern) => `${file.replace(`${projectRoot}/`, '')}: ${pattern}`);
  });

  assert.deepEqual(violations, []);
});

test('Frappe provider preserves the Goal 3 SDK contract', () => {
  const source = readFileSync(join(projectRoot, 'src/providers/frappe.tsx'), 'utf8');
  for (const phrase of [
    'FrappeApp',
    'FrappeAuth',
    'FrappeCall',
    'FrappeDB',
    'FrappeFileUpload',
    'db: FrappeDB | null',
    'auth: FrappeAuth | null',
    'call: FrappeCall | null',
    'file: FrappeFileUpload | null',
    'useToken: false',
    "type: 'Bearer'",
    "'Auth-Token': `Bearer ${accessToken}`",
    'frappe.axios.interceptors.response.use',
    'Invalid or inactive token',
    'App Update Required',
    'Error verifying token',
    'router.replace',
    'setDb(frappe.db())',
    'setCall(frappe.call())',
    'setAuth(frappe.auth())',
    'setFile(frappe.file())',
    'if (!accessToken)',
    'setDb(null)',
    'setAuth(null)',
    'setFile(null)',
    'function createFrappeApp(accessToken',
    "accessToken\n      ? {",
  ]) {
    assert.match(source, new RegExp(escapeRegExp(phrase)));
  }
});

test('auth provider validates stored sessions through the Frappe SDK by default', () => {
  const source = readFileSync(join(projectRoot, 'src/providers/auth.tsx'), 'utf8');
  for (const phrase of [
    'validateStoredSession = validateStoredMobileSession',
    'FrappeApp',
    'createFrappeApiClient',
    'APP_CONFIG.BASE_URL',
    'return createFrappeApiClient(frappe.call()).currentSession()',
  ]) {
    assert.match(source, new RegExp(escapeRegExp(phrase)));
  }
});

test('sales employee item and stock requests include sales employee context', () => {
  const source = readFileSync(join(projectRoot, 'app/index.tsx'), 'utf8');

  assert.match(source, /catalogApi\.allowedItems\(customer, group\.name, salesEmployee\)/);
  assert.match(source, /api\.itemStock\(activeCustomer\(\), item\.name, activeSalesEmployeeContext\(\)\)/);
  assert.match(source, /api\.itemStock\(activeCustomer\(\), item, activeSalesEmployeeContext\(\)\)/);
  assert.match(source, /function activeSalesEmployeeContext\(\)/);
});

test('customer order screen keeps continuous catalog search, group filters, godown selection, and cart review', () => {
  const source = readFileSync(join(projectRoot, 'app/index.tsx'), 'utf8');

  for (const phrase of [
    'Search products',
    'Product groups',
    'Search item or product group',
    'MAX_VISIBLE_ITEMS',
    'Refine search to narrow results',
    'ItemSearchRow',
    'cartQuantityForItem(cart, item.name)',
    'Godown stock',
    'Back to product search',
    'function BackButton',
    'Review order',
    'Cart is empty',
    'Open carts',
    'Confirm order',
  ]) {
    assert.match(source, new RegExp(escapeRegExp(phrase)));
  }
});

test('mobile package records React Native Reusables CLI without importing missing runtime package', () => {
  const packageJson = JSON.parse(readFileSync(join(projectRoot, 'package.json'), 'utf8'));
  const appSource = readFileSync(join(projectRoot, 'app/index.tsx'), 'utf8');

  assert.equal(packageJson.devDependencies['@react-native-reusables/cli'], '^0.7.1');
  assert.equal(Object.hasOwn(packageJson.dependencies, 'react-native-reusables'), false);
  assert.match(appSource, /from 'react-native';/);
  assert.match(appSource, /from 'lucide-react-native'/);
  assert.match(appSource, /function Workspace/);
  assert.match(appSource, /function RowButton/);
});

function filesUnder(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? filesUnder(path) : [path];
  });
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
