import assert from 'node:assert/strict';
import test from 'node:test';

import {
  addAllocation,
  buildConfirmationNotes,
  buildCustomerOrderPayload,
  customerOrderGuard,
  finalizeOrderSubmission,
  formatSyncTimestampForMobile,
  groupCartByProductGroup,
  mobileDisplayStatus,
  orderTotals,
  parseOrderQuantityInput,
  prepareStockReviewBeforeSubmit,
  removeAllocation,
  searchItemsForMobile,
  sortGodownStockForMobile,
  stockRowDetailForMobile,
  stockRefreshItemsForCart,
  stockReviewAfterRefresh,
  updateAllocationQuantity,
} from '../src/domain/mobileFlow.mjs';

test('customer order flow merges duplicate item and godown allocations', () => {
  const firstCart = addAllocation([], {
    item: 'ITEM-COTTON-001',
    itemName: 'Cotton 40s',
    godown: 'Main Godown',
    quantity: 5,
    stockShownAtOrderTime: 12,
    stockSnapshotAt: '2026-05-19 12:05:00',
  });
  const cart = addAllocation(firstCart, {
    item: 'ITEM-COTTON-001',
    itemName: 'Cotton 40s',
    godown: 'Main Godown',
    quantity: 7,
    stockShownAtOrderTime: 12,
    stockSnapshotAt: '2026-05-19 12:05:00',
  });

  assert.equal(cart.length, 1);
  assert.deepEqual(orderTotals(cart), { rowCount: 1, totalQuantity: 12 });
});

test('cart quantities can be edited and godown allocations removed', () => {
  const cart = [
    {
      item: 'ITEM-COTTON-001',
      itemName: 'Cotton 40s',
      godown: 'Main Godown',
      quantity: 5,
      stockShownAtOrderTime: 12,
    },
    {
      item: 'ITEM-COTTON-001',
      itemName: 'Cotton 40s',
      godown: 'Zero Godown',
      quantity: 2,
      stockShownAtOrderTime: 0,
    },
  ];

  const edited = updateAllocationQuantity(cart, {
    item: 'ITEM-COTTON-001',
    godown: 'Main Godown',
    quantity: 9,
  });
  const removed = removeAllocation(edited, {
    item: 'ITEM-COTTON-001',
    godown: 'Zero Godown',
  });

  assert.deepEqual(orderTotals(edited), { rowCount: 2, totalQuantity: 11 });
  assert.deepEqual(orderTotals(removed), { rowCount: 1, totalQuantity: 9 });
  assert.equal(removed[0].godown, 'Main Godown');
  assert.throws(
    () => updateAllocationQuantity(cart, { item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 0 }),
    /Order Quantity must be positive/,
  );
});

test('cart summary groups items by backend mobile summary group when present', () => {
  const grouped = groupCartByProductGroup(
    [
      { item: 'ITEM-ALISHAN-001', itemName: 'Alishan Ply', godown: 'Goshamahal', quantity: 1 },
      { item: 'ITEM-FLEXI-001', itemName: 'Flexi Ply', godown: 'Goshamahal', quantity: 2 },
    ],
    [
      {
        name: 'ITEM-ALISHAN-001',
        item_name: 'Alishan Ply',
        root_stock_group: 'KE STOCK',
        mobile_summary_group: 'ALISHAN',
        mobile_summary_group_name: 'ALISHAN',
        mobile_summary_group_logo: '/files/alishan.png',
      },
      {
        name: 'ITEM-FLEXI-001',
        item_name: 'Flexi Ply',
        root_stock_group: 'KE STOCK',
      },
    ],
    new Map([['KE STOCK', '/files/ke.png']]),
  );

  assert.deepEqual(
    grouped.map((group) => ({
      name: group.groupName,
      logo: group.groupLogo,
      items: group.rows.map((row) => row.item),
    })),
    [
      { name: 'ALISHAN', logo: '/files/alishan.png', items: ['ITEM-ALISHAN-001'] },
      { name: 'KE STOCK', logo: '/files/ke.png', items: ['ITEM-FLEXI-001'] },
    ],
  );
});

test('order quantity input returns recoverable validation state before adding to cart', () => {
  assert.deepEqual(parseOrderQuantityInput(''), {
    ok: false,
    quantity: 0,
    state: { kind: 'validation_error', message: 'Order Quantity must be positive.' },
  });
  assert.deepEqual(parseOrderQuantityInput('0'), {
    ok: false,
    quantity: 0,
    state: { kind: 'validation_error', message: 'Order Quantity must be positive.' },
  });
  assert.deepEqual(parseOrderQuantityInput('3.5'), {
    ok: true,
    quantity: 3.5,
    state: { kind: 'idle' },
  });
});

