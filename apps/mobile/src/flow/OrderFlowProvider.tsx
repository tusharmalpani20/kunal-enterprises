import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Alert, Platform } from 'react-native';
import { type DateTimePickerEvent } from '@react-native-community/datetimepicker';
import { usePathname, useRouter } from 'expo-router';

import { createMobileApi } from '../api/mobileApi';
import {
  buildCustomerSignupPayload,
  customerOtpRouteAfterAccessCheck,
  nextAuthStepFromSalesEmployeeOtp,
  otpCooldownSecondsFromResponse,
  otpRequestKey,
  otpResendState,
  salesEmployeeSessionFromOtpResponse,
  shouldTrySalesEmployeeOtpAfterCustomerOtpError,
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
  orderTotals,
  parseOrderQuantityInput,
  prepareStockReviewBeforeSubmit,
  removeAllocation,
  searchItemsForMobile,
  updateAllocationQuantity,
} from '../domain/mobileFlow.mjs';
import { buildSalesEmployeeOrderPayload, salesEmployeeOrderGuard } from '../domain/salesEmployeeFlow.mjs';
import { loadProfileForMobile, saveCustomerProfileForMobile } from '../domain/profileHistoryFlow.mjs';
import { classifyApiFailure, requestBanner } from '../domain/sharedStateFlow.mjs';
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
import { dateFromIsoDate, isoDateFromDate, showToast, searchProductGroups, uniqueItemsByName } from '../utils/orderFormatting';
import type { AllowedCustomer, CartAllocation, ItemStock, OrderDetail, OrderSummary, ProductGroup, TallyItem } from '../types';
import type { DatePickerTarget, DraftCartSummary, Mode, Step } from './types';

