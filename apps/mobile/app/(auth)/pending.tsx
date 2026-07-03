import React from 'react';
import { Text } from 'react-native';
import { Check, RefreshCw } from 'lucide-react-native';

import { AuthShell } from '../../src/components/AuthShell';
import { FeedbackPressable, Workspace } from '../../src/components/orderUi';
import { pendingAccessMessage } from '../../src/domain/screenCopy.mjs';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { styles } from '../../src/styles/appStyles';

export default function PendingScreen() {
  const { pendingAccessRequest, pendingAccessRefreshing, refreshPendingAccess } = useOrderFlow();
  const mobileNumber = pendingAccessRequest?.mobileNumber;

  return (
    <AuthShell>
      <Workspace title="Access Pending" icon={<Check size={18} color="#111111" />}>
        <Text style={styles.rowTitle}>Pending Admin Review</Text>
        {mobileNumber ? <Text style={styles.rowDetail}>Mobile Number: {mobileNumber}</Text> : null}
        <Text style={styles.rowDetail}>{pendingAccessMessage()}</Text>
        <FeedbackPressable
          style={[styles.primaryAction, styles.authPrimaryAction]}
          pressedStyle={styles.primaryActionPressed}
          rippleColor="#2a2a2a"
          onPress={refreshPendingAccess}
          disabled={pendingAccessRefreshing}
        >
          <RefreshCw size={16} color="#ffffff" />
          <Text style={styles.primaryActionText}>
            {pendingAccessRefreshing ? 'Checking status...' : 'Refresh status'}
          </Text>
        </FeedbackPressable>
      </Workspace>
    </AuthShell>
  );
}
