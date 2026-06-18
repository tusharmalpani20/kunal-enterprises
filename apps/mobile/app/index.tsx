import React, { useCallback, useContext, useEffect, useMemo, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import DateTimePicker, { type DateTimePickerEvent } from '@react-native-community/datetimepicker';
import { Alert, Modal, Platform, Pressable, SafeAreaView, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Check, ChevronLeft, ChevronRight, History, LogOut, Minus, Plus, Search, ShoppingBag, ShoppingCart, Trash2, UserRound } from 'lucide-react-native';
import Toast from 'react-native-toast-message';

import { createMobileApi } from '../src/api/mobileApi';
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
} from '../src/domain/authAccessFlow.mjs';
import { activeIdentityForMode, authHeadersForSession, canUseProtectedMobileApi, restoredSessionRoute } from '../src/domain/sessionFlow.mjs';
import {
  addAllocation,
  buildCustomerOrderPayload,
  buildConfirmationNotes,
  customerOrderGuard,
  finalizeOrderSubmission,
  formatSyncTimestampForMobile,
  orderTotals,
  parseOrderQuantityInput,
  prepareStockReviewBeforeSubmit,
  removeAllocation,
  searchItemsForMobile,
  stockRowDetailForMobile,
  updateAllocationQuantity,
} from '../src/domain/mobileFlow.mjs';
import { buildSalesEmployeeOrderPayload, salesEmployeeOrderGuard } from '../src/domain/salesEmployeeFlow.mjs';
import { loadProfileForMobile, saveCustomerProfileForMobile } from '../src/domain/profileHistoryFlow.mjs';
import { orderHeaderSubtitle, pendingAccessMessage } from '../src/domain/screenCopy.mjs';
import { classifyApiFailure, requestBanner } from '../src/domain/sharedStateFlow.mjs';
import { AuthContext } from '../src/providers/auth';
import { useFrappe } from '../src/providers/frappe';
import { cartKeyForOrderContext, cartOwnerKeyForSession, clearAllCarts, clearCart, ensureCartOwner, listSalesEmployeeDraftCarts, loadCart, saveCart } from '../src/storage/mobileStorage';
import type { AllowedCustomer, CartAllocation, ItemStock, OrderDetail, OrderSummary, ProductGroup, TallyItem } from '../src/types';

type Step = 'auth' | 'pending' | 'customer' | 'groups' | 'summary' | 'success' | 'history' | 'detail' | 'profile';
type AppSection = 'order' | 'history' | 'profile';
type Mode = 'Customer' | 'Sales Employee';
type DatePickerTarget = 'signupDateOfBirth' | 'signupDateOfAnniversary' | 'profileBirthDate' | 'profileAnniversaryDate';
type ToastKind = 'success' | 'error' | 'info';
type DraftCartSummary = { customer: string; rowCount: number; totalQuantity: number };
const fonts = {
  regular: 'Figtree_400Regular',
  medium: 'Figtree_500Medium',
  semibold: 'Figtree_600SemiBold',
};
const MAX_VISIBLE_GROUPS = 40;
const MAX_VISIBLE_ITEMS = 60;

function showToast(type: ToastKind, text1: string, text2?: string) {
  Toast.show({
    type,
    text1,
    text2,
    position: 'top',
    visibilityTime: type === 'error' ? 5000 : 3000,
  });
}

function RequiredFieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <Text style={styles.fieldLabel}>
      {children}
      <Text style={styles.requiredAsterisk}> *</Text>
    </Text>
  );
}

