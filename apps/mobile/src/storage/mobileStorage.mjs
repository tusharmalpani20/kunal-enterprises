export const SESSION_KEY = 'kunal-enterprises:mobile-session';
export const CART_PREFIX = 'kunal-enterprises:cart:';
export const CART_OWNER_KEY = 'kunal-enterprises:cart-owner';

export async function saveSession(storage, session) {
  await storage.setItem(SESSION_KEY, JSON.stringify(session));
}

export async function loadSession(storage) {
  const value = await storage.getItem(SESSION_KEY);
  if (!value) {
    return null;
  }
  return JSON.parse(value);
}

export async function clearSession(storage) {
  await storage.removeItem(SESSION_KEY);
}

export async function saveCart(storage, cartKey, cart) {
  await storage.setItem(`${CART_PREFIX}${cartKey}`, JSON.stringify(cart));
}

export async function clearCart(storage, cartKey) {
  await storage.removeItem(`${CART_PREFIX}${cartKey}`);
}

export async function loadCart(storage, cartKey) {
  const value = await storage.getItem(`${CART_PREFIX}${cartKey}`);
  if (!value) {
    return [];
  }
  return JSON.parse(value);
}

export async function listSalesEmployeeDraftCarts(storage, salesEmployee) {
  if (!salesEmployee || typeof storage.getAllKeys !== 'function') {
    return [];
  }
  const draftPrefix = `${CART_PREFIX}Sales Employee:${salesEmployee}:`;
  const keys = await storage.getAllKeys();
  const drafts = [];

  for (const storageKey of keys.filter((key) => key.startsWith(draftPrefix))) {
    const customer = storageKey.slice(draftPrefix.length);
    const cart = await loadCart(storage, `Sales Employee:${salesEmployee}:${customer}`);
    const rowCount = Array.isArray(cart) ? cart.length : 0;
    const totalQuantity = Array.isArray(cart)
      ? cart.reduce((total, row) => total + Number(row.quantity || 0), 0)
      : 0;
    if (rowCount > 0 || totalQuantity > 0) {
      drafts.push({ customer, rowCount, totalQuantity });
    }
  }

  return drafts.sort((left, right) => left.customer.localeCompare(right.customer));
}

export function cartOwnerKeyForSession(session) {
  if (!session?.identityType || !session?.identity) {
    return null;
  }
  return `${session.identityType}:${session.identity}`;
}

export async function ensureCartOwner(storage, ownerKey) {
  if (!ownerKey) {
    await clearAllCarts(storage);
    await storage.removeItem(CART_OWNER_KEY);
    return { changed: true };
  }

  const previousOwner = await storage.getItem(CART_OWNER_KEY);
  if (!previousOwner) {
    await storage.setItem(CART_OWNER_KEY, ownerKey);
    return { changed: false };
  }
  if (previousOwner === ownerKey) {
    return { changed: false };
  }

  await clearAllCarts(storage);
  await storage.setItem(CART_OWNER_KEY, ownerKey);
  return { changed: true };
}

export async function clearAllCarts(storage) {
  if (typeof storage.getAllKeys !== 'function') {
    return;
  }
  const keys = await storage.getAllKeys();
  const cartKeys = keys.filter((key) => key.startsWith(CART_PREFIX));
  if (typeof storage.multiRemove === 'function') {
    await storage.multiRemove(cartKeys);
    return;
  }
  await Promise.all(cartKeys.map((key) => storage.removeItem(key)));
}

export function cartKeyForOrderContext({ mode, customer, salesEmployee, selectedCustomer }) {
  if (mode === 'Customer') {
    return customer ? `Customer:${customer}` : null;
  }
  if (!salesEmployee || !selectedCustomer) {
    return null;
  }
  return `Sales Employee:${salesEmployee}:${selectedCustomer}`;
}
