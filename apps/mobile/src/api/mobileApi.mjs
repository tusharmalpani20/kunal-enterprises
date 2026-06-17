import { createFrappeApiClient } from './frappeClient.mjs';
import { mockApi } from './mockApi.mjs';

export function mobileApiMode({ call }) {
  return call ? 'live' : 'mock';
}

export function createMobileApi({ call }) {
  if (call) {
    return createFrappeApiClient(call);
  }
  return mockApi;
}
