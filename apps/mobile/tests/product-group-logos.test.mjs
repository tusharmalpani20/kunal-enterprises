import assert from 'node:assert/strict';
import test from 'node:test';

import {
  logoForGroup,
  logoForItem,
  productGroupLogoMap,
  resolveFrappeFileUrl,
} from '../src/domain/mobileFlow.mjs';
import { mockApi } from '../src/api/mockApi.mjs';

const groupsWithLogos = [
  { name: 'Cotton Fabric', group_name: 'Cotton Fabric', full_path: 'Cotton Fabric', product_group_logo: '/files/cotton_fabric_logo.jpeg' },
  { name: 'Lining', group_name: 'Lining', full_path: 'Lining', product_group_logo: null },
  { name: 'Silk', group_name: 'Silk', full_path: 'Silk', product_group_logo: '' },
  { name: 'Wool', group_name: 'Wool', full_path: 'Wool', product_group_logo: 'https://cdn.example.com/wool.png' },
];

test('productGroupLogoMap skips null and empty logos, keeps valid URLs', () => {
  const map = productGroupLogoMap(groupsWithLogos);
  assert.equal(map.size, 2);
  assert.equal(map.has('Cotton Fabric'), true);
  assert.equal(map.has('Wool'), true);
  assert.equal(map.has('Lining'), false);
  assert.equal(map.has('Silk'), false);
});

test('logoForGroup returns null for roots without a logo or unknown roots', () => {
  assert.equal(logoForGroup(groupsWithLogos, 'Cotton Fabric'), '/files/cotton_fabric_logo.jpeg');
  assert.equal(logoForGroup(groupsWithLogos, 'Wool'), 'https://cdn.example.com/wool.png');
  assert.equal(logoForGroup(groupsWithLogos, 'Lining'), null);
  assert.equal(logoForGroup(groupsWithLogos, 'Silk'), null);
  assert.equal(logoForGroup(groupsWithLogos, 'Unknown'), null);
});

test('logoForGroup accepts a prebuilt map', () => {
  const map = productGroupLogoMap(groupsWithLogos);
  assert.equal(logoForGroup(map, 'Cotton Fabric'), '/files/cotton_fabric_logo.jpeg');
  assert.equal(logoForGroup(map, 'Lining'), null);
});

test('logoForItem resolves via root_stock_group and returns null when root has no logo', () => {
  const itemWithLogo = { name: 'ITEM-COTTON-001', item_name: 'Cotton 40s', root_stock_group: 'Cotton Fabric', uom: 'PCS', total_closing_balance: 12 };
  const itemWithoutLogo = { name: 'ITEM-LINING-001', item_name: 'Plain Lining', root_stock_group: 'Lining', uom: 'PCS', total_closing_balance: 0 };
  const itemUnknownRoot = { name: 'ITEM-X', item_name: 'X', root_stock_group: 'Unknown', uom: 'PCS', total_closing_balance: 0 };
  const itemNoRoot = { name: 'ITEM-Y', item_name: 'Y', root_stock_group: '', uom: 'PCS', total_closing_balance: 0 };

  assert.equal(logoForItem(groupsWithLogos, itemWithLogo), '/files/cotton_fabric_logo.jpeg');
  assert.equal(logoForItem(groupsWithLogos, itemWithoutLogo), null);
  assert.equal(logoForItem(groupsWithLogos, itemUnknownRoot), null);
  assert.equal(logoForItem(groupsWithLogos, itemNoRoot), null);
  assert.equal(logoForItem(groupsWithLogos, null), null);
});

test('resolveFrappeFileUrl handles null, empty, relative, and absolute paths', () => {
  const base = 'https://ke-dev.hopnet.co.in';
  assert.equal(resolveFrappeFileUrl(null, base), null);
  assert.equal(resolveFrappeFileUrl('', base), null);
  assert.equal(resolveFrappeFileUrl('   ', base), null);
  assert.equal(resolveFrappeFileUrl('/files/cotton_fabric_logo.jpeg', base), 'https://ke-dev.hopnet.co.in/files/cotton_fabric_logo.jpeg');
  assert.equal(resolveFrappeFileUrl('files/x.jpeg', base), 'https://ke-dev.hopnet.co.in/files/x.jpeg');
  assert.equal(resolveFrappeFileUrl('https://cdn.example.com/wool.png', base), 'https://cdn.example.com/wool.png');
  assert.equal(resolveFrappeFileUrl('http://cdn.example.com/wool.png', base), 'http://cdn.example.com/wool.png');
});

test('resolveFrappeFileUrl returns the raw path when baseUrl is omitted', () => {
  assert.equal(resolveFrappeFileUrl('/files/cotton_fabric_logo.jpeg'), '/files/cotton_fabric_logo.jpeg');
  assert.equal(resolveFrappeFileUrl('https://cdn.example.com/wool.png'), 'https://cdn.example.com/wool.png');
  assert.equal(resolveFrappeFileUrl(null), null);
});

test('mock allowedProductGroups returns one group with a logo URL and one with null', async () => {
  const groups = await mockApi.allowedProductGroups('CUST-001');
  assert.equal(groups.length, 2);
  const cotton = groups.find((g) => g.name === 'Cotton Fabric');
  const lining = groups.find((g) => g.name === 'Lining');
  assert.equal(cotton.product_group_logo, '/files/cotton_fabric_logo.jpeg');
  assert.equal(lining.product_group_logo, null);
});

test('mock item logo resolves through root_stock_group to the group logo', async () => {
  const groups = await mockApi.allowedProductGroups('CUST-001');
  const items = await mockApi.allowedItems('CUST-001', 'Cotton Fabric');
  assert.equal(items.length > 0, true);
  assert.equal(logoForItem(groups, items[0]), '/files/cotton_fabric_logo.jpeg');
});
