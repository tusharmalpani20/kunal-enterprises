import React from 'react';
import { Pressable, Text } from 'react-native';
import { Check } from 'lucide-react-native';

import { AppShell } from '../../src/components/AppShell';
import { Workspace } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { styles } from '../../src/styles/orderScreen';

export default function SuccessScreen() {
  const { reference, showOrder } = useOrderFlow();

  return (
    <AppShell>
      <Workspace title="Order Placed" icon={<Check size={18} color="#111111" />}>
        <Text style={styles.successRef}>{reference}</Text>
        <Text style={styles.rowDetail}>WhatsApp confirmation and PDF are queued for the Customer.</Text>
        <Pressable style={styles.primaryAction} onPress={showOrder}>
          <Text style={styles.primaryActionText}>Place another order</Text>
        </Pressable>
      </Workspace>
    </AppShell>
  );
}
