import React from 'react';
import { Modal, Pressable, SafeAreaView, ScrollView, Text, TextInput, View } from 'react-native';
import { History, LogOut, ShoppingBag, ShoppingCart, UserRound } from 'lucide-react-native';

import { requestBanner } from '../domain/sharedStateFlow.mjs';
import { useOrderFlow } from '../flow/OrderFlowProvider';
import { styles } from '../styles/orderScreen';
import { godownStockDetailForSelection } from '../utils/orderFormatting';
import { RowButton, TopLevelTab } from './orderUi';

export function AppShell({ children }: { children: React.ReactNode }) {
  const {
    mode,
    totals,
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
            <Text style={styles.kicker}>{mode === 'Customer' ? 'Customer order' : 'Sales employee order'}</Text>
            <Text style={styles.title}>Kunal Enterprises</Text>
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
            icon={<ShoppingBag size={16} color={appSection === 'order' ? '#ffffff' : '#111111'} />}
            onPress={showOrder}
          />
          <TopLevelTab
            label="History"
            active={appSection === 'history'}
            icon={<History size={16} color={appSection === 'history' ? '#ffffff' : '#111111'} />}
            onPress={showHistory}
          />
          <TopLevelTab
            label="Profile"
            active={appSection === 'profile'}
            icon={<UserRound size={16} color={appSection === 'profile' ? '#ffffff' : '#111111'} />}
            onPress={showProfile}
          />
        </View>

        {showCartControls && (
          <View style={styles.statusStrip}>
            <View>
              <Text style={styles.metricLabel}>Cart quantity</Text>
              <Text style={styles.metric}>{totals.totalQuantity}</Text>
            </View>
            <View>
              <Text style={styles.metricLabel}>Rows</Text>
              <Text style={styles.metric}>{totals.rowCount}</Text>
            </View>
          </View>
        )}
        {showCartControls && (
          <View style={styles.actionRow}>
            {mode === 'Sales Employee' && selectedCustomer && (
              <Pressable style={styles.secondaryAction} onPress={switchCustomer}>
                <UserRound size={16} color="#111111" />
                <Text style={styles.secondaryActionText}>Switch customer</Text>
              </Pressable>
            )}
            <Pressable
              style={[styles.secondaryAction, totals.rowCount === 0 && styles.disabledAction]}
              disabled={totals.rowCount === 0}
              onPress={() => setStep('summary')}
            >
              <ShoppingCart size={16} color={totals.rowCount === 0 ? '#8a8a8a' : '#111111'} />
              <Text style={[styles.secondaryActionText, totals.rowCount === 0 && styles.disabledActionText]}>
                {totals.rowCount === 0 ? 'Cart is empty' : 'Review order'}
              </Text>
            </Pressable>
          </View>
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
            <Text style={styles.workspaceTitle}>{selectedItem?.item_name || 'Select godown'}</Text>
            <Text style={styles.rowDetail}>{selectedItem?.root_stock_group} · {selectedItem?.uom}</Text>
            <Text style={styles.fieldLabel}>Quantity</Text>
            <TextInput value={quantity} onChangeText={setQuantity} keyboardType="numeric" style={styles.input} />
            <Text style={styles.fieldLabel}>Godown stock</Text>
            {stockRows.map((stock) => (
              <RowButton
                key={stock.godown}
                title={stock.godown}
                detail={godownStockDetailForSelection(stock, quantity)}
                onPress={() => addFromGodown(stock)}
                tone={Number(quantity) > stock.quantity ? 'warn' : 'default'}
              />
            ))}
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}
