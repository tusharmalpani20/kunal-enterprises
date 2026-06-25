import React from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';
import { Check, Minus, Plus, Trash2 } from 'lucide-react-native';

import { AppShell } from '../../src/components/AppShell';
import { BackButton, Workspace } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { styles } from '../../src/styles/orderScreen';

export default function SummaryScreen() {
  const {
    mode,
    selectedCustomer,
    salesNote, setSalesNote,
    cart,
    notes,
    backToItems,
    changeCartQuantity,
    removeCartItem,
    submitOrder,
  } = useOrderFlow();

  return (
    <AppShell>
      <Workspace title="Order Summary" icon={<Check size={18} color="#111111" />}>
        <BackButton label="Back to product search" onPress={backToItems} />
        {mode === 'Sales Employee' && selectedCustomer && (
          <View style={styles.contextBlock}>
            <Text style={styles.fieldLabel}>Customer</Text>
            <Text style={styles.rowTitle}>{selectedCustomer.customer_name}</Text>
            <Text style={styles.rowDetail}>{selectedCustomer.business_legal_name}</Text>
            <Text style={styles.fieldLabel}>Internal note</Text>
            <TextInput
              value={salesNote}
              onChangeText={setSalesNote}
              placeholder="Add dispatch note for internal team"
              placeholderTextColor="#9a9a9a"
              style={styles.input}
            />
          </View>
        )}
        {cart.map((row) => (
          <View key={`${row.item}:${row.godown}`} style={styles.summaryLine}>
            <View style={styles.summaryItemText}>
              <Text style={[styles.rowTitle, styles.summaryItemTitle]}>{row.itemName}</Text>
              <Text style={styles.rowDetail}>{row.godown}</Text>
            </View>
            <View style={styles.cartControls}>
              <Pressable style={styles.iconButton} onPress={() => changeCartQuantity(row, -1)}>
                <Minus size={16} color="#111111" />
              </Pressable>
              <Text style={styles.quantity}>{row.quantity}</Text>
              <Pressable style={styles.iconButton} onPress={() => changeCartQuantity(row, 1)}>
                <Plus size={16} color="#111111" />
              </Pressable>
              <Pressable style={styles.iconButton} onPress={() => removeCartItem(row.item)}>
                <Trash2 size={16} color="#111111" />
              </Pressable>
            </View>
          </View>
        ))}
        {notes.map((note) => (
          <Text key={note} style={styles.note}>{note}</Text>
        ))}
        <Pressable style={styles.primaryAction} onPress={submitOrder}>
          <Text style={styles.primaryActionText}>Confirm order</Text>
        </Pressable>
      </Workspace>
    </AppShell>
  );
}
