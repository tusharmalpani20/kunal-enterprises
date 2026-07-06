import { useRouter } from 'expo-router';
import { FrappeApp, FrappeAuth, FrappeCall, FrappeDB, FrappeFileUpload } from 'frappe-js-sdk';
import React, { createContext, useContext, useEffect, useState } from 'react';

import { APP_CONFIG, FALLBACK_BASE_URL, PRIMARY_BASE_URL } from '../constants/config';
import { resolveBaseUrl } from '../domain/baseUrlResolver.mjs';
import { AuthContext } from './auth';

interface FrappeContextType {
  db: FrappeDB | null;
  auth: FrappeAuth | null;
  call: FrappeCall | null;
  guestCall: FrappeCall | null;
  callAccessToken: string | null;
  file: FrappeFileUpload | null;
  baseUrl: string | null;
}

const FrappeContext = createContext<FrappeContextType>({
  db: null,
  auth: null,
  call: null,
  guestCall: null,
  callAccessToken: null,
  file: null,
  baseUrl: null,
});

const FrappeProvider = ({ children }: { children: React.ReactNode }) => {
  const { accessToken, logout } = useContext(AuthContext);
  const router = useRouter();
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [db, setDb] = useState<FrappeDB | null>(null);
  const [call, setCall] = useState<FrappeCall | null>(null);
  const [guestCall, setGuestCall] = useState<FrappeCall | null>(null);
  const [callAccessToken, setCallAccessToken] = useState<string | null>(null);
  const [auth, setAuth] = useState<FrappeAuth | null>(null);
  const [file, setFile] = useState<FrappeFileUpload | null>(null);

  useEffect(() => {
    let cancelled = false;
    resolveBaseUrl({
      primary: PRIMARY_BASE_URL,
      fallback: FALLBACK_BASE_URL,
      probe: frappeHealthProbe,
    }).then((resolved) => {
      if (!cancelled) {
        console.log(`[frappe] resolved base URL: ${resolved}`);
        setBaseUrl(resolved);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!baseUrl) {
      return;
    }
    const frappe = createFrappeApp(baseUrl, accessToken);

    setCall(frappe.call());
    setGuestCall(createFrappeApp(baseUrl, null).call());
    setCallAccessToken(accessToken);

    if (!accessToken) {
      setDb(null);
      setAuth(null);
      setFile(null);
      return;
    }

    frappe.axios.interceptors.response.use(
      (response) => response,
      (error) => {
        const message =
          error.response?.data?.message?.message ||
          error.response?.data?.message ||
          error.message ||
          'An error occurred';

        if (
          message === 'Invalid or inactive token' ||
          message === 'App Update Required' ||
          message === 'Error verifying token'
        ) {
          logout().then(() => {
            router.replace('/');
          });
        }

        return Promise.reject(error);
      },
    );

    setDb(frappe.db());
    setAuth(frappe.auth());
    setFile(frappe.file());
  }, [accessToken, baseUrl, logout, router]);

  return <FrappeContext.Provider value={{ db, auth, call, guestCall, callAccessToken, file, baseUrl }}>{children}</FrappeContext.Provider>;
};

export const useFrappe = (): FrappeContextType => {
  return useContext(FrappeContext);
};

export { FrappeContext, FrappeProvider };
export type { FrappeContextType };

function createFrappeApp(baseUrl: string, accessToken: string | null) {
  return new FrappeApp(
    baseUrl,
    {
      useToken: false,
      type: 'Bearer',
    },
    undefined,
    accessToken
      ? {
          'Auth-Token': `Bearer ${accessToken}`,
        }
      : undefined,
  );
}

function frappeHealthProbe(url: string, method: string, timeoutMs: number) {
  const frappe = new FrappeApp(url, { useToken: false, type: 'Bearer' }, undefined, undefined);
  frappe.axios.defaults.timeout = timeoutMs;
  return frappe.call().get(method);
}
