import React from 'react';
import { Text, View } from 'react-native';
import { AppShell } from '../../src/components/AppShell';
import { BackButton, FeedbackPressable, Workspace } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { formatOrderPlacedStamp } from '../../src/utils/orderFormatting';
import { styles, colors } from '../../src/styles/appStyles';

export default function QuickOrderDetailScreen() {
  const { quickOrders, quickOrdersEnabled, quickOrderLinkedLoading, showHistory, showQuickOrderLinkedOrder } = useOrderFlow();
  const { detail, detailLoading, error } = quickOrders;
  if (!quickOrdersEnabled) return <AppShell><Text style={styles.rowDetail}>Quick Order is available to signed-in Customers.</Text></AppShell>;
  return (
    <AppShell>
      <Workspace title="Quick Order Request">
        <BackButton label="Order History" onPress={showHistory} />
        {detailLoading ? <Text style={styles.rowDetail}>Loading request...</Text> : null}
        {error ? <Text style={styles.note}>{error}</Text> : null}
        {detail ? <>
          <Text style={styles.successRef}>{detail.name}</Text>
          <Text style={styles.rowTitle}>{detail.status}</Text>
          <Text style={styles.rowDetail}>{formatOrderPlacedStamp(detail.confirmation_datetime)}</Text>
          <View style={styles.segmentedControl}>
            <FeedbackPressable style={[styles.segmentedButtonPressable, { flex: 0, minWidth: 112 }]} pressedStyle={styles.detailSegmentedActive} rippleColor={colors.primaryPressed} accessibilityRole="tab" accessibilityState={{ selected: true }}>
              <View pointerEvents="none" style={[styles.segmentedButton, styles.segmentedButtonActive, styles.detailSegmentedActive]}>
                <Text style={[styles.segmentedButtonText, styles.segmentedButtonTextActive]}>Order Note</Text>
              </View>
            </FeedbackPressable>
          </View>
          <Text style={styles.rowDetail} selectable>{detail.text}</Text>
          {detail.rejection_reason ? <>
            <Text style={styles.fieldLabel}>Reason</Text>
            <Text style={styles.rowDetail}>{detail.rejection_reason}</Text>
          </> : null}
          {detail.order ? (
            <FeedbackPressable style={styles.primaryAction} disabled={quickOrderLinkedLoading} onPress={showQuickOrderLinkedOrder}>
              <Text style={styles.primaryActionText}>{quickOrderLinkedLoading ? 'Opening order...' : `View order ${detail.portal_reference_number || detail.order}`}</Text>
            </FeedbackPressable>
          ) : null}
        </> : !detailLoading && !error ? <Text style={styles.rowDetail}>Select a request from Order History.</Text> : null}
      </Workspace>
    </AppShell>
  );
}
