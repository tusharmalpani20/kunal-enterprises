import React from 'react';
import { Text, View } from 'react-native';
import { History } from 'lucide-react-native';

import { AppShell } from '../../src/components/AppShell';
import { BackButton, Workspace } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { styles } from '../../src/styles/orderScreen';

export default function DetailScreen() {
  const { orderDetail, showHistory } = useOrderFlow();

  if (!orderDetail) {
    return <AppShell>{null}</AppShell>;
  }

  return (
    <AppShell>
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
    </AppShell>
  );
}
