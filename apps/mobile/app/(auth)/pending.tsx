import React from 'react';
import { Text } from 'react-native';
import { Check } from 'lucide-react-native';

import { AuthShell } from '../../src/components/AuthShell';
import { Workspace } from '../../src/components/orderUi';
import { pendingAccessMessage } from '../../src/domain/screenCopy.mjs';
import { styles } from '../../src/styles/orderScreen';

export default function PendingScreen() {
  return (
    <AuthShell>
      <Workspace title="Access Pending" icon={<Check size={18} color="#111111" />}>
        <Text style={styles.rowTitle}>Pending Admin Review</Text>
        <Text style={styles.rowDetail}>{pendingAccessMessage()}</Text>
      </Workspace>
    </AuthShell>
  );
}
