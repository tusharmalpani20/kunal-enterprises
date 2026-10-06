import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createQuickOrderSubmitter } from '../domain/quickOrderFlow.mjs';
import { apiErrorMessage } from '../domain/sharedStateFlow.mjs';
import type { QuickOrderRequest } from '../types';

interface QuickOrderApi {
  quickOrderSubmit(text: string, customer: string): Promise<QuickOrderRequest>;
  quickOrderHistory(customer: string, options: { limit: number; offset: number }): Promise<{
    requests: QuickOrderRequest[]; has_more: boolean; next_offset: number | null;
  }>;
  quickOrderDetail(request: string, customer: string): Promise<QuickOrderRequest>;
}

export function useQuickOrders({ api, customer, contextKey, enabled, active, onError }: {
  api: QuickOrderApi; customer: string; contextKey: string; enabled: boolean; active: boolean;
  onError: (error: unknown) => void;
}) {
  const [text, setText] = useState('');
  const [requests, setRequests] = useState<QuickOrderRequest[]>([]);
  const [detail, setDetail] = useState<QuickOrderRequest | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState('');
  const [submittedReference, setSubmittedReference] = useState('');
  const [stateContext, setStateContext] = useState(contextKey);
  const currentContext = useRef(contextKey);
  currentContext.current = contextKey;
  const errorHandler = useRef(onError);
  errorHandler.current = onError;
  const nextOffset = useRef(0);
  const historyRequestId = useRef(0);
  const detailRequestId = useRef(0);
  const historyInFlight = useRef(false);
  const submitInFlight = useRef(false);
  const submitter = useMemo(() => createQuickOrderSubmitter(
    (value: string) => api.quickOrderSubmit(value, customer),
  ), [api, customer, contextKey]);

  useEffect(() => {
    setStateContext(contextKey);
    historyRequestId.current++;
    detailRequestId.current++;
    historyInFlight.current = false;
    submitInFlight.current = false;
    nextOffset.current = 0;
    setText(''); setRequests([]); setDetail(null); setError(''); setSubmittedReference('');
    setSubmitting(false); setLoading(false); setDetailLoading(false); setHasMore(false);
  }, [contextKey]);

  const reportError = useCallback((failure: unknown) => {
    setError(apiErrorMessage(failure));
    errorHandler.current(failure);
  }, []);

  const loadHistory = useCallback(async (more = false) => {
    if (!enabled || historyInFlight.current) return;
    const requestId = ++historyRequestId.current;
    historyInFlight.current = true;
    setLoading(true); setError('');
    try {
      const offset = more ? nextOffset.current : 0;
      const page = await api.quickOrderHistory(customer, { limit: 20, offset });
      if (currentContext.current !== contextKey || requestId !== historyRequestId.current) return;
      setRequests((current) => more
        ? [...current, ...page.requests.filter((row) => !current.some((entry) => entry.name === row.name))]
        : page.requests);
      nextOffset.current = page.next_offset ?? offset + page.requests.length;
      setHasMore(page.has_more);
    } catch (failure) {
      if (currentContext.current === contextKey && requestId === historyRequestId.current) reportError(failure);
    } finally {
      if (currentContext.current === contextKey && requestId === historyRequestId.current) {
        historyInFlight.current = false;
        setLoading(false);
      }
    }
  }, [api, customer, contextKey, enabled, reportError]);

  useEffect(() => {
    if (active && enabled) void loadHistory();
  }, [active, enabled, loadHistory]);

  async function submit() {
    if (!enabled || submitInFlight.current) return;
    submitInFlight.current = true;
    setSubmitting(true); setError(''); setSubmittedReference('');
    try {
      const request = await submitter(text) as QuickOrderRequest | null;
      if (!request || currentContext.current !== contextKey) return;
      // Ignore a history request started before this submission was accepted.
      historyRequestId.current++;
      historyInFlight.current = false;
      setLoading(false);
      setRequests((current) => [request, ...current.filter((row) => row.name !== request.name)]);
      nextOffset.current++;
      setText('');
      setSubmittedReference(request.name);
      // Reload the first page so a submission during the initial load cannot hide older requests.
      void loadHistory();
      return request;
    } catch (failure) {
      if (currentContext.current === contextKey) reportError(failure);
    } finally {
      if (currentContext.current === contextKey) {
        submitInFlight.current = false;
        setSubmitting(false);
      }
    }
  }

  async function loadDetail(request: string) {
    if (!enabled) return;
    const requestId = ++detailRequestId.current;
    setDetail(null); setDetailLoading(true); setError('');
    try {
      const row = await api.quickOrderDetail(request, customer);
      if (currentContext.current === contextKey && requestId === detailRequestId.current) setDetail(row);
    } catch (failure) {
      if (currentContext.current === contextKey && requestId === detailRequestId.current) reportError(failure);
    } finally {
      if (currentContext.current === contextKey && requestId === detailRequestId.current) setDetailLoading(false);
    }
  }

  const ownsState = stateContext === contextKey;
  return { text: ownsState ? text : '', setText, requests: ownsState ? requests : [],
    detail: ownsState ? detail : null, submitting: ownsState && submitting, loading: ownsState && loading,
    detailLoading: ownsState && detailLoading, hasMore: ownsState && hasMore, error: ownsState ? error : '',
    submittedReference: ownsState ? submittedReference : '', submit, loadHistory, loadDetail,
    isSubmitting: () => submitInFlight.current };
}
