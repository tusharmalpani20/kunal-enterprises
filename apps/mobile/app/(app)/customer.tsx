import React from 'react';
import { ActivityIndicator, Text, TextInput, View } from 'react-native';
import { ChevronRight } from 'lucide-react-native';

import { AppShell } from '../../src/components/AppShell';
import { DraftCartRow, FeedbackPressable, RowButton, Workspace } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { MAX_CUSTOMER_SEARCH_RESULTS, MIN_CUSTOMER_SEARCH_LENGTH } from '../../src/domain/salesEmployeeFlow.mjs';
import { styles } from '../../src/styles/appStyles';

export default function CustomerScreen() {
  const {
    draftCarts,
    draftCartsExpanded, setDraftCartsExpanded,
    customerForDraftCart,
    chooseDraftCart,
    clearDraftCart,
    customers,
    customerSearchLoading,
    customerSearch, setCustomerSearch,
    chooseCustomer,
  } = useOrderFlow();

  return (
    <AppShell>
      <Workspace title="Select Customer">
        {draftCarts.length > 0 && (
          <View style={styles.draftCartSection}>
            <View style={styles.openCartsWidget}>
              <FeedbackPressable style={styles.openCartsHeader} onPress={() => setDraftCartsExpanded((current) => !current)}>
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
              </FeedbackPressable>
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
        {customerSearchLoading && (
          <View style={styles.loadingProducts}>
            <ActivityIndicator color="#111111" />
            <Text style={styles.helperText}>Searching customers</Text>
          </View>
        )}
        {!customerSearchLoading && customerSearch.trim().length === 1 && (
          <Text style={styles.helperText}>Enter at least 2 characters to search customers.</Text>
        )}
        {!customerSearchLoading && customers.map((customer) => (
          <RowButton
            key={customer.customer}
            title={customer.customer_name}
            detail={customer.business_legal_name}
            onPress={() => chooseCustomer(customer)}
          />
        ))}
        {!customerSearchLoading && customerSearch.trim().length >= MIN_CUSTOMER_SEARCH_LENGTH && customers.length === 0 && (
          <Text style={styles.helperText}>No customers match this search.</Text>
        )}
        {!customerSearchLoading && customers.length === MAX_CUSTOMER_SEARCH_RESULTS && (
          <Text style={styles.helperText}>Showing the first {MAX_CUSTOMER_SEARCH_RESULTS} matches. Refine your search for more.</Text>
        )}
      </Workspace>
    </AppShell>
  );
}