test('removing an item removes all godown allocations for that item', () => {
  const cart = [
    { item: 'ITEM-COTTON-001', itemName: 'Cotton 40s', godown: 'Main Godown', quantity: 5 },
    { item: 'ITEM-COTTON-001', itemName: 'Cotton 40s', godown: 'Zero Godown', quantity: 2 },
    { item: 'ITEM-LINING-001', itemName: 'Plain Lining', godown: 'Main Godown', quantity: 1 },
  ];

  const nextCart = removeAllocation(cart, { item: 'ITEM-COTTON-001' });

  assert.deepEqual(nextCart.map((row) => row.item), ['ITEM-LINING-001']);
});

test('confirmation notes are soft warnings for over-stock and zero-stock requests', () => {
  const cart = [
    {
      item: 'ITEM-COTTON-001',
      itemName: 'Cotton 40s',
      godown: 'Main Godown',
      quantity: 14,
      stockShownAtOrderTime: 12,
    },
    {
      item: 'ITEM-COTTON-001',
      itemName: 'Cotton 40s',
      godown: 'Zero Godown',
      quantity: 1,
      stockShownAtOrderTime: 0,
    },
  ];

  const notes = buildConfirmationNotes(cart);

  assert.equal(notes.length, 2);
  assert.match(notes[0], /exceeds latest synced stock/);
  assert.match(notes[1], /zero latest synced stock/);
});

test('confirmation notes include stock changes since the godown screen loaded', () => {
  const notes = buildConfirmationNotes(
    [
      {
        item: 'ITEM-COTTON-001',
        itemName: 'Cotton 40s',
        godown: 'Main Godown',
        quantity: 4,
        stockShownAtOrderTime: 12,
      },
    ],
    [{ item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 6 }],
  );

  assert.equal(notes.length, 1);
  assert.match(notes[0], /changed from 12 to 6/);
});

test('confirmation notes evaluate over-stock against latest stock when it changed', () => {
  const notes = buildConfirmationNotes(
    [
      {
        item: 'ITEM-COTTON-001',
        itemName: 'Cotton 40s',
        godown: 'Main Godown',
        quantity: 8,
        stockShownAtOrderTime: 12,
      },
    ],
    [{ item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 6 }],
  );

  assert.equal(notes.length, 2);
  assert.match(notes[0], /exceeds latest synced stock \(6\)/);
  assert.match(notes[1], /changed from 12 to 6/);
});

test('cart stock refresh requests each item once before final confirmation', () => {
  const items = stockRefreshItemsForCart([
    { item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 4 },
    { item: 'ITEM-COTTON-001', godown: 'Zero Godown', quantity: 1 },
    { item: 'ITEM-LINING-001', godown: 'Main Godown', quantity: 2 },
  ]);

  assert.deepEqual(items, ['ITEM-COTTON-001', 'ITEM-LINING-001']);
});

test('refreshed stock changes require summary review before final submission', () => {
  const review = stockReviewAfterRefresh({
    cart: [
      {
        item: 'ITEM-COTTON-001',
        itemName: 'Cotton 40s',
        godown: 'Main Godown',
        quantity: 8,
        stockShownAtOrderTime: 12,
      },
    ],
    previousNotes: [],
    latestStockRows: [{ item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 6 }],
  });

  assert.deepEqual(review, {
    shouldReview: true,
    notes: [
      'Cotton 40s at Main Godown exceeds latest synced stock (6).',
      'Cotton 40s at Main Godown latest synced stock changed from 12 to 6.',
    ],
    state: {
      kind: 'validation_error',
      message: 'Review the latest stock notes before confirming the order.',
    },
  });
});

test('reviewed refreshed stock notes do not block the next confirmation', () => {
  const latestStockRows = [{ item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 6 }];
  const cart = [
    {
      item: 'ITEM-COTTON-001',
      itemName: 'Cotton 40s',
      godown: 'Main Godown',
      quantity: 8,
      stockShownAtOrderTime: 12,
    },
  ];
  const reviewedNotes = buildConfirmationNotes(cart, latestStockRows);

  assert.deepEqual(stockReviewAfterRefresh({ cart, previousNotes: reviewedNotes, latestStockRows }), {
    shouldReview: false,
    notes: reviewedNotes,
    state: { kind: 'idle' },
  });
});

test('pre-submit stock refresh failure returns recoverable state', async () => {
  const result = await prepareStockReviewBeforeSubmit({
    cart: [{ item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 2, stockShownAtOrderTime: 12 }],
    previousNotes: [],
    refreshItemStock: async () => {
      throw new Error('Network request failed');
    },
  });

  assert.deepEqual(result, {
    ok: false,
    stockRows: [],
    review: null,
    state: {
      kind: 'no_network',
      message: 'Network request failed',
    },
  });
});

