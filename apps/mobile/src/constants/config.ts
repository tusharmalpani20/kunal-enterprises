export const LOCAL_BASE_URL = 'http://10.50.69.198:8000';
export const REMOTE_BASE_URL = 'https://ke-dev.hopnet.co.in';

export const isDevEnvironment = process.env.NODE_ENV !== 'production';

export const PRIMARY_BASE_URL: string =
  process.env.EXPO_PUBLIC_FRAPPE_BASE_URL || (isDevEnvironment ? LOCAL_BASE_URL : REMOTE_BASE_URL);

export const FALLBACK_BASE_URL: string | null = isDevEnvironment
  ? process.env.EXPO_PUBLIC_FRAPPE_BASE_URL
    ? null
    : REMOTE_BASE_URL
  : null;

export const APP_CONFIG = {
  BASE_URL: PRIMARY_BASE_URL,
  FALLBACK_BASE_URL,
};
