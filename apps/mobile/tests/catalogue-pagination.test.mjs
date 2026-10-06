import assert from 'node:assert/strict';
import test from 'node:test';
import { mockApi } from '../src/api/mockApi.mjs';

test('catalogue cursors load every item exactly once and retain the full All count under filters', async () => {
  const first = await mockApi.allowedItemsPage('CUSTOMER', undefined, undefined, { limit: 1, offset: 0 });
  assert.ok(first.all_count > 1);
  let page = first;
  const loaded = [...page.items];
  while (page.has_more) {
    assert.equal(page.next_offset, loaded.length);
    page = await mockApi.allowedItemsPage('CUSTOMER', undefined, undefined, { limit: 1, offset: page.next_offset });
    loaded.push(...page.items);
  }
  assert.equal(page.next_offset, null);
  assert.equal(loaded.length, first.total_count);
  assert.equal(new Set(loaded.map(item => item.name)).size, loaded.length);
  const filtered = await mockApi.allowedItemsPage('CUSTOMER', loaded[0].root_stock_group, undefined, { limit: 1 });
  assert.equal(filtered.all_count, first.all_count);
  assert.ok(filtered.total_count <= first.total_count);
});
