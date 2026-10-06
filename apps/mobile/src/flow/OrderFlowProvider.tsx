import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Alert, Platform } from 'react-native';
import { type DateTimePickerEvent } from '@react-native-community/datetimepicker';
import { usePathname, useRouter } from 'expo-router';

import { createMobileApi } from '../api/mobileApi';
import { canUseQuickOrders, loadQuickOrderLinkedOrder } from '../domain/quickOrderFlow.mjs';
import { useQuickOrders } from './useQuickOrders';
import { useCataloguePagination } from './useCataloguePagination';
import {
  buildCustomerSignupPayload,
  canStartOtpRequest,
  customerOtpRouteAfterAccessCheck,
  nextAuthStepFromSalesEmployeeOtp,
  otpCooldownSecondsFromResponse,
  otpRequestKey,
  otpResendState,
  pendingAccessRequestFromCustomerOtp,
  salesEmployeeSessionFromOtpResponse,
  shouldUseOtpResend,
  validateCustomerSignupInput,
} from '../domain/authAccessFlow.mjs';
import { activeIdentityForMode, authHeadersForSession, canUseProtectedMobileApi, restoredSessionRoute } from '../domain/sessionFlow.mjs';
import {
  addAllocation,
  buildCustomerOrderPayload,
  buildConfirmationNotes,
  customerOrderGuard,
  finalizeOrderSubmission,
  groupCartByProductGroup,
  logoForGroup,
  logoForItem,
  orderTotals,
  parseOrderQuantityInput,
  prepareStockReviewBeforeSubmit,
  productGroupLogoMap,
  removeAllocation,
  resolveFrappeFileUrl,
  searchItemsForMobile,
  updateAllocationQuantity,
} from '../domain/mobileFlow.mjs';
import {
  buildSalesEmployeeOrderPayload,
  MAX_CUSTOMER_SEARCH_RESULTS,
  customerSearchQuery,
  salesEmployeeOrderGuard,
} from '../domain/salesEmployeeFlow.mjs';
import { loadProfileForMobile, saveCustomerProfileForMobile } from '../domain/profileHistoryFlow.mjs';
import { classifyApiFailure, requestBanner } from '../domain/sharedStateFlow.mjs';
import { PRIMARY_BASE_URL } from '../constants/config';
import {
  appSectionForStep,
  isAuthSurface as isAuthSurfaceStep,
  shouldShowFloatingCartBar,
  showCartControls as computeShowCartControls,
  signupAuthView,
} from './orderViewState.mjs';
import { navigationActionForStep, routeForStep, stepForRoute } from './stepRoutes.mjs';
import { AuthContext } from '../providers/auth';
import { useFrappe } from '../providers/frappe';
import { cartKeyForOrderContext, cartOwnerKeyForSession, clearAllCarts, clearCart, ensureCartOwner, listSalesEmployeeDraftCarts, loadCart, saveCart } from '../storage/mobileStorage';
import { dateFromIsoDate, isoDateFromDate, showToast, searchProductGroups } from '../utils/orderFormatting';
import type { AllowedCustomer, CartAllocation, ItemStock, OrderDetail, OrderSummary, ProductGroup, TallyItem } from '../types';
import type { DatePickerTarget, DraftCartSummary, Mode, Step } from './types';

const MAX_VISIBLE_ITEMS = 60;
const CUSTOMER_SEARCH_DEBOUNCE_MS = 300;
const ITEM_SEARCH_DEBOUNCE_MS = 300;
const HISTORY_PAGE_SIZE = 20;

export type OrderFlowValue = ReturnType<typeof useOrderFlowState>;

const OrderFlowContext = createContext<OrderFlowValue | null>(null);

export function OrderFlowProvider({ children }: { children: React.ReactNode }) {
  const value = useOrderFlowState();
  return <OrderFlowContext.Provider value={value}>{children}</OrderFlowContext.Provider>;
}

export function useOrderFlow(): OrderFlowValue {
  const value = useContext(OrderFlowContext);
  if (!value) {
    throw new Error('useOrderFlow must be used within an OrderFlowProvider');
  }
  return value;
}

