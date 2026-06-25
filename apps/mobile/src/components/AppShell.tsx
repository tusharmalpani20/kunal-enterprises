import React from 'react';
import { Modal, Pressable, SafeAreaView, ScrollView, Text, TextInput, View } from 'react-native';
import { History, LogOut, ShoppingBag, ShoppingCart, UserRound } from 'lucide-react-native';

import { requestBanner } from '../domain/sharedStateFlow.mjs';
import { useOrderFlow } from '../flow/OrderFlowProvider';
import { styles } from '../styles/appStyles';
import { godownStockDetailForSelection } from '../utils/orderFormatting';
import { RowButton, TopLevelTab } from './orderUi';

export function AppShell({ children }: { children: React.ReactNode }) {
  const {
    mode,
    totals,
    greetingName,
    appSection,
    showCartControls,
    showFloatingCartBar,
    selectedCustomer,
    selectedItem,
    stockRows,
    quantity, setQuantity,
    godownSelectorOpen, setGodownSelectorOpen,
    systemState,
    revokeAndLogout,
    showOrder,
    showHistory,
    showProfile,
    switchCustomer,
    setStep,
    addFromGodown,
  } = useOrderFlow();
  const banner = requestBanner(systemState);

  return (
    <SafeAreaView style={styles.shell}>
      <ScrollView contentContainerStyle={styles.page}>
        {banner && (
          <View style={styles.banner}>
            <Text style={styles.bannerTitle}>{banner.title}</Text>
            <Text style={styles.bannerText}>{banner.message}</Text>
          </View>
        )}

        <View style={styles.appHeader}>
          <View style={styles.appHeaderText}>
            <Text style={styles.kicker}>Kunal Enterprises</Text>
            <Text style={styles.title}>{greetingName ? `Hi, ${greetingName}` : 'Welcome'}</Text>
          </View>
          {appSection === 'profile' && (
            <Pressable style={styles.iconOnlyButton} onPress={revokeAndLogout}>
              <LogOut size={17} color="#111111" />
            </Pressable>
          )}
        </View>

        <View style={styles.tabBar}>
          <TopLevelTab
            label="Order"
            active={appSection === 'order'}
            icon={<ShoppingBag size={16} color={appSection === 'order' ? '#FFAF00' : '#111111'} />}
            onPress={showOrder}
          />
          <TopLevelTab
            label="History"
            active={appSection === 'history'}
            icon={<History size={16} color={appSection === 'history' ? '#FFAF00' : '#111111'} />}
            onPress={showHistory}
          />
          <TopLevelTab
            label="Profile"
            active={appSection === 'profile'}
            icon={<UserRound size={16} color={appSection === 'profile' ? '#FFAF00' : '#111111'} />}
            onPress={showProfile}
          />
        </View>

        {showCartControls && mode === 'Sales Employee' && selectedCustomer && (
          <View style={styles.actionRow}>
            <Pressable style={styles.secondaryAction} onPress={switchCustomer}>
              <UserRound size={16} color="#111111" />
              <Text style={styles.secondaryActionText}>Switch customer</Text>
            </Pressable>
          </View>
        )}

        {showCartControls && totals.rowCount === 0 && (
          <Text style={styles.cartHint}>
            Search for an item below and tap Add to start building this order.
          </Text>
        )}

        {children}
      </ScrollView>
      {showFloatingCartBar && (
        <Pressable style={styles.cartBar} onPress={() => setStep('summary')}>
          <View>
            <Text style={styles.cartBarTitle}>{totals.rowCount} items in cart</Text>
            <Text style={styles.cartBarText}>Total quantity {totals.totalQuantity}</Text>
          </View>
          <View style={styles.cartBarAction}>
            <ShoppingCart size={16} color="#ffffff" />
            <Text style={styles.cartBarActionText}>Review</Text>
          </View>
        </Pressable>
      )}
      <Modal visible={godownSelectorOpen} transparent animationType="slide" onRequestClose={() => setGodownSelectorOpen(false)}>
        <View style={styles.modalOverlay}>
          <Pressable style={styles.modalScrim} onPress={() => setGodownSelectorOpen(false)} />
          <View style={styles.bottomSheet}>
            <View style={styles.sheetHandle} />
            <View style={styles.sheetHeader}>
              <Text style={styles.kicker}>Add to order</Text>
              <Text style={styles.workspaceTitle}>{selectedItem?.item_name || 'Select godown'}</Text>
              <Text style={styles.rowDetail}>{selectedItem?.root_stock_group} · {selectedItem?.uom}</Text>
            </View>
            <Text style={styles.fieldLabel}>Quantity to order</Text>
            <TextInput value={quantity} onChangeText={setQuantity} keyboardType="numeric" style={styles.input} />
            <View style={styles.sheetSectionHeading}>
              <Text style={styles.fieldLabel}>Choose godown to order from</Text>
              <Text style={styles.helperText}>
                Tap a godown to add {Number(quantity) > 0 ? quantity : 0} {selectedItem?.uom || 'units'} to your cart.
              </Text>
            </View>
            {stockRows.map((stock) => (
              <RowButton
                key={stock.godown}
                title={stock.godown}
                detail={godownStockDetailForSelection(stock, quantity)}
                onPress={() => addFromGodown(stock)}
                tone={Number(quantity) > stock.quantity ? 'warn' : 'default'}
                actionLabel="Add"
              />
            ))}
            <View style={styles.sheetFooterSpace} />
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}
