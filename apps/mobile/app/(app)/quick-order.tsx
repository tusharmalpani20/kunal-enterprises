import React from 'react';
import { Text, View } from 'react-native';
import { Package } from 'lucide-react-native';
import { AppShell } from '../../src/components/AppShell';
import { FeedbackPressable, RowButton, Workspace } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { QuickOrderForm } from '../../src/components/QuickOrderModal';
import { formatOrderPlacedStamp } from '../../src/utils/orderFormatting';
import { styles } from '../../src/styles/appStyles';

export default function QuickOrderScreen() {
  const { quickOrders, quickOrdersEnabled, showQuickOrderDetail } = useOrderFlow();
  const { requests, submitting, loading, hasMore, error, loadHistory } = quickOrders;
  if (!quickOrdersEnabled) {
    return <AppShell><Text style={styles.rowDetail}>Quick Order is available to signed-in Customers.</Text></AppShell>;
  }
  return (
    <AppShell>
      <Workspace title="Quick Order" icon={<Package size={18} color="#111111" />}>
        <QuickOrderForm />
      </Workspace>
      <Workspace title="Quick Order History">
        <FeedbackPressable style={styles.secondaryAction} disabled={loading || submitting} onPress={() => loadHistory()}>
          <Text style={styles.secondaryActionText}>{loading ? 'Loading...' : 'Refresh requests'}</Text>
        </FeedbackPressable>
        {!loading && !requests.length && !error ? (
          <View style={styles.emptyState}><Text style={styles.rowDetail}>Your submitted requests will appear here.</Text></View>
        ) : requests.map((request) => (
          <RowButton
            key={request.name}
            title={request.name}
            detail={[request.status, formatOrderPlacedStamp(request.confirmation_datetime), request.portal_reference_number ? `Order ${request.portal_reference_number}` : ''].filter(Boolean).join('\n')}
            onPress={() => showQuickOrderDetail(request.name)}
          />
        ))}
        {hasMore && (
          <FeedbackPressable style={styles.secondaryAction} disabled={loading || submitting} onPress={() => loadHistory(true)}>
            <Text style={styles.secondaryActionText}>{loading ? 'Loading...' : 'Load more'}</Text>
          </FeedbackPressable>
        )}
      </Workspace>
    </AppShell>
  );
}
