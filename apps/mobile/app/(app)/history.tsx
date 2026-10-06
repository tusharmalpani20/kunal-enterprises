import React from 'react';
import { Text, View } from 'react-native';
import { History } from 'lucide-react-native';

import { AppShell } from '../../src/components/AppShell';
import { FeedbackPressable, Workspace } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { styles } from '../../src/styles/appStyles';
import { OrderHistoryCard } from '../../src/components/OrderHistoryCard';

const HISTORY_PAGE_SIZE = 20;

export default function HistoryScreen() {
  const { mode, historyRows, historyLoading, historyHasMore, loadMoreHistory, showOrderDetail, showQuickOrderDetail } = useOrderFlow();

  return (
    <AppShell>
      <Workspace title="Order History" icon={<History size={18} color="#111111" />}>
        {historyRows.length === 0 ? (
          <View style={styles.emptyState}>
            <Text style={styles.workspaceTitle}>No orders yet</Text>
            <Text style={styles.rowDetail}>{mode === 'Customer' ? 'Orders and Quick Order requests will appear here.' : 'Placed orders will appear here.'}</Text>
          </View>
        ) : historyRows.map((order) => (
          <OrderHistoryCard
            key={`${order.entry_type || 'order'}:${order.name}`}
            order={order}
            mode={mode}
            onPress={() => order.entry_type === 'quick_order' ? showQuickOrderDetail(order.name) : showOrderDetail(order)}
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