export default function CustomerOrderScreen() {
  const { call, callAccessToken } = useFrappe();
  const { logout, session, setSession } = useContext(AuthContext);
  const api = useMemo(() => createMobileApi({ call }), [call]);
  const [mode, setMode] = useState<Mode>('Customer');
  const [step, setStep] = useState<Step>('auth');
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
        showToast('error', 'Unable to load catalog', failure.message || 'Try again after checking your connection.');
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
      showToast('error', 'Unable to load godowns', failure.message || 'Try again after checking your connection.');
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
      showToast('error', 'Unable to open draft cart', failure.message || 'Try again after checking your connection.');
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
        showToast('error', 'Signup details missing', validation.message);
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
      showToast('error', 'OTP request failed', failure.message || 'Try again after checking the details.');
    }
  }

  async function verifyOtp() {
    try {
      if (otpIdentityType === 'Sales Employee') {
        const response = await api.verifySalesEmployeeOtp(mobileNumber, otpCode);
        const session = salesEmployeeSessionFromOtpResponse(response);
        const nextStep = nextAuthStepFromSalesEmployeeOtp(response);
        if (session) {
          await setSession(session);
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
      showToast('error', 'OTP verification failed', failure.message || 'Check the code and try again.');
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
    setStep('auth');
    setCart([]);
    setCatalogLoadedKey(null);
    setGroups([]);
    setItems([]);
    setReference(null);
    setOrderDetail(null);
  }

  const isAuthSurface = step === 'auth' || step === 'pending';
  const appSection: AppSection = step === 'history' || step === 'detail' ? 'history' : step === 'profile' ? 'profile' : 'order';
  const isOrderSection = appSection === 'order';
  const showCartControls = isOrderSection && !(mode === 'Sales Employee' && step === 'customer');
  const otpRequestedForCurrentFlow = Boolean(otpSentAtMs && lastOtpRequestKey === currentOtpRequestKey);
  const isSignupOtpFlow = customerAuthIntent === 'signup' && otpRequestedForCurrentFlow;
  const showSignupDetails = customerAuthIntent === 'signup' && (!isSignupOtpFlow || signupDetailsReview);
  const signupDetailsReadOnly = isSignupOtpFlow && signupDetailsReview;
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

  return (
    <SafeAreaView style={styles.shell}>
      <ScrollView contentContainerStyle={[styles.page, isAuthSurface && styles.authPage]}>
        {requestBanner(systemState) && (
          <View style={styles.banner}>
            <Text style={styles.bannerTitle}>{requestBanner(systemState)?.title}</Text>
            <Text style={styles.bannerText}>{requestBanner(systemState)?.message}</Text>
          </View>
        )}

        {isAuthSurface ? (
          <View style={styles.authHeader}>
            <Text style={styles.brandMark}>Kunal Enterprises</Text>
            <Text style={styles.authTitle}>
              {step === 'pending'
                ? 'Request received'
                : customerAuthIntent === 'signup'
                  ? 'Create your account'
                  : 'Sign in to order'}
            </Text>
            {step === 'pending' && (
              <Text style={styles.authSubtitle}>Ordering unlocks after approval.</Text>
            )}
          </View>
        ) : (
          <>
            <View style={styles.appHeader}>
              <View style={styles.appHeaderText}>
                <Text style={styles.kicker}>{mode === 'Customer' ? 'Customer order' : 'Sales employee order'}</Text>
                <Text style={styles.title}>Kunal Enterprises</Text>
                {/* <Text style={styles.subtitle}>{orderHeaderSubtitle({ mode, selectedCustomer })}</Text> */}
              </View>
              {appSection === 'profile' && (
                <Pressable style={styles.iconOnlyButton} onPress={revokeAndLogout}>
                  <LogOut size={17} color="#111111" />
                </Pressable>
              )}
            </View>

            <View style={styles.tabBar}>
              <TopLevelTab
                label="Order"
                active={appSection === 'order'}
                icon={<ShoppingBag size={16} color={appSection === 'order' ? '#ffffff' : '#111111'} />}
                onPress={showOrder}
              />
              <TopLevelTab
                label="History"
                active={appSection === 'history'}
                icon={<History size={16} color={appSection === 'history' ? '#ffffff' : '#111111'} />}
                onPress={showHistory}
              />
              <TopLevelTab
                label="Profile"
                active={appSection === 'profile'}
                icon={<UserRound size={16} color={appSection === 'profile' ? '#ffffff' : '#111111'} />}
                onPress={showProfile}
              />
            </View>

            {showCartControls && (
              <View style={styles.statusStrip}>
                <View>
                  <Text style={styles.metricLabel}>Cart quantity</Text>
                  <Text style={styles.metric}>{totals.totalQuantity}</Text>
                </View>
                <View>
                  <Text style={styles.metricLabel}>Rows</Text>
                  <Text style={styles.metric}>{totals.rowCount}</Text>
                </View>
              </View>
            )}
            {showCartControls && (
              <View style={styles.actionRow}>
                {mode === 'Sales Employee' && selectedCustomer && (
                  <Pressable style={styles.secondaryAction} onPress={switchCustomer}>
                    <UserRound size={16} color="#111111" />
                    <Text style={styles.secondaryActionText}>Switch customer</Text>
                  </Pressable>
                )}
                <Pressable
                  style={[styles.secondaryAction, totals.rowCount === 0 && styles.disabledAction]}
                  disabled={totals.rowCount === 0}
                  onPress={() => setStep('summary')}
                >
                  <ShoppingCart size={16} color={totals.rowCount === 0 ? '#8a8a8a' : '#111111'} />
                  <Text style={[styles.secondaryActionText, totals.rowCount === 0 && styles.disabledActionText]}>
                    {totals.rowCount === 0 ? 'Cart is empty' : 'Review order'}
                  </Text>
                </Pressable>
              </View>
            )}
          </>
        )}

        {step === 'auth' && (
          <View style={styles.authForm}>
            {(!isSignupOtpFlow || signupDetailsReview) && (
              <>
                <RequiredFieldLabel>Mobile Number</RequiredFieldLabel>
                <TextInput
                  value={mobileNumber}
                  onChangeText={setMobileNumber}
                  editable={!signupDetailsReadOnly}
                  keyboardType="phone-pad"
                  placeholder="Enter mobile number"
                  placeholderTextColor="#9a9a9a"
                  style={[styles.input, signupDetailsReadOnly && styles.readOnlyInput]}
                />
              </>
            )}
            {showSignupDetails && (
              <>
                <RequiredFieldLabel>Customer Name</RequiredFieldLabel>
                <TextInput
                  value={signupCustomerName}
                  onChangeText={setSignupCustomerName}
                  editable={!signupDetailsReadOnly}
                  placeholder="Enter customer name"
                  placeholderTextColor="#9a9a9a"
                  style={[styles.input, signupDetailsReadOnly && styles.readOnlyInput]}
                />
                <RequiredFieldLabel>Business / Legal Name</RequiredFieldLabel>
                <TextInput
                  value={signupBusinessLegalName}
                  onChangeText={setSignupBusinessLegalName}
                  editable={!signupDetailsReadOnly}
                  placeholder="Enter business or legal name"
                  placeholderTextColor="#9a9a9a"
                  style={[styles.input, signupDetailsReadOnly && styles.readOnlyInput]}
                />
                <RequiredFieldLabel>GSTIN</RequiredFieldLabel>
                <TextInput
                  value={signupGstin}
                  onChangeText={setSignupGstin}
                  editable={!signupDetailsReadOnly}
                  autoCapitalize="characters"
                  placeholder="Enter GSTIN"
                  placeholderTextColor="#9a9a9a"
                  style={[styles.input, signupDetailsReadOnly && styles.readOnlyInput]}
                />
                <RequiredFieldLabel>Email ID</RequiredFieldLabel>
                <TextInput
                  value={signupEmailId}
                  onChangeText={setSignupEmailId}
                  editable={!signupDetailsReadOnly}
                  keyboardType="email-address"
                  autoCapitalize="none"
                  placeholder="Enter email address"
                  placeholderTextColor="#9a9a9a"
                  style={[styles.input, signupDetailsReadOnly && styles.readOnlyInput]}
                />
                <RequiredFieldLabel>Date of Birth</RequiredFieldLabel>
                <DatePickerButton
                  value={signupDateOfBirth}
                  placeholder="DD-MM-YYYY"
                  disabled={signupDetailsReadOnly}
                  onPress={() => setDatePickerTarget('signupDateOfBirth')}
                />
                <Text style={styles.fieldLabel}>Date of Anniversary</Text>
                <DatePickerButton
                  value={signupDateOfAnniversary}
                  placeholder="DD-MM-YYYY"
                  disabled={signupDetailsReadOnly}
                  onPress={() => setDatePickerTarget('signupDateOfAnniversary')}
                />
              </>
            )}
            {otpRequestedForCurrentFlow && !signupDetailsReview && (
              <>
                {isSignupOtpFlow && (
                  <Pressable style={styles.backButton} onPress={() => setSignupDetailsReview(true)}>
                    <ChevronLeft size={16} color="#111111" />
                    <Text style={styles.backButtonText}>Back to details</Text>
                  </Pressable>
                )}
                <Text style={styles.fieldLabel}>OTP</Text>
                <TextInput
                  value={otpCode}
                  onChangeText={(value) => setOtpCode(value.toUpperCase())}
                  autoCapitalize="characters"
                  autoCorrect={false}
                  placeholder="Enter WhatsApp OTP"
                  placeholderTextColor="#9a9a9a"
                  style={styles.input}
                />
              </>
            )}
            {signupDetailsReadOnly ? (
              <View style={styles.authSplitActions}>
                <Pressable style={[styles.secondaryAction, styles.authSecondaryAction]} onPress={editSignupDetails}>
                  <Text style={styles.secondaryActionText}>Edit details</Text>
                </Pressable>
                <Pressable style={[styles.primaryAction, styles.authInlinePrimaryAction]} onPress={() => setSignupDetailsReview(false)}>
                  <Text style={styles.primaryActionText}>Continue to OTP</Text>
                </Pressable>
              </View>
            ) : (
              <Pressable style={[styles.primaryAction, styles.authPrimaryAction]} onPress={otpRequestedForCurrentFlow ? verifyOtp : requestOtp}>
                <Text style={styles.primaryActionText}>
                  {otpRequestedForCurrentFlow
                    ? 'Verify OTP'
                    : customerAuthIntent === 'signup'
                      ? 'Send OTP and create request'
                      : 'Send OTP'}
                </Text>
              </Pressable>
            )}
            {otpRequestedForCurrentFlow && !signupDetailsReview && (
              <Pressable style={styles.textAction} onPress={requestOtp}>
                <Text style={styles.textActionText}>
                  {resend.canResend ? 'Resend OTP' : `Resend available in ${resend.secondsRemaining}s`}
                </Text>
              </Pressable>
            )}
            <Pressable
              style={styles.authTextAction}
              onPress={() => {
                setCustomerAuthIntent(customerAuthIntent === 'signup' ? 'login' : 'signup');
                setMode('Customer');
                setOtpIdentityType(null);
                setSignupDetailsReview(false);
                setOtpSentAtMs(null);
                setLastOtpRequestKey(null);
                setOtpCode('');
                setSystemState({ kind: 'idle' });
              }}
            >
              <Text style={styles.textActionText}>
                {customerAuthIntent === 'signup' ? 'Already have access? Sign in' : 'New customer? Create account'}
              </Text>
            </Pressable>
          </View>
        )}

        {step === 'pending' && (
          <Workspace title="Access Pending" icon={<Check size={18} color="#111111" />}>
            <Text style={styles.rowTitle}>Pending Admin Review</Text>
            <Text style={styles.rowDetail}>{pendingAccessMessage()}</Text>
          </Workspace>
        )}

        {step === 'customer' && (
          <Workspace title="Select Customer">
            {draftCarts.length > 0 && (
              <View style={styles.draftCartSection}>
                <View style={styles.openCartsWidget}>
                  <Pressable style={styles.openCartsHeader} onPress={() => setDraftCartsExpanded((current) => !current)}>
                    <View>
                      <Text style={styles.rowTitle}>Open carts</Text>
                      <Text style={styles.rowDetail}>
                        {draftCarts.length} {draftCarts.length === 1 ? 'draft' : 'drafts'} saved
                      </Text>
                    </View>
                    <ChevronRight
                      size={18}
                      color="#111111"
                      style={draftCartsExpanded && styles.chevronExpanded}
                    />
                  </Pressable>
                  {draftCartsExpanded &&
                    draftCarts.map((draft) => {
                      const customer = customerForDraftCart(draft);
                      return (
                        <DraftCartRow
                          key={draft.customer}
                          title={customer?.customer_name || draft.customer}
                          detail={`${draft.rowCount} ${draft.rowCount === 1 ? 'row' : 'rows'} · total quantity ${draft.totalQuantity}`}
                          onOpen={() => chooseDraftCart(draft)}
                          onClear={() => clearDraftCart(draft)}
                        />
                      );
                    })}
                </View>
              </View>
            )}
            <TextInput
              value={customerSearch}
              onChangeText={setCustomerSearch}
              placeholder="Search customer"
              placeholderTextColor="#9a9a9a"
              style={styles.input}
            />
            {customers.map((customer) => (
              <RowButton
                key={customer.customer}
                title={customer.customer_name}
                detail={customer.business_legal_name}
                onPress={() => chooseCustomer(customer)}
              />
            ))}
          </Workspace>
        )}

        {step === 'groups' && (
          <Workspace title="Order" icon={<Search size={18} color="#111111" />}>
            <View style={styles.searchPanel}>
              <Text style={styles.fieldLabel}>Search products</Text>
              <TextInput
                value={itemSearch}
                onChangeText={setItemSearch}
                placeholder="Search item or product group"
                style={styles.input}
              />
            </View>
            <Text style={styles.fieldLabel}>Product groups ({groups.length})</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.groupChips}>
              <Pressable style={[styles.groupChip, !selectedGroup && styles.groupChipActive]} onPress={() => chooseGroup(null)}>
                <Text style={[styles.groupChipText, !selectedGroup && styles.groupChipTextActive]}>All</Text>
              </Pressable>
              {renderedGroups.map((group) => (
                <Pressable
                  key={group.name}
                  style={[styles.groupChip, selectedGroup?.name === group.name && styles.groupChipActive]}
                  onPress={() => chooseGroup(group)}
                >
                  <Text style={[styles.groupChipText, selectedGroup?.name === group.name && styles.groupChipTextActive]}>
                    {group.group_name}
                  </Text>
                </Pressable>
              ))}
            </ScrollView>
            {renderedItems.map((item: TallyItem) => (
              <ItemSearchRow
                key={item.name}
                item={item}
                cartQuantity={cartQuantityForItem(cart, item.name)}
                onPress={() => chooseItem(item)}
              />
            ))}
            {visibleItems.length === 0 && (
              <Text style={styles.helperText}>No items match this search and product group filter.</Text>
            )}
            {visibleItems.length > renderedItems.length && (
              <Text style={styles.helperText}>
                Showing {renderedItems.length} of {visibleItems.length} matches. Refine search to narrow results.
              </Text>
            )}
          </Workspace>
        )}

        {step === 'summary' && (
          <Workspace title="Order Summary" icon={<Check size={18} color="#111111" />}>
            <BackButton label="Back to product search" onPress={backToItems} />
            {mode === 'Sales Employee' && selectedCustomer && (
              <View style={styles.contextBlock}>
                <Text style={styles.fieldLabel}>Customer</Text>
                <Text style={styles.rowTitle}>{selectedCustomer.customer_name}</Text>
                <Text style={styles.rowDetail}>{selectedCustomer.business_legal_name}</Text>
                <Text style={styles.fieldLabel}>Internal note</Text>
                <TextInput
                  value={salesNote}
                  onChangeText={setSalesNote}
                  placeholder="Add dispatch note for internal team"
                  placeholderTextColor="#9a9a9a"
                  style={styles.input}
                />
              </View>
            )}
            {cart.map((row) => (
              <View key={`${row.item}:${row.godown}`} style={styles.summaryLine}>
                <View style={styles.summaryItemText}>
                  <Text style={[styles.rowTitle, styles.summaryItemTitle]}>{row.itemName}</Text>
                  <Text style={styles.rowDetail}>{row.godown}</Text>
                </View>
                <View style={styles.cartControls}>
                  <Pressable style={styles.iconButton} onPress={() => changeCartQuantity(row, -1)}>
                    <Minus size={16} color="#111111" />
                  </Pressable>
                  <Text style={styles.quantity}>{row.quantity}</Text>
                  <Pressable style={styles.iconButton} onPress={() => changeCartQuantity(row, 1)}>
                    <Plus size={16} color="#111111" />
                  </Pressable>
                  <Pressable style={styles.iconButton} onPress={() => removeCartItem(row.item)}>
                    <Trash2 size={16} color="#111111" />
                  </Pressable>
                </View>
              </View>
            ))}
            {notes.map((note) => (
              <Text key={note} style={styles.note}>{note}</Text>
            ))}
            <Pressable style={styles.primaryAction} onPress={submitOrder}>
              <Text style={styles.primaryActionText}>Confirm order</Text>
            </Pressable>
          </Workspace>
        )}

        {step === 'success' && (
          <Workspace title="Order Placed" icon={<Check size={18} color="#111111" />}>
            <Text style={styles.successRef}>{reference}</Text>
            <Text style={styles.rowDetail}>WhatsApp confirmation and PDF are queued for the Customer.</Text>
            <Pressable style={styles.primaryAction} onPress={showOrder}>
              <Text style={styles.primaryActionText}>Place another order</Text>
            </Pressable>
          </Workspace>
        )}

        {step === 'history' && (
          <Workspace title="Order History" icon={<History size={18} color="#111111" />}>
            {historyRows.map((order) => (
              <RowButton
                key={order.name}
                title={order.portal_reference_number}
                detail={orderHistoryRowDetail(order, mode)}
                onPress={() => showOrderDetail(order)}
              />
            ))}
          </Workspace>
        )}

        {step === 'detail' && orderDetail && (
          <Workspace title="Order Detail" icon={<History size={18} color="#111111" />}>
            <BackButton label="Order History" onPress={showHistory} />
            <Text style={styles.successRef}>{orderDetail.portal_reference_number}</Text>
            <Text style={styles.rowDetail}>{orderDetail.display_status || orderDetail.status}</Text>
            <Text style={styles.rowDetail}>Placed by {orderDetail.placed_by_label || orderDetail.placed_by || 'You'}</Text>
            {(orderDetail.godown_allocations || []).map((allocation) => (
              <View key={`${allocation.item}:${allocation.godown}`} style={styles.summaryLine}>
                <View>
                  <Text style={styles.rowTitle}>{allocation.item}</Text>
                  <Text style={styles.rowDetail}>{allocation.godown}</Text>
                </View>
                <Text style={styles.quantity}>{allocation.requested_quantity}</Text>
              </View>
            ))}
          </Workspace>
        )}

        {step === 'profile' && profile && (
          <Workspace title="Profile" icon={<UserRound size={18} color="#111111" />}>
            {mode === 'Customer' && (
              <View style={styles.contextBlock}>
                <ProfileReadOnlyField label="Customer Name" value={profile.customer_name} />
                <ProfileReadOnlyField label="Business / Legal Name" value={profile.business_legal_name} />
                <ProfileReadOnlyField label="Mobile Number" value={profile.mobile_number} />
                <Text style={styles.fieldLabel}>Email</Text>
                <TextInput value={profileEmail} onChangeText={setProfileEmail} style={styles.input} />
                <Text style={styles.fieldLabel}>Date of Birth</Text>
                <DatePickerButton
                  value={profileBirthDate}
                  placeholder="DD-MM-YYYY"
                  onPress={() => setDatePickerTarget('profileBirthDate')}
                />
                <Text style={styles.fieldLabel}>Date of Anniversary</Text>
                <DatePickerButton
                  value={profileAnniversaryDate}
                  placeholder="DD-MM-YYYY"
                  onPress={() => setDatePickerTarget('profileAnniversaryDate')}
                />
                <Pressable style={styles.primaryAction} onPress={saveCustomerProfile}>
                  <Text style={styles.primaryActionText}>Save profile</Text>
                </Pressable>
              </View>
            )}
            {mode === 'Sales Employee' && (
              <View style={styles.contextBlock}>
                <ProfileReadOnlyField label="Sales Employee Name" value={profile.sales_employee_name} />
                <ProfileReadOnlyField label="Employee Code" value={profile.employee_code} />
                <ProfileReadOnlyField label="Mobile Number" value={profile.mobile_number} />
                <ProfileReadOnlyField label="Status" value={profile.status} />
              </View>
            )}
          </Workspace>
        )}
      </ScrollView>
      {!isAuthSurface && isOrderSection && step !== 'summary' && totals.rowCount > 0 && (
        <Pressable style={styles.cartBar} onPress={() => setStep('summary')}>
          <View>
            <Text style={styles.cartBarTitle}>{totals.rowCount} items in cart</Text>
            <Text style={styles.cartBarText}>Total quantity {totals.totalQuantity}</Text>
          </View>
          <View style={styles.cartBarAction}>
            <ShoppingCart size={16} color="#ffffff" />
            <Text style={styles.cartBarActionText}>Review</Text>
          </View>
        </Pressable>
      )}
      <Modal visible={godownSelectorOpen} transparent animationType="slide" onRequestClose={() => setGodownSelectorOpen(false)}>
        <View style={styles.modalOverlay}>
          <Pressable style={styles.modalScrim} onPress={() => setGodownSelectorOpen(false)} />
          <View style={styles.bottomSheet}>
            <View style={styles.sheetHandle} />
            <Text style={styles.workspaceTitle}>{selectedItem?.item_name || 'Select godown'}</Text>
            <Text style={styles.rowDetail}>{selectedItem?.root_stock_group} · {selectedItem?.uom}</Text>
            <Text style={styles.fieldLabel}>Quantity</Text>
            <TextInput value={quantity} onChangeText={setQuantity} keyboardType="numeric" style={styles.input} />
            <Text style={styles.fieldLabel}>Godown stock</Text>
            {stockRows.map((stock) => (
              <RowButton
                key={stock.godown}
                title={stock.godown}
                detail={godownStockDetailForSelection(stock, quantity)}
                onPress={() => addFromGodown(stock)}
                tone={Number(quantity) > stock.quantity ? 'warn' : 'default'}
              />
            ))}
          </View>
        </View>
      </Modal>
      <Modal visible={Boolean(datePickerTarget)} transparent animationType="slide" onRequestClose={() => setDatePickerTarget(null)}>
        <View style={styles.modalOverlay}>
          <Pressable style={styles.modalScrim} onPress={() => setDatePickerTarget(null)} />
          <View style={styles.bottomSheet}>
            <View style={styles.sheetHandle} />
            <Text style={styles.workspaceTitle}>Select date</Text>
            <Text style={styles.rowDetail}>{formatIndianDate(activeDatePickerValue) || 'DD-MM-YYYY'}</Text>
            {datePickerTarget && (
              <View style={styles.datePickerFrame}>
                <DateTimePicker
                  value={activeDatePickerDate}
                  mode="date"
                  display={Platform.OS === 'ios' ? 'spinner' : 'default'}
                  locale="en-IN"
                  onChange={handleDatePickerChange}
                  style={styles.nativeDatePicker}
                />
              </View>
            )}
            {Platform.OS === 'ios' && (
              <Pressable style={styles.primaryAction} onPress={() => setDatePickerTarget(null)}>
                <Text style={styles.primaryActionText}>Done</Text>
              </Pressable>
            )}
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function Workspace({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <View style={styles.workspace}>
      <View style={styles.workspaceHeader}>
        {icon}
        <Text style={styles.workspaceTitle}>{title}</Text>
      </View>
      {children}
    </View>
  );
}

function DraftCartRow({
  title,
  detail,
  onOpen,
  onClear,
}: {
  title: string;
  detail: string;
  onOpen: () => void;
  onClear: () => void;
}) {
  return (
    <View style={styles.draftCartRow}>
      <Pressable style={styles.draftCartOpen} onPress={onOpen}>
        <View style={styles.rowButtonTextBlock}>
          <Text style={styles.rowTitle}>{title}</Text>
          <Text style={styles.rowDetail}>{detail}</Text>
        </View>
        <View style={styles.rowChevron}>
          <ChevronRight size={18} color="#111111" />
        </View>
      </Pressable>
      <Pressable style={styles.draftCartClear} onPress={onClear}>
        <Trash2 size={15} color="#b42318" />
        <Text style={styles.draftCartClearText}>Clear</Text>
      </Pressable>
    </View>
  );
}

function BackButton({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <Pressable style={styles.backButton} onPress={onPress}>
      <ChevronLeft size={16} color="#111111" />
      <Text style={styles.backButtonText}>{label}</Text>
    </Pressable>
  );
}

function DatePickerButton({
  value,
  placeholder,
  disabled = false,
  onPress,
}: {
  value: string;
  placeholder: string;
  disabled?: boolean;
  onPress: () => void;
}) {
  const displayValue = formatIndianDate(value);
  return (
    <Pressable style={[styles.datePickerButton, disabled && styles.readOnlyInput]} disabled={disabled} onPress={onPress}>
      <Text style={[styles.datePickerText, !displayValue && styles.placeholderText]}>{displayValue || placeholder}</Text>
    </Pressable>
  );
}

function ProfileReadOnlyField({ label, value }: { label: string; value: unknown }) {
  return (
    <>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        value={String(value || '')}
        editable={false}
        placeholder="-"
        placeholderTextColor="#9a9a9a"
        style={[styles.input, styles.readOnlyInput]}
      />
    </>
  );
}

function TopLevelTab({
  label,
  active,
  icon,
  onPress,
}: {
  label: string;
  active: boolean;
  icon: React.ReactNode;
  onPress: () => void;
}) {
  return (
    <Pressable style={[styles.tabButton, active && styles.tabButtonActive]} onPress={onPress}>
      {icon}
      <Text style={[styles.tabButtonText, active && styles.tabButtonTextActive]}>{label}</Text>
    </Pressable>
  );
}

function RowButton({
  title,
  detail,
  onPress,
  tone = 'default',
}: {
  title: string;
  detail: string;
  onPress: () => void;
  tone?: 'default' | 'warn';
}) {
  return (
    <Pressable style={[styles.rowButton, tone === 'warn' && styles.warningRow]} onPress={onPress}>
      <View style={styles.rowButtonTextBlock}>
        <Text style={[styles.rowTitle, tone === 'warn' && styles.warningTitle]}>{title}</Text>
        <Text style={[styles.rowDetail, tone === 'warn' && styles.warningDetail]}>{detail}</Text>
      </View>
      <View style={styles.rowChevron}>
        <ChevronRight size={18} color={tone === 'warn' ? '#c2410c' : '#111111'} />
      </View>
    </Pressable>
  );
}

function ItemSearchRow({
  item,
  cartQuantity,
  onPress,
}: {
  item: TallyItem;
  cartQuantity: number;
  onPress: () => void;
}) {
  return (
    <Pressable style={styles.itemRow} onPress={onPress}>
      <View style={styles.itemRowText}>
        <Text style={styles.rowTitle}>{item.item_name}</Text>
        <Text style={styles.rowDetail}>{item.root_stock_group} · {item.uom}</Text>
        <Text style={styles.rowDetail}>Stock {item.total_closing_balance}</Text>
      </View>
      <View style={[styles.itemAddPill, cartQuantity > 0 && styles.itemAddPillActive]}>
        <Text style={[styles.itemAddPillText, cartQuantity > 0 && styles.itemAddPillTextActive]}>
          {cartQuantity > 0 ? `Qty ${cartQuantity}` : 'Add'}
        </Text>
      </View>
    </Pressable>
  );
}

function searchProductGroups(groups: ProductGroup[], search: string) {
  const query = search.trim().toLowerCase();
  if (!query) {
    return groups;
  }
  return groups.filter((group) =>
    [group.group_name, group.full_path, group.name].some((value) => String(value || '').toLowerCase().includes(query)),
  );
}

function uniqueItemsByName(items: TallyItem[]) {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.name)) {
      return false;
    }
    seen.add(item.name);
    return true;
  });
}

