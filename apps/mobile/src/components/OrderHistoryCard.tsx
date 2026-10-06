import React from 'react';
import { Text, View } from 'react-native';
import { ChevronRight } from 'lucide-react-native';
import { FeedbackPressable } from './orderUi';
import { styles } from '../styles/appStyles';
import { formatOrderPlacedStamp } from '../utils/orderFormatting';
import { orderSourceLabels } from '../domain/profileHistoryFlow.mjs';
import type { Mode } from '../flow/types';
import type { OrderSummary } from '../types';

export function OrderHistoryCard({ order, mode, onPress }: {
  order: OrderSummary; mode: Mode; onPress: () => void;
}) {
  const labels = orderSourceLabels(order);
  const stamp = formatOrderPlacedStamp(order.confirmation_datetime);
  return (
    <FeedbackPressable style={styles.historyCard} pressedStyle={styles.rowButtonPressed} onPress={onPress} accessibilityRole="button">
      <View style={styles.historyCardHeading}>
        <Text style={[styles.rowTitle, { flex: 1 }]}>{order.name}</Text>
        <ChevronRight size={18} color="#777777" />
      </View>
      {labels.length > 0 && (
        <View style={styles.historySourceLabels}>
          {labels.map(label => (
            <View key={label} style={[styles.historySourceBadge, label === 'Sales Employee' && styles.historySalesBadge]}>
              <Text style={[styles.historySourceText, label === 'Sales Employee' && styles.historySalesText]}>{label}</Text>
            </View>
          ))}
        </View>
      )}
      {mode === 'Sales Employee' ? <Text style={styles.rowDetail}>{order.customer_name || order.customer}</Text> : null}
      <View style={styles.historyCardHeading}>
        <Text style={[styles.rowDetail, { flex: 1 }]}>{order.display_status || order.status}</Text>
        {order.entry_type !== 'quick_order' && typeof order.total_quantity === 'number' ? (
          <Text style={styles.rowDetail}>Qty {order.total_quantity}</Text>
        ) : null}
      </View>
      {stamp ? <Text style={styles.helperText}>{order.entry_type === 'quick_order' ? 'Sent' : 'Placed'} {stamp}</Text> : null}
    </FeedbackPressable>
  );
}
