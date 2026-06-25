import Toast from 'react-native-toast-message';

import { formatSyncTimestampForMobile, stockRowDetailForMobile } from '../domain/mobileFlow.mjs';
import type { CartAllocation, ItemStock, OrderSummary, ProductGroup, TallyItem } from '../types';
import type { Mode, ToastKind } from '../flow/types';

export function showToast(type: ToastKind, text1: string, text2?: string) {
  Toast.show({
    type,
    text1,
    text2,
    position: 'top',
    visibilityTime: type === 'error' ? 5000 : 3000,
  });
}

export function searchProductGroups(groups: ProductGroup[], search: string) {
  const query = search.trim().toLowerCase();
  if (!query) {
    return groups;
  }
  return groups.filter((group) =>
    [group.group_name, group.full_path, group.name].some((value) => String(value || '').toLowerCase().includes(query)),
  );
}

export function uniqueItemsByName(items: TallyItem[]) {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.name)) {
      return false;
    }
    seen.add(item.name);
    return true;
  });
}

export function cartQuantityForItem(cart: CartAllocation[], item: string) {
  return cart.filter((row) => row.item === item).reduce((total, row) => total + row.quantity, 0);
}

export function orderHistoryRowDetail(order: OrderSummary, mode: Mode) {
  const statusLine = `${order.display_status || order.status} · Quantity ${order.total_quantity || 0}`;
  if (mode !== 'Sales Employee') {
    return statusLine;
  }
  return `${order.customer_name || order.customer} · ${statusLine}`;
}

export function godownStockDetailForSelection(stock: ItemStock, requestedQuantityInput: string) {
  const requestedQuantity = Number(requestedQuantityInput);
  const uom = stock.uom || '';
  if (Number.isFinite(requestedQuantity) && requestedQuantity > stock.quantity) {
    const syncStamp = formatSyncTimestampForMobile(stock.synced_at || stock.as_on_date);
    return `Only ${stock.quantity} ${uom} here · requested ${requestedQuantity}\nSync ${syncStamp}`.trim();
  }
  return stockRowDetailForMobile(stock);
}

export function dateFromIsoDate(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
  if (!match) {
    return new Date();
  }
  const [, year, month, day] = match;
  return new Date(Number(year), Number(month) - 1, Number(day));
}

export function isoDateFromDate(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function formatIndianDate(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
  if (!match) {
    return '';
  }
  const [, year, month, day] = match;
  return `${day}-${month}-${year}`;
}