function useOrderFlowState() {
  const { call, guestCall, callAccessToken, baseUrl } = useFrappe();
  const { logout, session, setSession } = useContext(AuthContext);
  const api = useMemo(() => createMobileApi({ call }), [call]);
  const guestApi = useMemo(() => createMobileApi({ call: guestCall || call }), [call, guestCall]);
  const router = useRouter();
  const pathname = usePathname();
  const step = stepForRoute(pathname) as Step;
  const navigationChangeRevision = useRef(0);
  const setStep = useCallback(
    (next: Step) => {
      // Invalidate pending screen work immediately, before Expo publishes the new pathname.
      if (stepForRoute(pathname) !== next) navigationChangeRevision.current++;
      const action = navigationActionForStep(stepForRoute(pathname), next);
      const href = routeForStep(next) as Parameters<typeof router.navigate>[0];
      if (action === 'replace') {
        router.replace(href);
      } else {
        router.navigate(href);
      }
    },
    [pathname, router],
  );
  const [mode, setMode] = useState<Mode>('Customer');
  const [groups, setGroups] = useState<ProductGroup[]>([]);
  const [items, setItems] = useState<TallyItem[]>([]);
  const [itemIndex, setItemIndex] = useState<Record<string, TallyItem>>({});
  const [catalogLoadedKey, setCatalogLoadedKey] = useState<string | null>(null);
  const [itemsLoadedKey, setItemsLoadedKey] = useState<string | null>(null);
  const [groupsLoading, setGroupsLoading] = useState(false);
  const [itemsLoading, setItemsLoading] = useState(false);
  const catalogRequestIdRef = useRef(0);
  const itemsRequestIdRef = useRef(0);
  const stockRequestIdRef = useRef(0);
  const [godownStockState, setGodownStockState] = useState<{ kind: string; message?: string }>({ kind: 'idle' });
  const [stockRows, setStockRows] = useState<ItemStock[]>([]);
  const [customers, setCustomers] = useState<AllowedCustomer[]>([]);
  const [customerSearchLoading, setCustomerSearchLoading] = useState(false);
  const [selectedCustomer, setSelectedCustomer] = useState<AllowedCustomer | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<ProductGroup | null>(null);
  const [selectedItem, setSelectedItem] = useState<TallyItem | null>(null);
  const [godownSelectorOpen, setGodownSelectorOpen] = useState(false);
  const [cart, setCart] = useState<CartAllocation[]>([]);
  const [cartLoadedKey, setCartLoadedKey] = useState<string | null>(null);
  const [draftCarts, setDraftCarts] = useState<DraftCartSummary[]>([]);
  const [draftCartsExpanded, setDraftCartsExpanded] = useState(false);
  const [groupSheetOpen, setGroupSheetOpen] = useState(false);
  const [salesNote, setSalesNote] = useState('');
  const [customerSearch, setCustomerSearch] = useState('');
  const [itemSearch, setItemSearch] = useState('');
  const [quantity, setQuantity] = useState('14');
  const [mobileNumber, setMobileNumber] = useState('');
  const [otpCode, setOtpCode] = useState('');
  const [customerAuthIntent, setCustomerAuthIntent] = useState<'login' | 'signup'>('login');
  const [otpIdentityType, setOtpIdentityType] = useState<Mode | null>(null);
  const [signupDetailsReview, setSignupDetailsReview] = useState(false);
  const [signupCustomerName, setSignupCustomerName] = useState('');
  const [signupBusinessLegalName, setSignupBusinessLegalName] = useState('');
  const [signupGstin, setSignupGstin] = useState('');
  const [signupEmailId, setSignupEmailId] = useState('');
  const [signupDateOfBirth, setSignupDateOfBirth] = useState('');
  const [signupDateOfAnniversary, setSignupDateOfAnniversary] = useState('');
  const [otpSentAtMs, setOtpSentAtMs] = useState<number | null>(null);
  const [lastOtpRequestKey, setLastOtpRequestKey] = useState<string | null>(null);
  const [otpCooldownSeconds, setOtpCooldownSeconds] = useState(45);
  const [otpRequestLoading, setOtpRequestLoading] = useState(false);
  const otpRequestInFlightRef = useRef(false);
  const otpRequestKeyRef = useRef<string | null>(null);
  const [otpVerificationLoading, setOtpVerificationLoading] = useState(false);
  const otpVerificationInFlightRef = useRef(false);
  const [pendingAccessRequest, setPendingAccessRequest] = useState<Record<string, string> | null>(null);
  const [pendingAccessRefreshing, setPendingAccessRefreshing] = useState(false);
  const [reference, setReference] = useState<string | null>(null);
  const [historyRows, setHistoryRows] = useState<OrderSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyHasMore, setHistoryHasMore] = useState(false);
  const [orderDetail, setOrderDetail] = useState<OrderDetail | null>(null);
  const [profile, setProfile] = useState<Record<string, unknown> | null>(null);
  const [profileEmail, setProfileEmail] = useState('');
  const [profileBirthDate, setProfileBirthDate] = useState('');
  const [profileAnniversaryDate, setProfileAnniversaryDate] = useState('');
  const [datePickerTarget, setDatePickerTarget] = useState<DatePickerTarget | null>(null);
  const [systemState, setSystemState] = useState<{ kind: string; message?: string }>({ kind: 'idle' });
  const hasActiveModeSession = canUseProtectedMobileApi({ mode, session });
  const protectedCallReady = !session?.accessToken || callAccessToken === session.accessToken;
  const catalogLoading = groupsLoading || itemsLoading;
  const quickOrderContextKey = `${mode}:${session?.identity || ''}:${session?.accessToken || ''}`;
  const quickOrdersEnabled = canUseQuickOrders({ mode, session }) && protectedCallReady;
  const quickOrders = useQuickOrders({
    api,
    customer: session?.identity || '',
    contextKey: quickOrderContextKey,
    enabled: quickOrdersEnabled,
    active: step === 'quickOrder',
    onError(error) {
      const failure = classifyApiFailure(error);
      setSystemState(failure);
      if (failure.kind === 'expired_session') {
        setStep('auth');
        void logout();
      }
    },
  });

  function showQuickOrder() {
    if (!quickOrdersEnabled) return;
    setSystemState({ kind: 'idle' });
    setStep('quickOrder');
  }

  function showQuickOrderDetail(request: string) {
    if (!quickOrdersEnabled) return;
    setStep('quickOrderDetail');
    void quickOrders.loadDetail(request);
  }

  const [linkedLoadingRevision, setLinkedLoadingRevision] = useState<number | null>(null);
  const linkedOrderRequestId = useRef(0);
  const linkedOrderInFlight = useRef<number | null>(null);
  const linkedNavigation = useRef({ key: '', revision: 0 });
  const navigationKey = `${quickOrderContextKey}:${pathname}:${step}:${navigationChangeRevision.current}:${quickOrders.detail?.name || ''}`;
  if (linkedNavigation.current.key !== navigationKey) {
    linkedNavigation.current = { key: navigationKey, revision: linkedNavigation.current.revision + 1 };
  }

  const quickOrderLinkedLoading = linkedLoadingRevision === linkedNavigation.current.revision;

  async function showQuickOrderLinkedOrder() {
    const request = quickOrders.detail;
    if (!request?.order || !quickOrdersEnabled) return;
    const revision = linkedNavigation.current.revision;
    const navigationRevision = navigationChangeRevision.current;
    if (linkedOrderInFlight.current === revision) return;
    linkedOrderInFlight.current = revision;
    const requestId = ++linkedOrderRequestId.current;
    const isCurrent = () => linkedNavigation.current.revision === revision
      && linkedOrderRequestId.current === requestId
      && navigationChangeRevision.current === navigationRevision;
    setLinkedLoadingRevision(revision);
    try {
      const detail = await loadQuickOrderLinkedOrder({ order: request.order,
        customer: session?.identity || '', loadOrder: api.orderDetail, isCurrent });
      if (!detail || !isCurrent()) return;
      setOrderDetail(detail);
      setStep('detail');
    } catch (error) {
      if (!isCurrent()) return;
      const failure = classifyApiFailure(error);
      setSystemState(failure);
      if (failure.kind === 'expired_session') {
        setStep('auth');
        await logout();
      }
    } finally {
      if (linkedOrderRequestId.current === requestId) {
        linkedOrderInFlight.current = null;
        setLinkedLoadingRevision(null);
      }
    }
  }

  useEffect(() => {
    const banner = requestBanner(systemState);
    if (!banner || systemState.kind === 'loading') {
      return;
    }
    showToast(systemState.kind === 'validation_error' || systemState.kind === 'no_network' || systemState.kind === 'expired_session' || systemState.kind === 'access_removed' ? 'error' : 'info', banner.title, banner.message);
  }, [systemState]);

  const loadCatalogForCustomer = useCallback(
    async (customer: string, salesEmployee?: string) => {
      const catalogKey = `${customer}:${salesEmployee || ''}`;
      const sameCatalogContext = catalogLoadedKey === catalogKey;
      const requestId = ++catalogRequestIdRef.current;
      itemsRequestIdRef.current += 1;
      try {
        setGroupsLoading(true);
        setItemsLoading(false);
        setGroups([]);
        setCatalogLoadedKey(null);
        setItems([]);
        if (!sameCatalogContext) {
          setItemIndex({});
        }
        setItemsLoadedKey(null);
        const catalogApi = api as any;
        const allowedGroups = await catalogApi.allowedProductGroups(customer, salesEmployee);
        if (requestId !== catalogRequestIdRef.current) {
          return false;
        }
        setGroups(allowedGroups);
        setSelectedGroup((current) => current && allowedGroups.some((group: ProductGroup) => group.name === current.name) ? current : null);
        setCatalogLoadedKey(catalogKey);
        return true;
      } catch (error) {
        if (requestId !== catalogRequestIdRef.current) {
          return false;
        }
        const failure = classifyApiFailure(error);
        setSystemState(failure);
        setCatalogLoadedKey(null);
        setGroups([]);
        setItems([]);
        setItemIndex({});
        setItemsLoadedKey(null);
        if (failure.kind === 'expired_session') {
          await logout();
          setCart([]);
          setSelectedCustomer(null);
          setSelectedGroup(null);
          setSelectedItem(null);
          setGodownSelectorOpen(false);
          setStep('auth');
          return false;
        }
        return false;
      } finally {
        if (requestId === catalogRequestIdRef.current) {
          setGroupsLoading(false);
        }
      }
    },
    [api, catalogLoadedKey, logout],
  );

  useEffect(() => {
    if (!session || (step !== 'auth' && step !== 'pending')) {
      return;
    }
    const route = restoredSessionRoute(session);
    setMode(route.mode as Mode);
    setSystemState({ kind: 'idle' });
    setStep(route.step as Step);
  }, [session, step]);

  useEffect(() => {
    if (!hasActiveModeSession) {
      catalogRequestIdRef.current += 1;
      itemsRequestIdRef.current += 1;
      setGroupsLoading(false);
      setItemsLoading(false);
      setGroups([]);
      setItems([]);
      setItemIndex({});
      setCatalogLoadedKey(null);
      setItemsLoadedKey(null);
      setCustomers([]);
      setCustomerSearchLoading(false);
      return;
    }
    if (!protectedCallReady) {
      catalogRequestIdRef.current += 1;
      itemsRequestIdRef.current += 1;
      setGroupsLoading(false);
      setItemsLoading(false);
      setGroups([]);
      setItems([]);
      setItemIndex({});
      setCatalogLoadedKey(null);
      setItemsLoadedKey(null);
      setCustomerSearchLoading(false);
      return;
    }
    const customer = activeCustomerIdentity();
    const salesEmployee = activeSalesEmployeeIdentity();
    if (mode === 'Customer') {
      setCustomers([]);
      setCustomerSearchLoading(false);
      const catalogKey = `${customer}:`;
      if (catalogLoadedKey !== catalogKey && !groupsLoading) {
        loadCatalogForCustomer(customer);
      }
      return;
    }
    if (step !== 'customer') {
      setCustomers([]);
      setCustomerSearchLoading(false);
      return;
    }

    const searchText = customerSearch.trim();
    if (searchText.length === 1) {
      setCustomers([]);
      setCustomerSearchLoading(false);
      return;
    }

    const query = customerSearchQuery(customerSearch) || '';
    let cancelled = false;
    setCustomerSearchLoading(true);
    const searchTimer = setTimeout(() => {
      api.allowedCustomers(salesEmployee, query, MAX_CUSTOMER_SEARCH_RESULTS)
        .then((results) => {
          if (!cancelled) {
            setCustomers(results);
          }
        })
        .catch(async (error) => {
          if (cancelled) return;
          const failure = classifyApiFailure(error);
          setSystemState(failure);
          setCustomers([]);
          if (failure.kind === 'expired_session') {
            await logout();
            setSelectedCustomer(null);
            setStep('auth');
          }
        })
        .finally(() => {
          if (!cancelled) {
            setCustomerSearchLoading(false);
          }
        });
    }, CUSTOMER_SEARCH_DEBOUNCE_MS);

    return () => {
      cancelled = true;
      clearTimeout(searchTimer);
    };
  }, [api, catalogLoadedKey, customerSearch, hasActiveModeSession, loadCatalogForCustomer, logout, mode, protectedCallReady, step, session]);

  const catalogueIdentity = `${quickOrderContextKey}:${activeCustomer()}:${activeSalesEmployeeContext() || ''}`;
  const catalogueQuery = `${catalogueIdentity}:${selectedGroup?.name || ''}:${itemSearch.trim()}`;
  const pagination = useCataloguePagination({
    contextKey: catalogueQuery,
    catalogueKey: catalogueIdentity,
    active: step === 'groups' && hasActiveModeSession && protectedCallReady && !groupsLoading && !itemsLoading
      && itemsLoadedKey === `${activeCustomer()}:${activeSalesEmployeeContext() || ''}:${selectedGroup?.name || ''}:${itemSearch.trim()}`,
    fetchPage: (offset) => (api as any).allowedItemsPage(activeCustomer(), selectedGroup?.name, activeSalesEmployeeContext(), {
      search: itemSearch.trim(), limit: MAX_VISIBLE_ITEMS, offset,
    }),
    appendItems(nextItems) {
      setItems(current => [...new Map([...current, ...nextItems].map(item => [item.name, item])).values()]);
      setItemIndex(current => ({ ...current, ...Object.fromEntries(nextItems.map(item => [item.name, item])) }));
    },
    onError(error) {
      const failure = classifyApiFailure(error);
      setSystemState(failure);
      if (failure.kind === 'expired_session') void logout();
    },
  });

  useEffect(() => {
    if (!hasActiveModeSession || !protectedCallReady || groupsLoading || step !== 'groups') {
      return;
    }

    const customer = activeCustomer();
    const salesEmployee = activeSalesEmployeeContext();
    const expectedCatalogKey = `${customer}:${salesEmployee || ''}`;
    if (!customer || catalogLoadedKey !== expectedCatalogKey) {
      return;
    }

    const productGroup = selectedGroup?.name;
    const search = itemSearch.trim();
    const itemQueryKey = `${expectedCatalogKey}:${productGroup || ''}:${search}`;
    if (itemsLoadedKey === itemQueryKey) {
      return;
    }

    let cancelled = false;
    let requestId = 0;
    const searchTimer = setTimeout(async () => {
      if (cancelled) {
        return;
      }

      requestId = ++itemsRequestIdRef.current;
      setItemsLoading(true);
      try {
        const catalogApi = api as any;
        const page = await catalogApi.allowedItemsPage(customer, productGroup, salesEmployee, {
          search,
          limit: MAX_VISIBLE_ITEMS,
          offset: 0,
        });
        if (cancelled || requestId !== itemsRequestIdRef.current) {
          return;
        }
        const nextItems = page.items;
        pagination.acceptPage(page);
        setItems(nextItems);
        setItemIndex((current) => {
          const next = { ...current };
          for (const item of nextItems) {
            next[item.name] = item;
          }
          return next;
        });
        setItemsLoadedKey(itemQueryKey);
      } catch (error) {
        if (cancelled || requestId !== itemsRequestIdRef.current) {
          return;
        }
        const failure = classifyApiFailure(error);
        setSystemState(failure);
        setItems([]);
        setItemsLoadedKey(null);
        if (failure.kind === 'expired_session') {
          await logout();
          setGroups([]);
          setItems([]);
          setItemIndex({});
          setItemsLoadedKey(null);
          setSelectedCustomer(null);
          setSelectedGroup(null);
          setSelectedItem(null);
          setStep('auth');
        }
      } finally {
        if (!cancelled && requestId === itemsRequestIdRef.current) {
          setItemsLoading(false);
        }
      }
    }, ITEM_SEARCH_DEBOUNCE_MS);

    return () => {
      cancelled = true;
      clearTimeout(searchTimer);
      if (requestId && requestId === itemsRequestIdRef.current) {
        itemsRequestIdRef.current += 1;
        setItemsLoading(false);
      }
    };
  }, [api, catalogLoadedKey, groupsLoading, hasActiveModeSession, itemSearch, itemsLoadedKey, logout, mode, protectedCallReady, selectedCustomer, selectedGroup, session, step]);

  const totals = useMemo(() => orderTotals(cart), [cart]);
  const notes = useMemo(() => buildConfirmationNotes(cart, stockRows), [cart, stockRows]);
  const visibleGroups = useMemo(() => searchProductGroups(groups, itemSearch), [groups, itemSearch]);
  const renderedGroups = visibleGroups;
  const visibleItems = useMemo(
    () => {
      const pool = selectedGroup
        ? items.filter((item) => item.root_stock_group === selectedGroup.name)
        : items;
      return searchItemsForMobile(pool, itemSearch);
    },
    [items, selectedGroup, itemSearch],
  );
  const renderedItems = visibleItems;
  const resend = otpResendState({ lastSentAtMs: otpSentAtMs, nowMs: Date.now(), waitSeconds: otpCooldownSeconds });
  const currentOtpIdentityType = customerAuthIntent === 'signup' ? 'Customer' : otpIdentityType || 'Customer';
  const currentOtpRequestKey = otpRequestKey({ mode: currentOtpIdentityType, mobileNumber, customerAuthIntent });
  const hasCurrentOtpRequest = otpSentAtMs !== null && lastOtpRequestKey === currentOtpRequestKey;
  useEffect(() => {
    otpRequestKeyRef.current = currentOtpRequestKey;
  }, [currentOtpRequestKey]);
  const canUseOtpResend = shouldUseOtpResend({
    lastSentAtMs: otpSentAtMs,
    canResend: resend.canResend,
    currentRequestKey: currentOtpRequestKey,
    lastRequestKey: lastOtpRequestKey,
  });
  const cartStorageKey = useMemo(
    () =>
      cartKeyForOrderContext({
        mode,
        customer: activeCustomerIdentity(),
        salesEmployee: activeSalesEmployeeIdentity(),
        selectedCustomer: selectedCustomer?.customer || '',
      }),
    [mode, selectedCustomer, session],
  );
  const cartOwnerKey = useMemo(() => cartOwnerKeyForSession(session), [session]);
  const groupLogoMap = useMemo(() => productGroupLogoMap(groups), [groups]);
  const groupedCart = useMemo(
    () => groupCartByProductGroup(cart, Object.values(itemIndex), groupLogoMap),
    [cart, groupLogoMap, itemIndex],
  );
  useEffect(() => {
    if (groups.length === 0) return;
    console.log(`[logos] group logo map — ${groupLogoMap.size} of ${groups.length} groups have logos`);
    if (groupLogoMap.size > 0) {
      const entries = [...groupLogoMap.entries()].map(([name, url]) => `${name} -> ${url}`);
      console.log('[logos] map entries:', entries.join(', '));
    }
  }, [groupLogoMap, groups]);
  const logoForGroupName = useCallback((name: string) => logoForGroup(groupLogoMap, name), [groupLogoMap]);
  const logoForTallyItem = useCallback((item: TallyItem) => logoForItem(groupLogoMap, item), [groupLogoMap]);
  const logoForItemName = useCallback(
    (itemName: string) => {
      const item = itemIndex[itemName];
      return item ? logoForItem(groupLogoMap, item) : null;
    },
    [groupLogoMap, itemIndex],
  );
  const resolveLogoUrl = useCallback((path: string | null | undefined) => resolveFrappeFileUrl(path, baseUrl || PRIMARY_BASE_URL), [baseUrl]);

  useEffect(() => {
    let cancelled = false;
    ensureCartOwner(AsyncStorage, cartOwnerKey).then((result) => {
      if (cancelled || !result.changed) return;
      setCart([]);
      setCartLoadedKey(null);
      setSelectedCustomer(null);
      setSelectedGroup(null);
      setSelectedItem(null);
      setGroups([]);
      setItems([]);
      setItemIndex({});
      setCatalogLoadedKey(null);
      setItemsLoadedKey(null);
    });
    return () => {
      cancelled = true;
    };
  }, [cartOwnerKey]);

  useEffect(() => {
    let cancelled = false;
    if (!cartStorageKey) {
      setCartLoadedKey(null);
      return;
    }
    setCartLoadedKey(null);
    loadCart(AsyncStorage, cartStorageKey).then((storedCart) => {
      if (cancelled) return;
      setCart(storedCart);
      setCartLoadedKey(cartStorageKey);
    });
    return () => {
      cancelled = true;
    };
  }, [cartStorageKey]);

  useEffect(() => {
    if (!cartStorageKey || cartLoadedKey !== cartStorageKey) {
      return;
    }
    saveCart(AsyncStorage, cartStorageKey, cart);
  }, [cart, cartLoadedKey, cartStorageKey]);

  useEffect(() => {
    let cancelled = false;
    if (mode !== 'Sales Employee' || step !== 'customer' || !hasActiveModeSession) {
      setDraftCarts([]);
      return;
    }
    listSalesEmployeeDraftCarts(AsyncStorage, activeSalesEmployeeIdentity()).then((drafts) => {
      if (cancelled) return;
      setDraftCarts(drafts);
    });
    return () => {
      cancelled = true;
    };
  }, [cartStorageKey, hasActiveModeSession, mode, step, session]);

  useEffect(() => {
    stockRequestIdRef.current += 1;
    setGodownSelectorOpen(false);
    setStockRows([]);
    setGodownStockState({ kind: 'idle' });
  }, [session?.accessToken, mode, selectedCustomer?.customer]);

  function chooseGroup(group: ProductGroup | null) {
    setSelectedGroup(group);
    setItemSearch('');
    setItems([]);
    setItemsLoadedKey(null);
  }

  async function chooseItem(item: TallyItem) {
    const requestId = ++stockRequestIdRef.current;
    setSelectedItem(item);
    setStockRows([]);
    setQuantity('1');
    // Quantity-only ordering must remain available while optional stock loads or fails.
    setGodownSelectorOpen(true);
    setGodownStockState({ kind: 'loading' });
    try {
      const rows = await api.itemStock(activeCustomer(), item.name, activeSalesEmployeeContext());
      if (requestId !== stockRequestIdRef.current) return;
      setStockRows(rows);
      setGodownStockState({ kind: 'idle' });
    } catch (error) {
      if (requestId !== stockRequestIdRef.current) return;
      const failure = classifyApiFailure(error);
      setGodownStockState(failure);
      if (failure.kind === 'expired_session' || failure.kind === 'access_removed') {
        setGodownSelectorOpen(false);
        setSystemState(failure);
      }
    }
  }

  async function chooseCustomer(customer: AllowedCustomer) {
    setSelectedCustomer(customer);
    setSelectedGroup(null);
    setItemSearch('');
    const loaded = await loadCatalogForCustomer(customer.customer, activeSalesEmployeeIdentity());
    if (loaded) {
      setStep('groups');
    }
  }

  async function chooseDraftCart(draft: DraftCartSummary) {
    const knownCustomer = customers.find((customer) => customer.customer === draft.customer);
    if (knownCustomer) {
      await chooseCustomer(knownCustomer);
      return;
    }

    try {
      const matches: AllowedCustomer[] = await api.allowedCustomers(activeSalesEmployeeIdentity(), draft.customer);
      const customer =
        matches.find((match) => match.customer === draft.customer) ||
        matches.find((match) => match.customer_name === draft.customer);
      await chooseCustomer(
        customer || {
          customer: draft.customer,
          customer_name: draft.customer,
          business_legal_name: 'Draft cart',
          client_code: '',
        },
      );
    } catch (error) {
      const failure = classifyApiFailure(error);
      setSystemState(failure);
    }
  }

  function customerForDraftCart(draft: DraftCartSummary) {
    return customers.find((customer) => customer.customer === draft.customer);
  }

  async function clearDraftCart(draft: DraftCartSummary) {
    const customer = customerForDraftCart(draft);
    const customerName = customer?.customer_name || draft.customer;
    Alert.alert('Clear draft cart?', `This will remove the saved cart for ${customerName}.`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Clear cart',
        style: 'destructive',
        onPress: async () => {
          const draftKey = cartKeyForOrderContext({
            mode: 'Sales Employee',
            customer: '',
            salesEmployee: activeSalesEmployeeIdentity(),
            selectedCustomer: draft.customer,
          });
          if (!draftKey) return;
          await clearCart(AsyncStorage, draftKey);
          setDraftCarts((current) => current.filter((row) => row.customer !== draft.customer));
          showToast('success', 'Draft cart cleared', customerName);
        },
      },
    ]);
  }

  function addFromGodown(stock: ItemStock) {
    if (!selectedItem) return;
    const parsedQuantity = parseOrderQuantityInput(quantity);
    if (!parsedQuantity.ok) {
      setSystemState(parsedQuantity.state);
      return;
    }
    setCart((current) =>
      addAllocation(current, {
        item: selectedItem.name,
        itemName: selectedItem.item_name,
        godown: stock.godown,
        quantity: parsedQuantity.quantity,
        stockShownAtOrderTime: stock.quantity,
        stockSnapshotAt: stock.synced_at,
      }),
    );
    setGodownSelectorOpen(false);
    showToast('success', 'Added to cart', `${selectedItem.item_name} from ${stock.godown}.`);
  }

  function addWithoutGodown() {
    if (!selectedItem) return;
    const parsedQuantity = parseOrderQuantityInput(quantity);
    if (!parsedQuantity.ok) {
      setSystemState(parsedQuantity.state);
      return;
    }
    setCart((current) => addAllocation(current, {
      item: selectedItem.name,
      itemName: selectedItem.item_name,
      quantity: parsedQuantity.quantity,
    }));
    setGodownSelectorOpen(false);
    showToast('success', 'Added to cart', `${selectedItem.item_name} · Godown not assigned.`);
  }

  function backToItems() {
    setSelectedItem(null);
    setStockRows([]);
    setGodownSelectorOpen(false);
    setStep('groups');
  }

  function changeCartQuantity(row: CartAllocation, delta: number) {
    const nextQuantity = row.quantity + delta;
    if (nextQuantity <= 0) {
      setCart((current) => removeAllocation(current, { item: row.item, godown: row.godown }));
      return;
    }
    setCart((current) =>
      updateAllocationQuantity(current, {
        item: row.item,
        godown: row.godown,
        quantity: nextQuantity,
      }),
    );
  }

  function removeCartItem(item: string) {
    setCart((current) => removeAllocation(current, { item }));
  }

  async function submitOrder() {
    setSystemState({ kind: 'loading' });
    if (mode === 'Sales Employee') {
      const guard = salesEmployeeOrderGuard({ selectedCustomer, allocations: cart });
      if (!guard.canSubmit) {
        setSystemState(guard.state);
        setStep(guard.step as Step);
        return;
      }
    } else {
      const guard = customerOrderGuard({ allocations: cart });
      if (!guard.canSubmit) {
        setSystemState(guard.state);
        setStep(guard.step as Step);
        return;
      }
    }
    const payload =
      mode === 'Sales Employee'
        ? buildSalesEmployeeOrderPayload({
          salesEmployee: activeSalesEmployeeIdentity(),
          customer: activeCustomer(),
          note: salesNote,
          allocations: cart,
        })
        : buildCustomerOrderPayload({ customer: activeCustomerIdentity(), allocations: cart });
    const stockPreparation = await prepareStockReviewBeforeSubmit({
      cart,
      previousNotes: notes as string[],
      refreshItemStock: (item: string) => api.itemStock(activeCustomer(), item, activeSalesEmployeeContext()),
    });
    setStockRows(stockPreparation.stockRows);
    if (!stockPreparation.ok) {
      setSystemState(stockPreparation.state);
      return;
    }
    if (stockPreparation.review?.shouldReview) {
      setSystemState(stockPreparation.review.state);
      setStep('summary');
      return;
    }
    const result = await finalizeOrderSubmission({
      submit: api.submitOrder,
      payload,
    });
    setSystemState(result.state);
    if (result.ok) {
      setReference(result.reference);
      if (cartStorageKey) {
        await clearCart(AsyncStorage, cartStorageKey);
        setCartLoadedKey(null);
      }
      setCart([]);
      setStep('success');
    }
  }

  async function requestOtp() {
    if (!canStartOtpRequest({
      inFlight: otpRequestInFlightRef.current,
      canResend: resend.canResend,
      hasCurrentRequest: hasCurrentOtpRequest,
    })) return;

    const requestNumber = mobileNumber.trim();
    const requestKey = currentOtpRequestKey;
    otpRequestInFlightRef.current = true;
    setOtpRequestLoading(true);
    setSystemState({ kind: 'loading' });

    try {
      if (!requestNumber) {
        setSystemState({ kind: 'validation_error', message: 'Mobile Number is required.' });
        return;
      }
      if (canUseOtpResend) {
        const identityType = currentOtpIdentityType;
        const response = await api.resendOtp(requestNumber, identityType);
        if (otpRequestKeyRef.current !== requestKey) {
          setSystemState({ kind: 'idle' });
          return;
        }
        setOtpCooldownSeconds(otpCooldownSecondsFromResponse(response, otpCooldownSeconds));
        setOtpSentAtMs(Date.now());
        setLastOtpRequestKey(requestKey);
        setOtpCode('');
        setSystemState({ kind: 'idle' });
        showToast('success', 'OTP resent', `A new code was sent to ${requestNumber}.`);
        return;
      }
      if (customerAuthIntent === 'login') {
        const response = await requestSignInOtp(requestNumber);
        if (otpRequestKeyRef.current !== requestKey) {
          setSystemState({ kind: 'idle' });
          return;
        }
        const inferredIdentityType = response.identity_type as Mode;
        setMode(inferredIdentityType);
        setOtpIdentityType(inferredIdentityType);
        setOtpCooldownSeconds(otpCooldownSecondsFromResponse(response, otpCooldownSeconds));
        setOtpSentAtMs(Date.now());
        setLastOtpRequestKey(otpRequestKey({ mode: inferredIdentityType, mobileNumber: requestNumber, customerAuthIntent }));
        setOtpCode('');
        setSystemState({ kind: 'idle' });
        showToast('success', 'Sign in OTP sent', `Enter the code sent to ${requestNumber}.`);
        return;
      }
      const signupInput = {
        customerName: signupCustomerName,
        businessLegalName: signupBusinessLegalName,
        gstin: signupGstin,
        mobileNumber: requestNumber,
        emailId: signupEmailId,
        dateOfBirth: signupDateOfBirth,
        dateOfAnniversary: signupDateOfAnniversary,
      };
      const validation = validateCustomerSignupInput(signupInput);
      if (!validation.ok) {
        setSystemState({ kind: 'validation_error', message: validation.message });
        return;
      }
      const response = await api.startCustomerSignup(buildCustomerSignupPayload(signupInput));
      setMode('Customer');
      setOtpIdentityType('Customer');
      setSignupDetailsReview(false);
      setOtpCooldownSeconds(otpCooldownSecondsFromResponse(response, otpCooldownSeconds));
      setOtpSentAtMs(Date.now());
      setLastOtpRequestKey(requestKey);
      setOtpCode('');
      setSystemState({ kind: 'idle' });
      showToast('success', 'Sign up OTP sent', `Enter the code sent to ${requestNumber}.`);
    } catch (error) {
      const failure = classifyApiFailure(error);
      setSystemState(failure);
    } finally {
      otpRequestInFlightRef.current = false;
      setOtpRequestLoading(false);
    }
  }

  async function verifyOtp() {
    if (otpVerificationInFlightRef.current) return;

    otpVerificationInFlightRef.current = true;
    setOtpVerificationLoading(true);
    setSystemState({ kind: 'loading' });

    try {
      const requestNumber = mobileNumber.trim();
      const requestCode = otpCode.trim();
      if (!requestNumber || !requestCode) {
        setSystemState({ kind: 'validation_error', message: 'Enter the OTP before verifying.' });
        return;
      }
      if (otpIdentityType === 'Sales Employee') {
        const response = await api.verifySalesEmployeeOtp(requestNumber, requestCode);
        const employeeSession = salesEmployeeSessionFromOtpResponse(response);
        const nextStep = nextAuthStepFromSalesEmployeeOtp(response);
        if (employeeSession) {
          await setSession(employeeSession);
          setSystemState({ kind: 'idle' });
          setStep('customer');
          showToast('success', 'Signed in', 'Choose a Customer to start ordering.');
          return;
        }
        setSystemState({ kind: 'idle' });
        setStep(nextStep === 'pending_access' ? 'pending' : 'auth');
        showToast('info', 'Sign in pending', 'Access must be active before ordering.');
        return;
      }
      const response = await api.verifyCustomerOtp(requestNumber, requestCode);
      const route = await customerOtpRouteAfterAccessCheck({
        otpResponse: response,
        customerAccessStatus: api.customerAccessStatus,
      });
      if (route.session) {
        await setSession(route.session);
        setPendingAccessRequest(null);
        setSystemState({ kind: 'idle' });
        setStep(route.step as Step);
        showToast('success', 'Signed in', 'Your account is ready for ordering.');
        return;
      }
      const pendingRequest = pendingAccessRequestFromCustomerOtp({ otpResponse: response, mobileNumber });
      if (pendingRequest) {
        setPendingAccessRequest(pendingRequest);
      }
      await setSession(null);
      setSystemState({ kind: 'idle' });
      setStep(route.step as Step);
      showToast('info', customerAuthIntent === 'signup' ? 'Sign up received' : 'Sign in pending', 'Access must be active before ordering.');
    } catch (error) {
      const failure = classifyApiFailure(error);
      setSystemState(failure);
    } finally {
      otpVerificationInFlightRef.current = false;
      setOtpVerificationLoading(false);
    }
  }

  async function requestSignInOtp(number: string) {
    return api.startLoginOtp(number);
  }

  async function refreshPendingAccess() {
    const request = pendingAccessRequest;
    if (!request?.customer) {
      setSystemState({ kind: 'validation_error', message: 'No pending access request was found on this device. Sign in again to check status.' });
      setStep('auth');
      return;
    }

    try {
      setPendingAccessRefreshing(true);
      const status = await guestApi.customerAccessStatus(request.customer);
      if (status.customer_app_access) {
        setPendingAccessRequest(null);
        setCustomerAuthIntent('login');
        setOtpIdentityType(null);
        setOtpSentAtMs(null);
        setLastOtpRequestKey(null);
        setOtpCode('');
        setSystemState({ kind: 'idle' });
        setStep('auth');
        showToast('success', 'Access approved', 'Sign in with OTP to continue.');
        return;
      }

      const nextRequest = { ...request, status: status.status || request.status || 'Pending Admin Review' };
      setPendingAccessRequest(nextRequest);
      setSystemState({ kind: 'idle' });
      showToast('info', 'Still pending', 'Admin approval is not active yet.');
    } catch (error) {
      const failure = classifyApiFailure(error);
      setSystemState(failure);
    } finally {
      setPendingAccessRefreshing(false);
    }
  }

  function activeCustomer() {
    return mode === 'Sales Employee' ? selectedCustomer?.customer || '' : activeCustomerIdentity();
  }

  function activeCustomerIdentity() {
    return activeIdentityForMode({ mode: 'Customer', session, fallback: 'CUST-001' });
  }

  function activeSalesEmployeeIdentity() {
    return activeIdentityForMode({ mode: 'Sales Employee', session, fallback: 'SE-001' });
  }

  function activeSalesEmployeeContext() {
    return mode === 'Sales Employee' ? activeSalesEmployeeIdentity() : undefined;
  }

  function switchMode(nextMode: Mode) {
    setMode(nextMode);
    setStep('auth');
    setCustomerAuthIntent('login');
    setOtpIdentityType(null);
    setSignupDetailsReview(false);
    setOtpSentAtMs(null);
    setLastOtpRequestKey(null);
    setOtpCooldownSeconds(45);
    setCart([]);
    catalogRequestIdRef.current += 1;
    itemsRequestIdRef.current += 1;
    setGroupsLoading(false);
    setItemsLoading(false);
    setSelectedCustomer(null);
    setSelectedGroup(null);
    setSelectedItem(null);
    setCatalogLoadedKey(null);
    setItemsLoadedKey(null);
    setItemIndex({});
    setItems([]);
    setGodownSelectorOpen(false);
  }

  async function refreshCatalog() {
    const customer = activeCustomer();
    if (!customer) return;
    await loadCatalogForCustomer(customer, activeSalesEmployeeContext());
  }

  function showOrder() {
    setSystemState({ kind: 'idle' });
    setOrderDetail(null);
    if (mode === 'Sales Employee' && !selectedCustomer) {
      setStep('customer');
      return;
    }
    setStep('groups');
  }

  function switchCustomer() {
    setSystemState({ kind: 'idle' });
    setSelectedCustomer(null);
    setSelectedGroup(null);
    setSelectedItem(null);
    setCart([]);
    setCartLoadedKey(null);
    setGodownSelectorOpen(false);
    setItemSearch('');
    setGroups([]);
    setItems([]);
    setItemIndex({});
    setItemsLoadedKey(null);
    setCatalogLoadedKey(null);
    catalogRequestIdRef.current += 1;
    itemsRequestIdRef.current += 1;
    setGroupsLoading(false);
    setItemsLoading(false);
    setStep('customer');
  }

  async function showHistory() {
    if (!hasActiveModeSession) {
      setSystemState({ kind: 'validation_error', message: 'Verify OTP before loading account data.' });
      return;
    }
    try {
      setHistoryLoading(true);
      const rows = await fetchHistoryPage(0);
      setHistoryRows(rows.slice(0, HISTORY_PAGE_SIZE));
      setHistoryHasMore(rows.length > HISTORY_PAGE_SIZE);
      setStep('history');
    } catch (error) {
      const failure = classifyApiFailure(error);
      setSystemState(failure);
      if (failure.kind === 'expired_session') {
        await logout();
        setStep('auth');
      }
    } finally {
      setHistoryLoading(false);
    }
  }

  async function loadMoreHistory() {
    if (!hasActiveModeSession || historyLoading || !historyHasMore) {
      return;
    }
    try {
      setHistoryLoading(true);
      const rows = await fetchHistoryPage(historyRows.length);
      setHistoryRows((current) => [...current, ...rows.slice(0, HISTORY_PAGE_SIZE)]);
      setHistoryHasMore(rows.length > HISTORY_PAGE_SIZE);
    } catch (error) {
      const failure = classifyApiFailure(error);
      setSystemState(failure);
      if (failure.kind === 'expired_session') {
        await logout();
        setStep('auth');
      }
    } finally {
      setHistoryLoading(false);
    }
  }

  function fetchHistoryPage(offset: number) {
    const options = { limit: HISTORY_PAGE_SIZE + 1, offset };
    return mode === 'Sales Employee'
      ? api.orderHistory(undefined, activeSalesEmployeeIdentity(), options)
      : api.orderHistory(activeCustomerIdentity(), undefined, { ...options, includeQuickOrders: true });
  }

  async function showProfile() {
    if (!hasActiveModeSession) {
      setSystemState({ kind: 'validation_error', message: 'Verify OTP before loading account data.' });
      return;
    }
    const result = await loadProfileForMobile({
      identityType: mode,
      identity: mode === 'Customer' ? activeCustomerIdentity() : activeSalesEmployeeIdentity(),
      getProfile: api.getProfile,
    });
    setSystemState(result.state);
    if (!result.ok || !result.profile) {
      return;
    }
    const nextProfile = result.profile;
    setProfile(nextProfile);
    setProfileEmail(String(nextProfile.email_id || ''));
    setProfileBirthDate(String(nextProfile.date_of_birth || ''));
    setProfileAnniversaryDate(String(nextProfile.date_of_anniversary || ''));
    setStep('profile');
  }

  async function saveCustomerProfile() {
    const result = await saveCustomerProfileForMobile({
      customer: String(profile?.customer || activeCustomerIdentity()),
      patch: {
        email_id: profileEmail,
        date_of_birth: profileBirthDate,
        date_of_anniversary: profileAnniversaryDate,
      },
      updateCustomerProfile: api.updateCustomerProfile,
    });
    setSystemState(result.state);
    if (!result.ok || !result.profile) {
      return;
    }
    setProfile(result.profile);
    showToast('success', 'Profile updated', 'Your changes have been saved.');
  }

  async function showOrderDetail(order: OrderSummary) {
    try {
      setOrderDetail(
        await api.orderDetail(
          order.name,
          mode === 'Sales Employee'
            ? { salesEmployee: activeSalesEmployeeIdentity() }
            : { customer: activeCustomerIdentity() },
        ),
      );
      setStep('detail');
    } catch (error) {
      const failure = classifyApiFailure(error);
      setSystemState(failure);
      if (failure.kind === 'expired_session') {
        await logout();
        setStep('auth');
      }
    }
  }

  async function revokeAndLogout() {
    if (session) {
      await api.revokeToken?.(authHeadersForSession(session));
    }
    await clearAllCarts(AsyncStorage);
    await logout();
    resetOtpAfterLogout();
    setStep('auth');
    setCart([]);
    setCatalogLoadedKey(null);
    setGroups([]);
    setItems([]);
    setItemIndex({});
    setItemsLoadedKey(null);
    setReference(null);
    setOrderDetail(null);
  }

  function resetOtpAfterLogout() {
    setOtpCode('');
    setOtpIdentityType(null);
    setSignupDetailsReview(false);
    setOtpSentAtMs(null);
    setLastOtpRequestKey(null);
    setOtpCooldownSeconds(45);
    setSystemState({ kind: 'idle' });
  }

  const isAuthSurface = isAuthSurfaceStep(step);
  const appSection = appSectionForStep(step);
  const isOrderSection = appSection === 'order';
  const showCartControls = computeShowCartControls({ mode, step });
  const { otpRequestedForCurrentFlow, isSignupOtpFlow, showSignupDetails, signupDetailsReadOnly } = signupAuthView({
    customerAuthIntent,
    otpSentAtMs,
    lastOtpRequestKey,
    currentOtpRequestKey,
    signupDetailsReview,
  });
  const showFloatingCartBar = shouldShowFloatingCartBar({ step, rowCount: totals.rowCount });
  const activeDatePickerValue = datePickerTarget ? dateValueForTarget(datePickerTarget) : '';
  const activeDatePickerDate = dateFromIsoDate(activeDatePickerValue);

  function dateValueForTarget(target: DatePickerTarget) {
    switch (target) {
      case 'signupDateOfBirth':
        return signupDateOfBirth;
      case 'signupDateOfAnniversary':
        return signupDateOfAnniversary;
      case 'profileBirthDate':
        return profileBirthDate;
      case 'profileAnniversaryDate':
        return profileAnniversaryDate;
    }
  }

  function setDateValueForTarget(target: DatePickerTarget, value: string) {
    switch (target) {
      case 'signupDateOfBirth':
        setSignupDateOfBirth(value);
        return;
      case 'signupDateOfAnniversary':
        setSignupDateOfAnniversary(value);
        return;
      case 'profileBirthDate':
        setProfileBirthDate(value);
        return;
      case 'profileAnniversaryDate':
        setProfileAnniversaryDate(value);
        return;
    }
  }

  function handleDatePickerChange(event: DateTimePickerEvent, selectedDate?: Date) {
    if (event.type === 'dismissed') {
      setDatePickerTarget(null);
      return;
    }
    if (datePickerTarget && selectedDate) {
      setDateValueForTarget(datePickerTarget, isoDateFromDate(selectedDate));
    }
    if (Platform.OS !== 'ios') {
      setDatePickerTarget(null);
    }
  }

  function editSignupDetails() {
    setSignupDetailsReview(false);
    setOtpIdentityType(null);
    setOtpSentAtMs(null);
    setLastOtpRequestKey(null);
    setOtpCode('');
    setSystemState({ kind: 'idle' });
  }

  return {
    // state
    quickOrders, quickOrdersEnabled, quickOrderLinkedLoading, showQuickOrder, showQuickOrderDetail, showQuickOrderLinkedOrder,
    mode, setMode,
    step, setStep,
    groups,
    catalogLoading,
    groupsLoading,
    itemsLoading,
    itemsTotalCount: pagination.itemsTotalCount,
    itemsAllCount: pagination.itemsAllCount,
    itemsHasMore: pagination.itemsHasMore,
    itemsMoreLoading: pagination.itemsMoreLoading,
    loadMoreItems: pagination.loadMoreItems,
    items,
    stockRows,
    customers,
    customerSearchLoading,
    selectedCustomer,
    selectedGroup,
    selectedItem,
    godownSelectorOpen, setGodownSelectorOpen,
    godownStockState,
    cart,
    draftCarts,
    draftCartsExpanded, setDraftCartsExpanded,
    groupSheetOpen, setGroupSheetOpen,
    salesNote, setSalesNote,
    customerSearch, setCustomerSearch,
    itemSearch, setItemSearch,
    quantity, setQuantity,
    mobileNumber, setMobileNumber,
    otpCode, setOtpCode,
    customerAuthIntent, setCustomerAuthIntent,
    otpIdentityType, setOtpIdentityType,
    otpRequestLoading,
    otpVerificationLoading,
    signupDetailsReview, setSignupDetailsReview,
    signupCustomerName, setSignupCustomerName,
    signupBusinessLegalName, setSignupBusinessLegalName,
    signupGstin, setSignupGstin,
    signupEmailId, setSignupEmailId,
    signupDateOfBirth,
    signupDateOfAnniversary,
    setOtpSentAtMs,
    setLastOtpRequestKey,
    pendingAccessRequest,
    pendingAccessRefreshing,
    reference,
    historyRows,
    historyLoading,
    historyHasMore,
    orderDetail,
    profile,
    profileEmail, setProfileEmail,
    profileBirthDate,
    profileAnniversaryDate,
    datePickerTarget, setDatePickerTarget,
    systemState, setSystemState,
    // derived
    totals,
    notes,
    groupedCart,
    renderedGroups,
    visibleItems,
    renderedItems,
    resend,
    isAuthSurface,
    appSection,
    isOrderSection,
    showCartControls,
    otpRequestedForCurrentFlow,
    isSignupOtpFlow,
    showSignupDetails,
    signupDetailsReadOnly,
    showFloatingCartBar,
    activeDatePickerValue,
    activeDatePickerDate,
    // logo helpers
    logoForGroupName,
    logoForTallyItem,
    logoForItemName,
    resolveLogoUrl,
    // handlers
    chooseGroup,
    chooseItem,
    chooseCustomer,
    chooseDraftCart,
    clearDraftCart,
    customerForDraftCart,
    addFromGodown,
    addWithoutGodown,
    backToItems,
    changeCartQuantity,
    removeCartItem,
    submitOrder,
    requestOtp,
    verifyOtp,
    refreshPendingAccess,
    switchMode,
    showOrder,
    refreshCatalog,
    switchCustomer,
    showHistory,
    loadMoreHistory,
    showProfile,
    saveCustomerProfile,
    showOrderDetail,
    revokeAndLogout,
    handleDatePickerChange,
    editSignupDetails,
  };
}
