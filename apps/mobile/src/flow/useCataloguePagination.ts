import { useRef, useState } from 'react';
import type { TallyItem } from '../types';
type Page = { items: TallyItem[]; total_count: number; all_count: number; has_more: boolean; next_offset: number | null };

// Ignore late pages after the customer, session, filter or active screen changes.
export function useCataloguePagination({ contextKey, catalogueKey, active, fetchPage, appendItems, onError }: {
  contextKey: string; catalogueKey: string; active: boolean;
  fetchPage: (offset: number) => Promise<Page>;
  appendItems: (items: TallyItem[]) => void;
  onError: (error: unknown) => void;
}) {
  const [page, setPage] = useState<{ key: string; catalogue: string; data: Page } | null>(null);
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const current = useRef({ contextKey, active });
  const revision = useRef(0);
  if (current.current.contextKey !== contextKey || current.current.active !== active) revision.current += 1;
  current.current = { contextKey, active };
  const inFlight = useRef<string | null>(null);
  const validPage = page?.key === contextKey ? page.data : null;
  async function loadMoreItems() {
    if (!active || !validPage?.has_more || validPage.next_offset == null || inFlight.current) return;
    const key = contextKey;
    const requestRevision = revision.current;
    inFlight.current = key;
    setLoadingKey(key);
    try {
      const next = await fetchPage(validPage.next_offset);
      if (revision.current !== requestRevision || current.current.contextKey !== key || !current.current.active) return;
      appendItems(next.items);
      setPage({ key, catalogue: catalogueKey, data: next });
    } catch (error) {
      if (revision.current === requestRevision && current.current.contextKey === key && current.current.active) onError(error);
    } finally {
      inFlight.current = null;
      setLoadingKey(null);
    }
  }
  return {
    acceptPage(data: Page) { setPage({ key: contextKey, catalogue: catalogueKey, data }); },
    itemsTotalCount: validPage?.total_count ?? null,
    itemsAllCount: page?.catalogue === catalogueKey ? page.data.all_count ?? null : null,
    itemsHasMore: Boolean(validPage?.has_more),
    itemsMoreLoading: loadingKey === contextKey,
    loadMoreItems,
  };
}
