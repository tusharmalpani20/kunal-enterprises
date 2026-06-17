import { clearSession, loadSession } from '../storage/mobileStorage.mjs';

export function authHeadersForSession(session) {
  return { 'Auth-Token': `Bearer ${session.accessToken}` };
}

export function activeIdentityForMode({ mode, session, fallback }) {
  if (session?.identityType === mode && session.identity) {
    return session.identity;
  }
  return fallback;
}

export function canUseProtectedMobileApi({ mode, session }) {
  return Boolean(session?.identityType === mode && session.identity && session.accessToken);
}

export function restoredSessionRoute(session) {
  if (!session?.identityType || !session?.identity || !session?.accessToken) {
    return { mode: 'Customer', step: 'auth' };
  }
  if (session.identityType === 'Sales Employee') {
    return { mode: 'Sales Employee', step: 'customer' };
  }
  return { mode: 'Customer', step: 'groups' };
}

export async function refreshStoredSession({ storage, currentSession }) {
  const session = await loadSession(storage);
  if (!session) {
    return { valid: false, session: null, state: { kind: 'idle' } };
  }

  try {
    await currentSession(authHeadersForSession(session));
    return { valid: true, session, state: { kind: 'idle' } };
  } catch (error) {
    await clearSession(storage);
    return {
      valid: false,
      session: null,
      state: {
        kind: 'expired_session',
        message: String(error?.message || ''),
      },
    };
  }
}

export async function bootstrapStoredSession({ storage, currentSession, applySession }) {
  const result = currentSession
    ? await refreshStoredSession({ storage, currentSession })
    : { valid: true, session: await loadSession(storage), state: { kind: 'idle' } };

  if (result.valid && result.session) {
    applySession(result.session);
  }
  return result;
}

export async function logoutAndRevokeSession({ storage, revokeToken }) {
  const session = await loadSession(storage);
  if (session) {
    try {
      await revokeToken(authHeadersForSession(session));
    } catch (_error) {
      // Local logout must still clear the device even if the network revoke fails.
    }
  }
  await clearSession(storage);
  return { session: null, state: { kind: 'idle' } };
}