const MAX_VISIBLE_GROUPS = 40;
const MAX_VISIBLE_ITEMS = 60;

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
  const { call, callAccessToken } = useFrappe();
  const { logout, session, setSession } = useContext(AuthContext);
  const api = useMemo(() => createMobileApi({ call }), [call]);
  const router = useRouter();
  const pathname = usePathname();
  const step = stepForRoute(pathname) as Step;
  const setStep = useCallback(
    (next: Step) => {
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
  const [catalogLoadedKey, setCatalogLoadedKey] = useState<string | null>(null);
  const [stockRows, setStockRows] = useState<ItemStock[]>([]);
  const [customers, setCustomers] = useState<AllowedCustomer[]>([]);
  const [selectedCustomer, setSelectedCustomer] = useState<AllowedCustomer | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<ProductGroup | null>(null);
  const [selectedItem, setSelectedItem] = useState<TallyItem | null>(null);
  const [godownSelectorOpen, setGodownSelectorOpen] = useState(false);
  const [cart, setCart] = useState<CartAllocation[]>([]);
  const [cartLoadedKey, setCartLoadedKey] = useState<string | null>(null);
  const [draftCarts, setDraftCarts] = useState<DraftCartSummary[]>([]);
  const [draftCartsExpanded, setDraftCartsExpanded] = useState(false);
  const [salesNote, setSalesNote] = useState('');
  const [customerSearch, setCustomerSearch] = useState('');
  const [itemSearch, setItemSearch] = useState('');
  const [quantity, setQuantity] = useState('14');
  const [mobileNumber, setMobileNumber] = useState('');
  const [otpCode, setOtpCode] = useState('123456');
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
  const [reference, setReference] = useState<string | null>(null);
  const [historyRows, setHistoryRows] = useState<OrderSummary[]>([]);
  const [orderDetail, setOrderDetail] = useState<OrderDetail | null>(null);
  const [profile, setProfile] = useState<Record<string, unknown> | null>(null);
  const [profileEmail, setProfileEmail] = useState('');
  const [profileBirthDate, setProfileBirthDate] = useState('');
  const [profileAnniversaryDate, setProfileAnniversaryDate] = useState('');
  const [datePickerTarget, setDatePickerTarget] = useState<DatePickerTarget | null>(null);
  const [systemState, setSystemState] = useState<{ kind: string; message?: string }>({ kind: 'idle' });
  const hasActiveModeSession = canUseProtectedMobileApi({ mode, session });
  const protectedCallReady = !session?.accessToken || callAccessToken === session.accessToken;

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
      try {
        const catalogApi = api as any;
        const allowedGroups = await catalogApi.allowedProductGroups(customer, salesEmployee);
        setGroups(allowedGroups);
        const groupedItems = await Promise.all(
          allowedGroups.map((group: ProductGroup) => catalogApi.allowedItems(customer, group.name, salesEmployee)),
        );
        setItems(uniqueItemsByName(groupedItems.flat()));
        setCatalogLoadedKey(catalogKey);
      } catch (error) {
        const failure = classifyApiFailure(error);
        setSystemState(failure);
        setCatalogLoadedKey(null);
        if (failure.kind === 'expired_session') {
          await logout();
          setGroups([]);
          setItems([]);
          setCart([]);
          setSelectedCustomer(null);
          setSelectedGroup(null);
          setSelectedItem(null);
          setGodownSelectorOpen(false);
          setStep('auth');
          return;
        }
      }
    },
    [api, logout],
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
      setGroups([]);
      setCustomers([]);
      return;
    }
    if (!protectedCallReady) {
      return;
    }
    const customer = activeCustomerIdentity();
    const salesEmployee = activeSalesEmployeeIdentity();
    if (mode === 'Customer') {
      const catalogKey = `${customer}:`;
      if (catalogLoadedKey !== catalogKey) {
        loadCatalogForCustomer(customer);
      }
      return;
    }
    api.allowedCustomers(salesEmployee, customerSearch).then(setCustomers).catch(async (error) => {
      const failure = classifyApiFailure(error);
      setSystemState(failure);
      if (failure.kind === 'expired_session') {
        await logout();
        setCustomers([]);
        setSelectedCustomer(null);
        setStep('auth');
      }
    });
  }, [api, catalogLoadedKey, customerSearch, hasActiveModeSession, loadCatalogForCustomer, logout, mode, protectedCallReady, session]);

  const totals = useMemo(() => orderTotals(cart), [cart]);
  const notes = useMemo(() => buildConfirmationNotes(cart, stockRows), [cart, stockRows]);
  const visibleGroups = useMemo(() => searchProductGroups(groups, itemSearch), [groups, itemSearch]);
  const renderedGroups = useMemo(() => visibleGroups.slice(0, MAX_VISIBLE_GROUPS), [visibleGroups]);
  const filteredItems = useMemo(
    () => (selectedGroup ? items.filter((item) => item.root_stock_group === selectedGroup.name) : items),
    [items, selectedGroup],
  );
  const visibleItems = useMemo(() => searchItemsForMobile(filteredItems, itemSearch), [filteredItems, itemSearch]);
  const renderedItems = useMemo(() => visibleItems.slice(0, MAX_VISIBLE_ITEMS), [visibleItems]);
  const resend = otpResendState({ lastSentAtMs: otpSentAtMs, nowMs: Date.now(), waitSeconds: otpCooldownSeconds });
  const currentOtpIdentityType = customerAuthIntent === 'signup' ? 'Customer' : otpIdentityType || 'Customer';
  const currentOtpRequestKey = otpRequestKey({ mode: currentOtpIdentityType, mobileNumber, customerAuthIntent });
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
      setCatalogLoadedKey(null);
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

  function chooseGroup(group: ProductGroup | null) {
    setSelectedGroup(group);
  }

  async function chooseItem(item: TallyItem) {
    try {
      setSelectedItem(item);
      setStockRows(await api.itemStock(activeCustomer(), item.name, activeSalesEmployeeContext()));
      setQuantity('1');
      setGodownSelectorOpen(true);
    } catch (error) {
      const failure = classifyApiFailure(error);
      setSystemState(failure);
    }
  }

  async function chooseCustomer(customer: AllowedCustomer) {
    setSelectedCustomer(customer);
    setSelectedGroup(null);
    setItemSearch('');
    await loadCatalogForCustomer(customer.customer, activeSalesEmployeeIdentity());
    setStep('groups');
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
    setCart((current) => removeAllocation(current, { item, godown: undefined }));
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
    if (!resend.canResend) return;
    try {
      if (canUseOtpResend) {
        const identityType = currentOtpIdentityType;
        const response = await api.resendOtp(mobileNumber, identityType);
        setOtpCooldownSeconds(otpCooldownSecondsFromResponse(response, otpCooldownSeconds));
        setOtpSentAtMs(Date.now());
        setLastOtpRequestKey(currentOtpRequestKey);
        setOtpCode('');
        showToast('success', 'OTP resent', `A new code was sent to ${mobileNumber}.`);
        return;
      }
      if (customerAuthIntent === 'login') {
        const response = await requestInferredSignInOtp(mobileNumber);
        const inferredIdentityType = response.identity_type as Mode;
        setMode(inferredIdentityType);
        setOtpIdentityType(inferredIdentityType);
        setOtpCooldownSeconds(otpCooldownSecondsFromResponse(response, otpCooldownSeconds));
        setOtpSentAtMs(Date.now());
        setLastOtpRequestKey(otpRequestKey({ mode: inferredIdentityType, mobileNumber, customerAuthIntent }));
        setOtpCode('');
        showToast('success', 'Sign in OTP sent', `Enter the code sent to ${mobileNumber}.`);
        return;
      }
      const signupInput = {
        customerName: signupCustomerName,
        businessLegalName: signupBusinessLegalName,
        gstin: signupGstin,
        mobileNumber,
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
      setLastOtpRequestKey(currentOtpRequestKey);
      setOtpCode('');
      showToast('success', 'Sign up OTP sent', `Enter the code sent to ${mobileNumber}.`);
    } catch (error) {
      const failure = classifyApiFailure(error);
      setSystemState(failure);
    }
  }

  async function verifyOtp() {
    try {
      if (otpIdentityType === 'Sales Employee') {
        const response = await api.verifySalesEmployeeOtp(mobileNumber, otpCode);
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
      const response = await api.verifyCustomerOtp(mobileNumber, otpCode);
      const route = await customerOtpRouteAfterAccessCheck({
        otpResponse: response,
        customerAccessStatus: api.customerAccessStatus,
      });
      if (route.session) {
        await setSession(route.session);
        setSystemState({ kind: 'idle' });
        setStep(route.step as Step);
        showToast('success', 'Signed in', 'Your account is ready for ordering.');
        return;
      }
      setSystemState({ kind: 'idle' });
      setStep(route.step as Step);
      showToast('info', customerAuthIntent === 'signup' ? 'Sign up received' : 'Sign in pending', 'Access must be active before ordering.');
    } catch (error) {
      const failure = classifyApiFailure(error);
      setSystemState(failure);
    }
  }

  async function requestInferredSignInOtp(number: string) {
    try {
      return await api.startCustomerOtp(number);
    } catch (error) {
      const failure = classifyApiFailure(error);
      if (!shouldTrySalesEmployeeOtpAfterCustomerOtpError(failure.message)) {
        throw error;
      }
      return api.startSalesEmployeeOtp(number);
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
    setSelectedCustomer(null);
    setSelectedGroup(null);
    setSelectedItem(null);
    setCatalogLoadedKey(null);
    setGodownSelectorOpen(false);
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
    setCatalogLoadedKey(null);
    setStep('customer');
  }

  async function showHistory() {
    if (!hasActiveModeSession) {
      setSystemState({ kind: 'validation_error', message: 'Verify OTP before loading account data.' });
      return;
    }
    setHistoryRows(
      mode === 'Sales Employee'
        ? await api.orderHistory(undefined, activeSalesEmployeeIdentity())
        : await api.orderHistory(activeCustomerIdentity()),
    );
    setStep('history');
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
  }

  async function showOrderDetail(order: OrderSummary) {
    setOrderDetail(
      await api.orderDetail(
        order.name,
        mode === 'Sales Employee'
          ? { salesEmployee: activeSalesEmployeeIdentity() }
          : { customer: activeCustomerIdentity() },
      ),
    );
    setStep('detail');
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
    mode, setMode,
    step, setStep,
    groups,
    items,
    stockRows,
    customers,
    selectedCustomer,
    selectedGroup,
    selectedItem,
    godownSelectorOpen, setGodownSelectorOpen,
    cart,
    draftCarts,
    draftCartsExpanded, setDraftCartsExpanded,
    salesNote, setSalesNote,
    customerSearch, setCustomerSearch,
    itemSearch, setItemSearch,
    quantity, setQuantity,
    mobileNumber, setMobileNumber,
    otpCode, setOtpCode,
    customerAuthIntent, setCustomerAuthIntent,
    otpIdentityType, setOtpIdentityType,
    signupDetailsReview, setSignupDetailsReview,
    signupCustomerName, setSignupCustomerName,
    signupBusinessLegalName, setSignupBusinessLegalName,
    signupGstin, setSignupGstin,
    signupEmailId, setSignupEmailId,
    signupDateOfBirth,
    signupDateOfAnniversary,
    setOtpSentAtMs,
    setLastOtpRequestKey,
    reference,
    historyRows,
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
    // handlers
    chooseGroup,
    chooseItem,
    chooseCustomer,
    chooseDraftCart,
    clearDraftCart,
    customerForDraftCart,
    addFromGodown,
    backToItems,
    changeCartQuantity,
    removeCartItem,
    submitOrder,
    requestOtp,
    verifyOtp,
    switchMode,
    showOrder,
    switchCustomer,
    showHistory,
    showProfile,
    saveCustomerProfile,
    showOrderDetail,
    revokeAndLogout,
    handleDatePickerChange,
    editSignupDetails,
  };
}
