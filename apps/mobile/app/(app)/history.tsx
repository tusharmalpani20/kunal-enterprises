import React from 'react';
import { Text, View } from 'react-native';
import { History } from 'lucide-react-native';

import { AppShell } from '../../src/components/AppShell';
import { FeedbackPressable, RowButton, Workspace } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { styles } from '../../src/styles/appStyles';
import { orderHistoryRowDetail } from '../../src/utils/orderFormatting';

const HISTORY_PAGE_SIZE = 20;

export default function HistoryScreen() {
  const { mode, historyRows, historyLoading, historyHasMore, loadMoreHistory, showOrderDetail } = useOrderFlow();

  return (
    <AppShell>
      <Workspace title="Order History" icon={<History size={18} color="#111111" />}>
        {historyRows.length === 0 ? (
          <View style={styles.emptyState}>
            <Text style={styles.workspaceTitle}>No orders yet</Text>
            <Text style={styles.rowDetail}>Placed orders will appear here.</Text>
          </View>
        ) : historyRows.map((order) => (
          <RowButton
            key={order.name}
            title={order.portal_reference_number}
            detail={orderHistoryRowDetail(order, mode)}
            onPress={() => showOrderDetail(order)}
          />
        ))}
        {historyHasMore && (
          <FeedbackPressable
            style={[styles.secondaryAction, styles.historyLoadMore]}
            pressedStyle={styles.buttonPressed}
            rippleColor="#eeeeee"
            disabled={historyLoading}
            onPress={loadMoreHistory}
          >
            <Text style={styles.secondaryActionText}>{historyLoading ? 'Loading...' : 'Load more'}</Text>
          </FeedbackPressable>
        )}
        {historyRows.length >= HISTORY_PAGE_SIZE && !historyHasMore && (
          <Text style={[styles.rowDetail, styles.historyEndText]}>No more orders</Text>
        )}
      </Workspace>
    </AppShell>
  );
}
