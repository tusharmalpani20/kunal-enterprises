import { useRouter } from 'expo-router';
import { FrappeApp, FrappeAuth, FrappeCall, FrappeDB, FrappeFileUpload } from 'frappe-js-sdk';
import React, { createContext, useContext, useEffect, useState } from 'react';

import { APP_CONFIG } from '../constants/config';
import { AuthContext } from './auth';

interface FrappeContextType {
  db: FrappeDB | null;
  auth: FrappeAuth | null;
  call: FrappeCall | null;
  callAccessToken: string | null;
  file: FrappeFileUpload | null;
}

const FrappeContext = createContext<FrappeContextType>({
  db: null,
  auth: null,
  call: null,
  callAccessToken: null,
  file: null,
});

const FrappeProvider = ({ children }: { children: React.ReactNode }) => {
  const { accessToken, logout } = useContext(AuthContext);
  const router = useRouter();
  const [db, setDb] = useState<FrappeDB | null>(null);
  const [call, setCall] = useState<FrappeCall | null>(null);
  const [callAccessToken, setCallAccessToken] = useState<string | null>(null);
  const [auth, setAuth] = useState<FrappeAuth | null>(null);
  const [file, setFile] = useState<FrappeFileUpload | null>(null);

  useEffect(() => {
    const frappe = createFrappeApp(accessToken);

    setCall(frappe.call());
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
  }, [accessToken, logout, router]);

  return <FrappeContext.Provider value={{ db, auth, call, callAccessToken, file }}>{children}</FrappeContext.Provider>;
};

export const useFrappe = (): FrappeContextType => {
  return useContext(FrappeContext);
};

export { FrappeContext, FrappeProvider };
export type { FrappeContextType };

function createFrappeApp(accessToken: string | null) {
  return new FrappeApp(
    APP_CONFIG.BASE_URL,
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
