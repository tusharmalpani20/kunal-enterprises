export const QUICK_ORDER_TEXT_LIMIT = 5000;

export function quickOrderTextForSubmit(value) {
  const text = String(value || '').trim();
  if (!text) throw new Error('Describe the items and quantities you need.');
  if (text.length > QUICK_ORDER_TEXT_LIMIT) {
    throw new Error(`Quick order text cannot exceed ${QUICK_ORDER_TEXT_LIMIT} characters.`);
  }
  return text;
}

export function canUseQuickOrders({ mode, session }) {
  return mode === 'Customer' && session?.identityType === 'Customer' && Boolean(session.identity && session.accessToken);
}

// Keep concurrent taps from creating multiple requests, including before React updates the button.
export function createQuickOrderSubmitter(submit) {
  let inFlight = false;
  return async function submitText(value) {
    if (inFlight) return null;
    const text = quickOrderTextForSubmit(value);
    inFlight = true;
    try {
      const request = await submit(text);
      if (!request?.name) throw new Error('Quick order response did not include a request reference.');
      return request;
    } finally {
      inFlight = false;
    }
  };
}

export async function loadQuickOrderLinkedOrder({ order, customer, loadOrder, isCurrent }) {
  try {
    const detail = await loadOrder(order, { customer });
    return isCurrent() ? detail : null;
  } catch (error) {
    // Errors from an account or screen that has been left must not log out or navigate the new one.
    if (!isCurrent()) return null;
    throw error;
  }
}
