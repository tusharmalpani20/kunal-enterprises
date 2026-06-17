import { classifyApiFailure } from './sharedStateFlow.mjs';
import { detectStockChanges } from './sharedStateFlow.mjs';

export function addAllocation(cart, allocation) {
  if (!allocation.item || !allocation.godown) {
    throw new Error('Item and godown are required');
  }
  if (!Number.isFinite(allocation.quantity) || allocation.quantity <= 0) {
    throw new Error('Order Quantity must be positive');
  }

  const key = `${allocation.item}:${allocation.godown}`;
  const existing = cart.find((row) => `${row.item}:${row.godown}` === key);
  if (!existing) {
    return [...cart, { ...allocation }];
  }

  return cart.map((row) =>
    `${row.item}:${row.godown}` === key
      ? {
          ...row,
          quantity: row.quantity + allocation.quantity,
          stockShownAtOrderTime: allocation.stockShownAtOrderTime,
          stockSnapshotAt: allocation.stockSnapshotAt,
        }
      : row,
  );
}

export function updateAllocationQuantity(cart, { item, godown, quantity }) {
  if (!Number.isFinite(quantity) || quantity <= 0) {
    throw new Error('Order Quantity must be positive');
  }
  return cart.map((row) => (row.item === item && row.godown === godown ? { ...row, quantity } : row));
}

export function parseOrderQuantityInput(value) {
  const quantity = Number(value);
  if (!Number.isFinite(quantity) || quantity <= 0) {
    return {
      ok: false,
      quantity: 0,
      state: { kind: 'validation_error', message: 'Order Quantity must be positive.' },
    };
  }
  return {
    ok: true,
    quantity,
    state: { kind: 'idle' },
  };
}

export function removeAllocation(cart, { item, godown }) {
  if (godown) {
    return cart.filter((row) => !(row.item === item && row.godown === godown));
  }
  return cart.filter((row) => row.item !== item);
}

export function buildCustomerOrderPayload({ customer, allocations }) {
	if (!customer) {
		throw new Error('Customer is required');
	}
	return {
		customer,
		allocations: allocations.map(orderAllocationForApi),
	};
}

export function orderAllocationForApi(allocation) {
	return {
		item: allocation.item,
		godown: allocation.godown,
		quantity: allocation.quantity,
		stock_shown_at_order_time: allocation.stockShownAtOrderTime ?? 0,
		stock_snapshot_at: allocation.stockSnapshotAt,
	};
}

export function customerOrderGuard({ allocations }) {
  if (!Array.isArray(allocations) || allocations.length === 0) {
    return {
      canSubmit: false,
      step: 'summary',
      state: { kind: 'validation_error', message: 'Add at least one item before confirming the order.' },
    };
  }

  return {
    canSubmit: true,
    step: 'summary',
    state: { kind: 'idle' },
  };
}

export function sortGodownStockForMobile(stockRows) {
  return [...stockRows].sort(
    (a, b) => Number(b.quantity > 0) - Number(a.quantity > 0) || a.godown.localeCompare(b.godown),
  );
}

export function stockRowDetailForMobile(stock) {
  const uom = stock.uom || '';
  const syncStamp = formatSyncTimestampForMobile(stock.synced_at || stock.as_on_date);
  return `${stock.quantity} ${uom} latest synced\nSync ${syncStamp}`.trim();
}

export function formatSyncTimestampForMobile(value) {
  const raw = String(value || '').trim();
  if (!raw) {
    return 'not available';
  }

  const match = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?)?/.exec(raw);
  if (!match) {
    return raw;
  }

  const [, year, month, day, hour, minute] = match;
  if (!hour || !minute) {
    return `${day}-${month}-${year}`;
  }

  const hourNumber = Number(hour);
  const period = hourNumber >= 12 ? 'PM' : 'AM';
  const displayHour = hourNumber % 12 || 12;
  return `${day}-${month}-${year} ${displayHour}:${minute} ${period}`;
}

export function searchItemsForMobile(items, search) {
  const query = String(search || '').trim().toLowerCase();
  if (!query) {
    return items;
  }
  return items.filter((item) =>
    [item.name, item.item_name, item.root_stock_group].some((value) => String(value || '').toLowerCase().includes(query)),
  );
}

export function stockRefreshItemsForCart(cart) {
  return [...new Set(cart.map((row) => row.item).filter(Boolean))];
}

export function stockReviewAfterRefresh({
  cart,
  previousNotes = /** @type {string[]} */ ([]),
  latestStockRows = /** @type {Array<Record<string, unknown>>} */ ([]),
}) {
  const notes = buildConfirmationNotes(cart, latestStockRows);
  const previous = new Set(previousNotes);
  const hasNewNotes = notes.some((note) => !previous.has(note));
  return {
    shouldReview: hasNewNotes,
    notes,
    state: hasNewNotes
      ? {
          kind: 'validation_error',
          message: 'Review the latest stock notes before confirming the order.',
        }
      : { kind: 'idle' },
  };
}

export async function prepareStockReviewBeforeSubmit({
  cart,
  previousNotes = /** @type {string[]} */ ([]),
  refreshItemStock,
}) {
  try {
    const stockRows = (await Promise.all(stockRefreshItemsForCart(cart).map((item) => refreshItemStock(item)))).flat();
    return {
      ok: true,
      stockRows,
      review: stockReviewAfterRefresh({ cart, previousNotes, latestStockRows: stockRows }),
      state: { kind: 'idle' },
    };
  } catch (error) {
    return {
      ok: false,
      stockRows: [],
      review: null,
      state: classifyApiFailure(error),
    };
  }
}

export function orderTotals(cart) {
  return {
    rowCount: cart.length,
    totalQuantity: cart.reduce((total, row) => total + row.quantity, 0),
  };
}

export function buildConfirmationNotes(cart, latestStockRows = []) {
  const availabilityNotes = cart
    .map((row) => {
      const latestStock = latestStockRows.find((stock) => stock.item === row.item && stock.godown === row.godown);
      return {
        row,
        stockForAvailability: latestStock ? latestStock.quantity : row.stockShownAtOrderTime,
      };
    })
    .filter(({ row, stockForAvailability }) => row.quantity > stockForAvailability)
    .map(({ row, stockForAvailability }) => {
      if (stockForAvailability === 0) {
        return `${row.itemName} at ${row.godown} has zero latest synced stock. You can still request it.`;
      }
      return `${row.itemName} at ${row.godown} exceeds latest synced stock (${stockForAvailability}).`;
    });
  return [...availabilityNotes, ...detectStockChanges(cart, latestStockRows)];
}

export function mobileDisplayStatus(status) {
  return status === 'Manual Review' ? 'Under Review' : status;
}

export async function finalizeOrderSubmission({ submit, payload }) {
  try {
    const order = await submit(payload);
    if (!order?.portal_reference_number) {
      return {
        ok: false,
        reference: null,
        state: {
          kind: 'validation_error',
          message: 'Order placed response did not include a reference number.',
        },
      };
    }
    return {
      ok: true,
      reference: order.portal_reference_number,
      order,
      state: { kind: 'idle' },
    };
  } catch (error) {
    return {
      ok: false,
      reference: null,
      state: classifyApiFailure(error),
    };
  }
}
