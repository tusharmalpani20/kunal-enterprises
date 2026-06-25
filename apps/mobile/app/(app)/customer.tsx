import React from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';
import { ChevronRight } from 'lucide-react-native';

import { AppShell } from '../../src/components/AppShell';
import { DraftCartRow, RowButton, Workspace } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { styles } from '../../src/styles/appStyles';

export default function CustomerScreen() {
  const {
    draftCarts,
    draftCartsExpanded, setDraftCartsExpanded,
    customerForDraftCart,
    chooseDraftCart,
    clearDraftCart,
    customers,
    customerSearch, setCustomerSearch,
    chooseCustomer,
  } = useOrderFlow();

  return (
    <AppShell>
      <Workspace title="Select Customer">
        {draftCarts.length > 0 && (
          <View style={styles.draftCartSection}>
            <View style={styles.openCartsWidget}>
              <Pressable style={styles.openCartsHeader} onPress={() => setDraftCartsExpanded((current) => !current)}>
                <View>
                  <Text style={styles.rowTitle}>Open carts</Text>
                  <Text style={styles.rowDetail}>
                    {draftCarts.length} {draftCarts.length === 1 ? 'draft' : 'drafts'} saved
                  </Text>
                </View>
                <ChevronRight
                  size={18}
                  color="#111111"
                  style={draftCartsExpanded && styles.chevronExpanded}
                />
              </Pressable>
              {draftCartsExpanded &&
                draftCarts.map((draft) => {
                  const customer = customerForDraftCart(draft);
                  return (
                    <DraftCartRow
                      key={draft.customer}
                      title={customer?.customer_name || draft.customer}
                      detail={`${draft.rowCount} ${draft.rowCount === 1 ? 'row' : 'rows'} · total quantity ${draft.totalQuantity}`}
                      onOpen={() => chooseDraftCart(draft)}
                      onClear={() => clearDraftCart(draft)}
                    />
                  );
                })}
            </View>
          </View>
        )}
        <TextInput
          value={customerSearch}
          onChangeText={setCustomerSearch}
          placeholder="Search customer"
          placeholderTextColor="#9a9a9a"
          style={styles.input}
        />
        {customers.map((customer) => (
          <RowButton
            key={customer.customer}
            title={customer.customer_name}
            detail={customer.business_legal_name}
            onPress={() => chooseCustomer(customer)}
          />
        ))}
      </Workspace>
    </AppShell>
  );
}
