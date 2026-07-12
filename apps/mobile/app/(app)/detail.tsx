import React, { useMemo, useState } from 'react';
import { Text, View } from 'react-native';
import { History } from 'lucide-react-native';

import { AppShell } from '../../src/components/AppShell';
import { BackButton, FeedbackPressable, GroupLogo, Workspace } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { groupGodownAllocationsForMobile } from '../../src/domain/profileHistoryFlow.mjs';
import { colors, styles } from '../../src/styles/appStyles';

type DetailView = 'overall' | 'godown';

export default function DetailScreen() {
  const { orderDetail, showHistory, logoForItemName, resolveLogoUrl } = useOrderFlow();
  const [detailView, setDetailView] = useState<DetailView>('overall');

  const itemNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const item of orderDetail?.items || []) {
      map.set(item.item, item.item_name || item.item);
    }
    return map;
  }, [orderDetail]);

  const godownRows = orderDetail?.godown_allocations || [];
  const godownGroups = useMemo(() => groupGodownAllocationsForMobile(godownRows), [godownRows]);

  if (!orderDetail) {
    return <AppShell>{null}</AppShell>;
  }

  const overallRows = orderDetail.items || [];

  return (
    <AppShell>
      <Workspace title="Order Detail" icon={<History size={18} color="#111111" />}>
        <BackButton label="Order History" onPress={showHistory} />
        <Text style={styles.successRef}>{orderDetail.portal_reference_number}</Text>
        <Text style={styles.rowDetail}>{orderDetail.display_status || orderDetail.status}</Text>
        <Text style={styles.rowDetail}>Placed by {orderDetail.placed_by_label || orderDetail.placed_by || 'You'}</Text>
        <View style={styles.segmentedControl}>
          <FeedbackPressable
            style={styles.segmentedButtonPressable}
            pressedStyle={detailView === 'overall' ? styles.segmentedButtonActive : styles.buttonPressed}
            rippleColor={detailView === 'overall' ? colors.primaryPressed : '#eeeeee'}
            onPress={() => setDetailView('overall')}
          >
            <View pointerEvents="none" style={[styles.segmentedButton, detailView === 'overall' && styles.segmentedButtonActive]}>
              <Text style={[styles.segmentedButtonText, detailView === 'overall' && styles.segmentedButtonTextActive]}>Overall</Text>
            </View>
          </FeedbackPressable>
          <FeedbackPressable
            style={styles.segmentedButtonPressable}
            pressedStyle={detailView === 'godown' ? styles.segmentedButtonActive : styles.buttonPressed}
            rippleColor={detailView === 'godown' ? colors.primaryPressed : '#eeeeee'}
            onPress={() => setDetailView('godown')}
          >
            <View pointerEvents="none" style={[styles.segmentedButton, detailView === 'godown' && styles.segmentedButtonActive]}>
              <Text style={[styles.segmentedButtonText, detailView === 'godown' && styles.segmentedButtonTextActive]}>Godown Summary</Text>
            </View>
          </FeedbackPressable>
        </View>
        {detailView === 'overall' ? (
          overallRows.length === 0 ? (
            <View style={styles.emptyState}>
              <Text style={styles.rowDetail}>No item summary is available for this order.</Text>
            </View>
          ) : overallRows.map((item) => (
            <View key={item.item} style={styles.summaryLine}>
              <GroupLogo logoUrl={resolveLogoUrl(logoForItemName(item.item))} size={24} fallbackLabel={item.item_name || item.item} style={styles.itemRowLogo} />
              <View style={styles.summaryItemText}>
                <Text style={[styles.rowTitle, styles.summaryItemTitle]}>{item.item_name || item.item}</Text>
                <Text style={styles.rowDetail}>{overallRowDetail(item)}</Text>
              </View>
              <Text style={styles.quantity}>{item.requested_quantity}</Text>
            </View>
          ))
        ) : (
          godownRows.length === 0 ? (
            <View style={styles.emptyState}>
              <Text style={styles.rowDetail}>No godown summary is available for this order.</Text>
            </View>
          ) : godownGroups.map((group, groupIndex) => (
            <View key={group.godown} style={styles.godownGroup}>
              <View style={styles.godownGroupHeader}>
                <Text style={styles.godownGroupTitle}>{group.godown}</Text>
                <Text style={styles.godownGroupTotal}>
                  {group.rows.reduce((total, row) => total + Number(row.requested_quantity || 0), 0)} total
                </Text>
              </View>
              {group.rows.map((allocation, rowIndex) => {
                const itemName = allocation.item_name || itemNameById.get(allocation.item) || allocation.item;
                const isLastRow = rowIndex === group.rows.length - 1;
                return (
                  <View key={`${allocation.item}:${allocation.godown}`} style={[styles.summaryLine, isLastRow && { borderBottomWidth: 0 }]}>
                    <GroupLogo logoUrl={resolveLogoUrl(logoForItemName(allocation.item))} size={24} fallbackLabel={itemName} style={styles.itemRowLogo} />
                    <View style={styles.summaryItemText}>
                      <Text style={[styles.rowTitle, styles.summaryItemTitle]}>{itemName}</Text>
                      <Text style={styles.rowDetail}>{godownRowDetail(allocation)}</Text>
                    </View>
                    <Text style={styles.quantity}>{allocation.requested_quantity}</Text>
                  </View>
                );
              })}
              {groupIndex < godownGroups.length - 1 && <View style={styles.godownGroupDivider} />}
            </View>
          ))
        )}
      </Workspace>
    </AppShell>
  );
}

function overallRowDetail(item: {
  root_stock_group?: string;
  unit?: string;
  pending_quantity?: number;
  fulfilled_quantity?: number;
  status?: string;
}) {
  return [
    item.root_stock_group,
    item.unit,
    quantityStatus(item),
    item.status,
  ].filter(Boolean).join('\n');
}

function godownRowDetail(allocation: {
  unit?: string;
  pending_quantity?: number;
  fulfilled_quantity?: number;
}) {
  return [
    allocation.unit,
    quantityStatus(allocation),
  ].filter(Boolean).join('\n');
}

function quantityStatus(row: { pending_quantity?: number; fulfilled_quantity?: number }) {
  const parts = [];
  if (typeof row.fulfilled_quantity === 'number') {
    parts.push(`Fulfilled ${row.fulfilled_quantity}`);
  }
  if (typeof row.pending_quantity === 'number') {
    parts.push(`Pending ${row.pending_quantity}`);
  }
  return parts.join(' · ');
}
