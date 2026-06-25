import React from 'react';
import { History } from 'lucide-react-native';

import { AppShell } from '../../src/components/AppShell';
import { RowButton, Workspace } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { orderHistoryRowDetail } from '../../src/utils/orderFormatting';

export default function HistoryScreen() {
  const { mode, historyRows, showOrderDetail } = useOrderFlow();

  return (
    <AppShell>
      <Workspace title="Order History" icon={<History size={18} color="#111111" />}>
        {historyRows.map((order) => (
          <RowButton
            key={order.name}
            title={order.portal_reference_number}
            detail={orderHistoryRowDetail(order, mode)}
            onPress={() => showOrderDetail(order)}
          />
        ))}
      </Workspace>
    </AppShell>
  );
}
