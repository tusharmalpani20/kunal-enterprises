import React from 'react';
import { Text } from 'react-native';
import { Check } from 'lucide-react-native';

import { AppShell } from '../../src/components/AppShell';
import { FeedbackPressable, Workspace } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { styles } from '../../src/styles/appStyles';

export default function SuccessScreen() {
  const { reference, showOrder } = useOrderFlow();

  return (
    <AppShell>
      <Workspace title="Order Placed" icon={<Check size={18} color="#111111" />}>
        <Text style={styles.successRef}>{reference}</Text>
        <Text style={styles.rowDetail}>WhatsApp confirmation and PDF are queued for the Customer.</Text>
        <FeedbackPressable
          style={styles.primaryAction}
          pressedStyle={styles.primaryActionPressed}
          rippleColor="#2a2a2a"
          onPress={showOrder}
        >
          <Text style={styles.primaryActionText}>Place another order</Text>
        </FeedbackPressable>
      </Workspace>
    </AppShell>
  );
}
