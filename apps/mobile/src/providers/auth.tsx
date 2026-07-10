import AsyncStorage from '@react-native-async-storage/async-storage';
import { FrappeApp } from 'frappe-js-sdk';
import React, { createContext, useCallback, useEffect, useMemo, useState } from 'react';

import { createFrappeApiClient } from '../api/frappeClient';
import { FALLBACK_BASE_URL, PRIMARY_BASE_URL } from '../constants/config';
import { bootstrapStoredSession } from '../domain/sessionFlow';
import { clearSession, saveSession } from '../storage/mobileStorage';

interface AuthContextType {
  accessToken: string | null;
  session: MobileSession | null;
  isReady: boolean;
  setAccessToken: (token: string | null) => void;
  setSession: (session: MobileSession | null) => Promise<void>;
  logout: () => Promise<void>;
}

interface MobileSession {
  accessToken: string;
  identityType: string;
  identity: string;
  displayName?: string;
}

export const AuthContext = createContext<AuthContextType>({
  accessToken: null,
  session: null,
  isReady: false,
  setAccessToken: () => undefined,
  setSession: async () => undefined,
  logout: async () => undefined,
});

export function AuthProvider({
  children,
  validateStoredSession = validateStoredMobileSession,
}: {
  children: React.ReactNode;
  validateStoredSession?: (headers: Record<string, string>) => Promise<unknown>;
}) {
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [session, setSessionState] = useState<MobileSession | null>(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await bootstrapStoredSession({
          storage: AsyncStorage,
          currentSession: validateStoredSession,
          applySession: (storedSession: MobileSession) => {
            setSessionState(storedSession);
            setAccessToken(storedSession.accessToken);
          },
        });
      } catch (error) {
        console.warn('bootstrapStoredSession failed', error);
      } finally {
        if (!cancelled) {
          setIsReady(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [validateStoredSession]);

  const setSession = useCallback(async (nextSession: MobileSession | null) => {
    setSessionState(nextSession);
    setAccessToken(nextSession?.accessToken || null);
    if (nextSession) {
      await saveSession(AsyncStorage, nextSession);
    } else {
      await clearSession(AsyncStorage);
    }
  }, []);

  const logout = useCallback(async () => {
    await setSession(null);
  }, [setSession]);
  const value = useMemo(
    () => ({ accessToken, session, isReady, setAccessToken, setSession, logout }),
    [accessToken, isReady, logout, session, setSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export async function validateStoredMobileSession(headers: Record<string, string>) {
  try {
    return await validateSessionAgainstUrl(PRIMARY_BASE_URL, headers);
  } catch (primaryError) {
    if (!FALLBACK_BASE_URL) {
      throw primaryError;
    }
    return validateSessionAgainstUrl(FALLBACK_BASE_URL, headers);
  }
}

async function validateSessionAgainstUrl(baseUrl: string, headers: Record<string, string>) {
  const frappe = new FrappeApp(
    baseUrl,
    {
      useToken: false,
      type: 'Bearer',
    },
    undefined,
    headers,
  );
  return createFrappeApiClient(frappe.call()).currentSession();
}
