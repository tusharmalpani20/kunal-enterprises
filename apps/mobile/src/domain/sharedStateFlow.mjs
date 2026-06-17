export function requestStateFromTiming({ isLoading, elapsedMs }) {
  if (!isLoading) {
    return { kind: 'idle' };
  }
  if (elapsedMs >= 1500) {
    return { kind: 'slow' };
  }
  return { kind: 'loading' };
}

export function classifyApiFailure(error) {
  const message = apiErrorMessage(error);
  if (/network request failed|failed to fetch|offline|data.*undefined|timeout|couldn'?t connect/i.test(message)) {
    return { kind: 'no_network', message };
  }
  if (message === 'Invalid or inactive token' || message === 'Error verifying token') {
    return { kind: 'expired_session', message };
  }
  if (/Customer App Access is not active|Sales Employee is disabled|access.*removed/i.test(message)) {
    return { kind: 'access_removed', message };
  }
  return { kind: 'validation_error', message };
}

export function apiErrorMessage(error) {
  const candidates = [
    error?.response?.data?.message?.error?.message,
    error?.response?.data?.message?.message,
    error?.response?.data?.message,
    error?.message?.error?.message,
    error?.message?.message,
    error?.message,
    error,
  ];

  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim()) {
      return candidate;
    }
  }

  return 'Request failed';
}

export function detectStockChanges(cart, latestStockRows) {
  return cart.flatMap((allocation) => {
    const latest = latestStockRows.find(
      (row) => row.item === allocation.item && row.godown === allocation.godown,
    );
    if (!latest || latest.quantity === allocation.stockShownAtOrderTime) {
      return [];
    }
    return [
      `${allocation.itemName || allocation.item} at ${allocation.godown} latest synced stock changed from ${allocation.stockShownAtOrderTime} to ${latest.quantity}.`,
    ];
  });
}

export function requestBanner(state) {
  const banners = {
    idle: null,
    loading: {
      title: 'Loading',
      message: 'Fetching the latest portal data.',
      action: null,
    },
    slow: {
      title: 'Still working',
      message: 'The request is taking longer than usual.',
      action: null,
    },
    no_network: {
      title: 'No network',
      message: 'Internet is required for final order submission.',
      action: 'Retry',
    },
    expired_session: {
      title: 'Session expired',
      message: 'Your access token is no longer active.',
      action: 'Log in again',
    },
    access_removed: {
      title: 'Access changed',
      message: 'Ordering is blocked until access is active again.',
      action: 'Check status',
    },
    validation_error: {
      title: 'Validation error',
      message: state.message || 'The backend rejected this request.',
      action: 'Review',
    },
  };

  return banners[state.kind];
}