function cartQuantityForItem(cart: CartAllocation[], item: string) {
  return cart.filter((row) => row.item === item).reduce((total, row) => total + row.quantity, 0);
}

function orderHistoryRowDetail(order: OrderSummary, mode: Mode) {
  const statusLine = `${order.display_status || order.status} · Quantity ${order.total_quantity || 0}`;
  if (mode !== 'Sales Employee') {
    return statusLine;
  }
  return `${order.customer_name || order.customer} · ${statusLine}`;
}

function godownStockDetailForSelection(stock: ItemStock, requestedQuantityInput: string) {
  const requestedQuantity = Number(requestedQuantityInput);
  const uom = stock.uom || '';
  if (Number.isFinite(requestedQuantity) && requestedQuantity > stock.quantity) {
    const syncStamp = formatSyncTimestampForMobile(stock.synced_at || stock.as_on_date);
    return `Only ${stock.quantity} ${uom} here · requested ${requestedQuantity}\nSync ${syncStamp}`.trim();
  }
  return stockRowDetailForMobile(stock);
}

function dateFromIsoDate(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
  if (!match) {
    return new Date();
  }
  const [, year, month, day] = match;
  return new Date(Number(year), Number(month) - 1, Number(day));
}

function isoDateFromDate(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function formatIndianDate(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
  if (!match) {
    return '';
  }
  const [, year, month, day] = match;
  return `${day}-${month}-${year}`;
}

const styles = StyleSheet.create({
  shell: {
    flex: 1,
    backgroundColor: '#ffffff',
  },
  page: {
    padding: 24,
    gap: 24,
  },
  authPage: {
    minHeight: '100%',
    justifyContent: 'center',
    paddingTop: 40,
    paddingBottom: 40,
    gap: 34,
  },
  banner: {
    backgroundColor: '#f7f7f7',
    borderColor: '#d8d8d8',
    borderWidth: 1,
    borderRadius: 8,
    padding: 12,
    gap: 4,
  },
  bannerTitle: {
    color: '#111111',
    fontSize: 14,
    fontFamily: fonts.medium,
  },
  bannerText: {
    color: '#555555',
    fontSize: 13,
    fontFamily: fonts.regular,
    lineHeight: 18,
  },
  authHeader: {
    width: '100%',
    maxWidth: 560,
    alignSelf: 'center',
    gap: 10,
  },
  brandMark: {
    color: '#111111',
    fontSize: 16,
    fontFamily: fonts.semibold,
  },
  authTitle: {
    color: '#111111',
    fontSize: 30,
    fontFamily: fonts.semibold,
    letterSpacing: 0,
    lineHeight: 36,
  },
  authSubtitle: {
    color: '#606060',
    fontSize: 15,
    fontFamily: fonts.regular,
    lineHeight: 22,
  },
  appHeader: {
    paddingTop: 16,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 12,
  },
  appHeaderText: {
    flex: 1,
    gap: 8,
  },
  kicker: {
    color: '#777777',
    fontSize: 12,
    fontFamily: fonts.medium,
    letterSpacing: 0,
    textTransform: 'uppercase',
  },
  title: {
    color: '#111111',
    fontSize: 28,
    fontFamily: fonts.semibold,
    letterSpacing: 0,
    lineHeight: 34,
  },
  subtitle: {
    color: '#666666',
    fontSize: 15,
    fontFamily: fonts.regular,
    lineHeight: 22,
  },
  statusStrip: {
    backgroundColor: '#111111',
    borderRadius: 8,
    padding: 14,
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  tabBar: {
    flexDirection: 'row',
    gap: 8,
  },
  tabButton: {
    flex: 1,
    minHeight: 46,
    borderWidth: 1,
    borderColor: '#d8d8d8',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 11,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    gap: 6,
    backgroundColor: '#ffffff',
  },
  tabButtonActive: {
    backgroundColor: '#111111',
    borderColor: '#111111',
  },
  tabButtonText: {
    color: '#111111',
    fontSize: 13,
    fontFamily: fonts.medium,
  },
  tabButtonTextActive: {
    color: '#ffffff',
  },
  backButton: {
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingVertical: 6,
    paddingRight: 8,
  },
  backButtonText: {
    color: '#111111',
    fontSize: 14,
    fontFamily: fonts.regular,
  },
  utilityText: {
    color: '#111111',
    fontSize: 14,
    fontFamily: fonts.regular,
  },
  iconOnlyButton: {
    width: 42,
    height: 42,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#d8d8d8',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#ffffff',
  },
  metricLabel: {
    color: '#b8b8b8',
    fontSize: 11,
    fontFamily: fonts.medium,
    textTransform: 'uppercase',
  },
  metric: {
    color: '#ffffff',
    fontSize: 24,
    fontFamily: fonts.semibold,
  },
  metricSmall: {
    color: '#ffffff',
    fontSize: 15,
    fontFamily: fonts.medium,
    marginTop: 7,
  },
  workspace: {
    gap: 12,
  },
  authForm: {
    width: '100%',
    maxWidth: 560,
    alignSelf: 'center',
    gap: 12,
  },
  workspaceHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingTop: 4,
  },
  workspaceTitle: {
    color: '#111111',
    fontSize: 18,
    fontFamily: fonts.semibold,
  },
  rowButton: {
    backgroundColor: '#ffffff',
    borderRadius: 8,
    padding: 16,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#e0e0e0',
    gap: 12,
  },
  rowButtonTextBlock: {
    flex: 1,
    minWidth: 0,
  },
  rowChevron: {
    width: 22,
    alignItems: 'flex-end',
    justifyContent: 'center',
  },
  warningRow: {
    borderColor: '#f59e0b',
    backgroundColor: '#fff7ed',
  },
  warningTitle: {
    color: '#9a3412',
  },
  warningDetail: {
    color: '#c2410c',
  },
  rowTitle: {
    color: '#111111',
    fontSize: 15,
    fontFamily: fonts.medium,
  },
  rowDetail: {
    color: '#666666',
    fontSize: 13,
    fontFamily: fonts.regular,
    marginTop: 4,
  },
  fieldLabel: {
    color: '#555555',
    fontSize: 12,
    fontFamily: fonts.medium,
    textTransform: 'uppercase',
  },
  requiredAsterisk: {
    color: '#b42318',
  },
  input: {
    borderWidth: 1,
    borderColor: '#d8d8d8',
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 12,
    minHeight: 54,
    backgroundColor: '#ffffff',
    color: '#111111',
    fontSize: 16,
    fontFamily: fonts.regular,
  },
  readOnlyInput: {
    backgroundColor: '#f6f6f6',
    borderColor: '#e0e0e0',
  },
  datePickerButton: {
    borderWidth: 1,
    borderColor: '#d8d8d8',
    borderRadius: 8,
    paddingHorizontal: 14,
    minHeight: 54,
    backgroundColor: '#ffffff',
    justifyContent: 'center',
  },
  datePickerText: {
    color: '#111111',
    fontSize: 16,
    fontFamily: fonts.regular,
  },
  datePickerFrame: {
    minHeight: Platform.OS === 'ios' ? 216 : 0,
    justifyContent: 'center',
  },
  nativeDatePicker: {
    width: '100%',
    height: Platform.OS === 'ios' ? 216 : undefined,
  },
  placeholderText: {
    color: '#9a9a9a',
  },
  compactInput: {
    fontSize: 14,
    paddingVertical: 9,
  },
  searchPanel: {
    gap: 8,
  },
  draftCartSection: {
    gap: 8,
    paddingBottom: 8,
  },
  openCartsWidget: {
    backgroundColor: '#ffffff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#d8d8d8',
    overflow: 'hidden',
  },
  openCartsHeader: {
    padding: 16,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 12,
  },
  chevronExpanded: {
    transform: [{ rotate: '90deg' }],
  },
  draftCartRow: {
    backgroundColor: '#ffffff',
    borderTopWidth: 1,
    borderTopColor: '#eeeeee',
  },
  draftCartOpen: {
    padding: 16,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 12,
  },
  draftCartClear: {
    minHeight: 42,
    borderTopWidth: 1,
    borderTopColor: '#eeeeee',
    paddingHorizontal: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  },
  draftCartClearText: {
    color: '#b42318',
    fontSize: 13,
    fontFamily: fonts.regular,
  },
  groupFilterHeader: {
    gap: 8,
  },
  groupChips: {
    gap: 8,
    paddingRight: 24,
  },
  groupChip: {
    borderWidth: 1,
    borderColor: '#d8d8d8',
    borderRadius: 8,
    paddingHorizontal: 13,
    paddingVertical: 9,
    backgroundColor: '#ffffff',
  },
  groupChipActive: {
    borderColor: '#111111',
    backgroundColor: '#111111',
  },
  groupChipText: {
    color: '#555555',
    fontSize: 13,
    fontFamily: fonts.regular,
  },
  groupChipTextActive: {
    color: '#ffffff',
  },
  itemRow: {
    borderWidth: 1,
    borderColor: '#e0e0e0',
    borderRadius: 8,
    padding: 14,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: 12,
    backgroundColor: '#ffffff',
  },
  itemRowText: {
    flex: 1,
  },
  itemAddPill: {
    minWidth: 64,
    minHeight: 36,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#111111',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 10,
  },
  itemAddPillActive: {
    backgroundColor: '#111111',
  },
  itemAddPillText: {
    color: '#111111',
    fontSize: 13,
    fontFamily: fonts.medium,
  },
  itemAddPillTextActive: {
    color: '#ffffff',
  },
  helperText: {
    color: '#666666',
    fontSize: 13,
    fontFamily: fonts.regular,
    lineHeight: 19,
  },
  summaryLine: {
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#e6e6e6',
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 12,
  },
  summaryItemText: {
    flex: 1,
    minWidth: 0,
    paddingTop: 2,
  },
  summaryItemTitle: {
    lineHeight: 20,
    flexWrap: 'wrap',
  },
  contextBlock: {
    gap: 10,
    paddingBottom: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#e6e6e6',
  },
  quantity: {
    color: '#111111',
    fontSize: 16,
    fontFamily: fonts.medium,
    minWidth: 28,
    textAlign: 'center',
  },
  cartControls: {
    width: 154,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
    gap: 6,
  },
  iconButton: {
    width: 34,
    height: 34,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#d8d8d8',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#ffffff',
  },
  note: {
    color: '#444444',
    backgroundColor: '#f5f5f5',
    borderRadius: 8,
    padding: 12,
    fontSize: 13,
    fontFamily: fonts.regular,
    lineHeight: 18,
  },
  primaryAction: {
    backgroundColor: '#111111',
    borderRadius: 8,
    padding: 15,
    minHeight: 54,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 4,
  },
  authPrimaryAction: {
    marginTop: 18,
  },
  authInlinePrimaryAction: {
    flex: 1,
    marginTop: 0,
  },
  authSplitActions: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 18,
  },
  authSecondaryAction: {
    flex: 1,
    minHeight: 54,
  },
  secondaryAction: {
    flex: 1,
    minHeight: 56,
    backgroundColor: '#ffffff',
    borderWidth: 1,
    borderColor: '#d8d8d8',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 13,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    gap: 7,
  },
  secondaryActionText: {
    color: '#111111',
    fontSize: 14,
    fontFamily: fonts.regular,
    textAlign: 'center',
    flexShrink: 1,
  },
  disabledAction: {
    backgroundColor: '#f7f7f7',
  },
  disabledActionText: {
    color: '#8a8a8a',
  },
  actionRow: {
    flexDirection: 'row',
    gap: 10,
  },
  primaryActionText: {
    color: '#ffffff',
    fontSize: 15,
    fontFamily: fonts.regular,
  },
  textAction: {
    paddingVertical: 8,
    alignItems: 'center',
  },
  authTextAction: {
    paddingVertical: 10,
    marginTop: 12,
    alignItems: 'center',
  },
  textActionText: {
    color: '#111111',
    fontSize: 15,
    fontFamily: fonts.regular,
    textDecorationLine: 'underline',
  },
  successRef: {
    color: '#111111',
    fontSize: 28,
    fontFamily: fonts.semibold,
  },
  cartBar: {
    margin: 14,
    marginTop: 0,
    borderRadius: 8,
    backgroundColor: '#111111',
    padding: 14,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  cartBarTitle: {
    color: '#ffffff',
    fontSize: 15,
    fontFamily: fonts.medium,
  },
  cartBarText: {
    color: '#c8c8c8',
    fontSize: 12,
    fontFamily: fonts.regular,
    marginTop: 2,
  },
  cartBarAction: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  cartBarActionText: {
    color: '#ffffff',
    fontSize: 14,
    fontFamily: fonts.regular,
  },
  modalOverlay: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  modalScrim: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0, 0, 0, 0.28)',
  },
  bottomSheet: {
    maxHeight: '82%',
    backgroundColor: '#ffffff',
    borderTopLeftRadius: 8,
    borderTopRightRadius: 8,
    padding: 20,
    gap: 12,
  },
  sheetHandle: {
    alignSelf: 'center',
    width: 42,
    height: 4,
    borderRadius: 999,
    backgroundColor: '#d8d8d8',
    marginBottom: 2,
  },
});
