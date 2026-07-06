import React from 'react';
import { Text, TextInput, View } from 'react-native';
import { Check, Minus, Plus, ShoppingCart, Trash2 } from 'lucide-react-native';

import { AppShell } from '../../src/components/AppShell';
import { FeedbackPressable, GroupLogo, Workspace } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { colors, styles } from '../../src/styles/appStyles';
import type { CartAllocation } from '../../src/types';

export default function SummaryScreen() {
  const {
    mode,
    selectedCustomer,
    salesNote, setSalesNote,
    cart,
    groupedCart,
    notes,
    changeCartQuantity,
    removeCartItem,
    logoForItemName,
    resolveLogoUrl,
    setStep,
  } = useOrderFlow();

  if (cart.length === 0) {
    return (
      <AppShell>
        <Workspace title="Order Summary" icon={<Check size={18} color="#111111" />}>
          {mode === 'Sales Employee' && selectedCustomer && (
            <View style={styles.contextBlock}>
              <Text style={styles.fieldLabel}>Customer</Text>
              <Text style={styles.rowTitle}>{selectedCustomer.customer_name}</Text>
              <Text style={styles.rowDetail}>{selectedCustomer.business_legal_name}</Text>
            </View>
          )}
          <View style={{ alignItems: 'center', gap: 12, paddingVertical: 32 }}>
            <ShoppingCart size={32} color="#9a9a9a" />
            <Text style={styles.workspaceTitle}>Your cart is empty</Text>
          </View>
          <FeedbackPressable
            style={[styles.primaryAction, { marginTop: 8 }]}
            pressedStyle={styles.primaryActionPressed}
            rippleColor={colors.primaryPressed}
            onPress={() => setStep('groups')}
          >
            <Plus size={16} color={colors.onPrimary} />
            <Text style={styles.primaryActionText}>Add products</Text>
          </FeedbackPressable>
        </Workspace>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <Workspace title="Order Summary" icon={<Check size={18} color="#111111" />}>
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
        {groupedCart.map((group, index) => (
          <View key={group.groupName}>
            <View style={styles.groupSectionHeader}>
              <GroupLogo
                logoUrl={resolveLogoUrl(group.groupLogo)}
                size={18}
                fallbackLabel={group.groupName}
                style={styles.groupSectionLogo}
              />
              <Text style={styles.groupSectionTitle}>{group.groupName}</Text>
            </View>
            {group.rows.map((row: CartAllocation, rowIndex: number) => {
              const isLastRow = rowIndex === group.rows.length - 1;
              return (
              <View key={`${row.item}:${row.godown}`} style={[styles.summaryLine, isLastRow && { borderBottomWidth: 0 }]}>
                <GroupLogo
                  logoUrl={resolveLogoUrl(logoForItemName(row.item))}
                  size={24}
                  fallbackLabel={row.itemName}
                  style={styles.itemRowLogo}
                />
                <View style={styles.summaryItemText}>
                  <Text style={[styles.rowTitle, styles.summaryItemTitle]}>{row.itemName}</Text>
                  <Text style={styles.rowDetail}>{row.godown}</Text>
                </View>
                <View style={styles.cartControls}>
                  <FeedbackPressable style={styles.iconButton} pressedStyle={styles.iconButtonPressed} onPress={() => changeCartQuantity(row, -1)}>
                    <Minus size={16} color="#111111" />
                  </FeedbackPressable>
                  <Text style={styles.quantity}>{row.quantity}</Text>
                  <FeedbackPressable style={styles.iconButton} pressedStyle={styles.iconButtonPressed} onPress={() => changeCartQuantity(row, 1)}>
                    <Plus size={16} color="#111111" />
                  </FeedbackPressable>
                  <FeedbackPressable style={styles.iconButton} pressedStyle={styles.iconButtonPressed} onPress={() => removeCartItem(row.item)}>
                    <Trash2 size={16} color="#111111" />
                  </FeedbackPressable>
                </View>
              </View>
              );
            })}
            {index < groupedCart.length - 1 && <View style={styles.groupDivider} />}
          </View>
        ))}
        {notes.map((note) => (
          <Text key={note} style={styles.note}>{note}</Text>
        ))}
      </Workspace>
    </AppShell>
  );
}