test('godown stock list shows positive stock first and zero stock after', () => {
  const sorted = sortGodownStockForMobile([
    { item: 'ITEM-COTTON-001', godown: 'Zero B', quantity: 0 },
    { item: 'ITEM-COTTON-001', godown: 'Main B', quantity: 6 },
    { item: 'ITEM-COTTON-001', godown: 'Main A', quantity: 2 },
    { item: 'ITEM-COTTON-001', godown: 'Zero A', quantity: 0 },
  ]);

  assert.deepEqual(
    sorted.map((row) => row.godown),
    ['Main A', 'Main B', 'Zero A', 'Zero B'],
  );
});

test('godown stock row detail includes latest sync timestamp', () => {
  assert.equal(
    stockRowDetailForMobile({
      quantity: 12,
      uom: 'PCS',
      synced_at: '2026-05-19 12:05:00',
    }),
    '12 PCS latest synced\nSync 19-05-2026 12:05 PM',
  );
  assert.equal(
    stockRowDetailForMobile({
      quantity: 0,
      uom: 'PCS',
      as_on_date: '2026-05-19',
    }),
    '0 PCS latest synced\nSync 19-05-2026',
  );
});

test('sync timestamps hide fractional seconds and use Indian date format', () => {
  assert.equal(formatSyncTimestampForMobile('2026-05-27 17:45:27.748338'), '27-05-2026 5:45 PM');
  assert.equal(formatSyncTimestampForMobile('2026-05-27'), '27-05-2026');
  assert.equal(formatSyncTimestampForMobile('not available'), 'not available');
});

test('item search filters by item code, display name, and product group', () => {
  const results = searchItemsForMobile(
    [
      { name: 'ITEM-COTTON-001', item_name: 'Cotton 40s', root_stock_group: 'Cotton Fabric' },
      { name: 'ITEM-LINING-001', item_name: 'Plain Lining', root_stock_group: 'Lining' },
    ],
    'cotton',
  );

  assert.deepEqual(
    results.map((item) => item.name),
    ['ITEM-COTTON-001'],
  );
  assert.equal(searchItemsForMobile(results, '').length, 1);
});

test('manual review is displayed to mobile users as under review', () => {
  assert.equal(mobileDisplayStatus('Manual Review'), 'Under Review');
  assert.equal(mobileDisplayStatus('Processing'), 'Processing');
});

test('customer order payload sends quantity-only allocations without notes', () => {
	const payload = buildCustomerOrderPayload({
		customer: 'CUST-001',
		note: 'Should never be sent',
		allocations: [
			{
				item: 'ITEM-COTTON-001',
				godown: 'Main Godown',
				quantity: 2,
				stockShownAtOrderTime: 12,
				stockSnapshotAt: '2026-05-21 14:11:06',
			},
		],
	});

	assert.equal(payload.customer, 'CUST-001');
	assert.equal(payload.allocations.length, 1);
	assert.equal(payload.allocations[0].stock_shown_at_order_time, 12);
	assert.equal(payload.allocations[0].stock_snapshot_at, '2026-05-21 14:11:06');
	assert.equal(Object.hasOwn(payload.allocations[0], 'stockShownAtOrderTime'), false);
	assert.equal(Object.hasOwn(payload, 'note'), false);
	assert.equal(Object.hasOwn(payload, 'sales_employee_note'), false);
});

test('customer submit is blocked until the cart has at least one allocation', () => {
  assert.deepEqual(customerOrderGuard({ allocations: [] }), {
    canSubmit: false,
    step: 'summary',
    state: { kind: 'validation_error', message: 'Add at least one item before confirming the order.' },
  });

  assert.deepEqual(
    customerOrderGuard({
      allocations: [{ item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 2 }],
    }),
    {
      canSubmit: true,
      step: 'summary',
      state: { kind: 'idle' },
    },
  );
});

test('offline final submission returns recoverable state without a fake reference', async () => {
  const result = await finalizeOrderSubmission({
    submit: async () => {
      throw new Error('Network request failed');
    },
    payload: {
      customer: 'CUST-001',
      allocations: [{ item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 2 }],
    },
  });

  assert.deepEqual(result, {
    ok: false,
    reference: null,
    state: {
      kind: 'no_network',
      message: 'Network request failed',
    },
  });
});

test('final submission requires backend reference before showing success', async () => {
  const result = await finalizeOrderSubmission({
    submit: async () => ({
      order: 'ORDER-0001',
      status: 'Placed',
    }),
    payload: {
      customer: 'CUST-001',
      allocations: [{ item: 'ITEM-COTTON-001', godown: 'Main Godown', quantity: 2 }],
    },
  });

  assert.deepEqual(result, {
    ok: false,
    reference: null,
    state: {
      kind: 'validation_error',
      message: 'Order placed response did not include a reference number.',
    },
  });
});
