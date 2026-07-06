import Toast from 'react-native-toast-message';

import { formatSyncTimestampForMobile, stockRowDetailForMobile } from '../domain/mobileFlow.mjs';
import type { CartAllocation, ItemStock, OrderSummary, ProductGroup, TallyItem } from '../types';
import type { Mode, ToastKind } from '../flow/types';

export { resolveFrappeFileUrl } from '../domain/mobileFlow.mjs';

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
  const placedStamp = formatOrderPlacedStamp(order.confirmation_datetime);
  const placedLine = placedStamp ? `Placed ${placedStamp}` : '';
  const detailLine = placedLine ? `${statusLine}\n${placedLine}` : statusLine;
  if (mode !== 'Sales Employee') {
    return detailLine;
  }
  return `${order.customer_name || order.customer} · ${detailLine}`;
}

export function formatOrderPlacedStamp(value?: string | null, today = new Date()) {
  const parsed = parseOrderPlacedDateTime(value);
  if (!parsed) {
    return '';
  }

  const time = formatHourMinute(parsed.hour, parsed.minute);
  if (isSameLocalDate(parsed, today)) {
    return `at ${time}`;
  }
  return `on ${formatIndianDate(parsed.isoDate)} at ${time}`;
}

export function formatOrderPlacedTime(value?: string | null) {
  return formatOrderPlacedStamp(value).replace(/^at /, '').replace(/^on \d{2}-\d{2}-\d{4} at /, '');
}

function parseOrderPlacedDateTime(value?: string | null) {
  const text = String(value || '').trim();
  if (!text) {
    return null;
  }

  const frappeMatch = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})(?::\d{2})?/.exec(text);
  if (frappeMatch) {
    return {
      isoDate: frappeMatch[1],
      hour: Number(frappeMatch[2]),
      minute: frappeMatch[3],
    };
  }

  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return {
    isoDate: isoDateFromDate(parsed),
    hour: parsed.getHours(),
    minute: String(parsed.getMinutes()).padStart(2, '0'),
  };
}

function isSameLocalDate(parsed: { isoDate: string }, today: Date) {
  return parsed.isoDate === isoDateFromDate(today);
}

function formatHourMinute(hour24: number, minute: string) {
  const period = hour24 >= 12 ? 'PM' : 'AM';
  const hour12 = hour24 % 12 || 12;
  return `${hour12}:${minute} ${period}`;
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
