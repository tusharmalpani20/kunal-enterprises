import React, { useEffect, useState } from 'react';
import { Keyboard, Modal, Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Check, ChevronLeft, History, LogOut, Package, ShoppingBag, ShoppingCart, UserRound } from 'lucide-react-native';
import { useNavigation } from 'expo-router';

import { useOrderFlow } from '../flow/OrderFlowProvider';
import { colors, styles } from '../styles/appStyles';
import { godownStockDetailForSelection } from '../utils/orderFormatting';
import { FeedbackPressable, GroupLogo, RowButton, SpinningRefreshIcon, TopLevelTab } from './orderUi';

export function AppShell({ children }: { children: React.ReactNode }) {
  const navigation = useNavigation();
  const canGoBack = navigation.canGoBack();
  const [keyboardInset, setKeyboardInset] = useState(0);
  const {
    mode,
    step,
    totals,
    appSection,
    showCartControls,
    showFloatingCartBar,
    cart,
    submitOrder,
    selectedCustomer,
    selectedGroup,
    chooseGroup,
    selectedItem,
    stockRows,
    quantity, setQuantity,
    godownSelectorOpen, setGodownSelectorOpen,
    groupSheetOpen, setGroupSheetOpen,
    itemSearch, setItemSearch,
    revokeAndLogout,
    groups,
    logoForGroupName,
    resolveLogoUrl,
    showOrder,
    refreshCatalog,
    catalogLoading,
    showHistory,
    showProfile,
    switchCustomer,
    setStep,
    addFromGodown,
  } = useOrderFlow();
  const showBackButton = canGoBack && step !== 'groups' && step !== 'customer';

  useEffect(() => {
    const showSubscription = Keyboard.addListener('keyboardDidShow', (event) => {
      setKeyboardInset(event.endCoordinates.height);
    });
    const hideSubscription = Keyboard.addListener('keyboardDidHide', () => {
      setKeyboardInset(0);
    });

    return () => {
      showSubscription.remove();
      hideSubscription.remove();
    };
  }, []);

  return (
    <SafeAreaView style={styles.shell}>
      <ScrollView contentContainerStyle={styles.page}>
        <View style={[styles.appHeader, !showBackButton && styles.appHeaderCentered]}>
          <View style={styles.appHeaderText}>
            <Text style={styles.appName}>Kunal Enterprises</Text>
            {showBackButton && (
              <FeedbackPressable style={styles.appHeaderBackButton} onPress={() => navigation.goBack()}>
                <ChevronLeft size={17} color="#111111" />
                <Text style={styles.backButtonText}>Back</Text>
              </FeedbackPressable>
            )}
          </View>
          {appSection === 'order' && (
            <FeedbackPressable
              style={[styles.iconOnlyButton, { borderWidth: 0, backgroundColor: 'transparent' }]}
              onPress={refreshCatalog}
              disabled={catalogLoading}
            >
              <SpinningRefreshIcon size={17} color="#111111" spinning={catalogLoading} />
            </FeedbackPressable>
          )}
          {appSection === 'profile' && (
            <FeedbackPressable style={styles.iconOnlyButton} onPress={revokeAndLogout}>
              <LogOut size={17} color="#111111" />
            </FeedbackPressable>
          )}
        </View>

        <View style={styles.tabBar}>
          <TopLevelTab
            label="Order"
            active={appSection === 'order'}
            icon={<ShoppingBag size={16} color={appSection === 'order' ? colors.onPrimary : '#111111'} />}
            onPress={showOrder}
          />
          <TopLevelTab
            label="History"
            active={appSection === 'history'}
            icon={<History size={16} color={appSection === 'history' ? colors.onPrimary : '#111111'} />}
            onPress={showHistory}
          />
          <TopLevelTab
            label="Profile"
            active={appSection === 'profile'}
            icon={<UserRound size={16} color={appSection === 'profile' ? colors.onPrimary : '#111111'} />}
            onPress={showProfile}
          />
        </View>

        {showCartControls && mode === 'Sales Employee' && selectedCustomer && (
          <View style={styles.actionRow}>
            <FeedbackPressable style={styles.secondaryAction} onPress={switchCustomer}>
              <UserRound size={16} color="#111111" />
              <Text style={styles.secondaryActionText}>Switch customer</Text>
            </FeedbackPressable>
          </View>
        )}

        {children}
      </ScrollView>
      {step === 'summary' && cart.length > 0 ? (
        <FeedbackPressable
          style={styles.cartBar}
          pressedStyle={styles.primaryActionPressed}
          rippleColor={colors.primaryPressed}
          onPress={submitOrder}
        >
          <View>
            <Text style={styles.cartBarTitle}>{totals.rowCount} item{totals.rowCount !== 1 ? 's' : ''} in cart</Text>
            <Text style={styles.cartBarText}>Total quantity {totals.totalQuantity}</Text>
          </View>
          <View style={styles.cartBarAction}>
            <Check size={16} color={colors.onPrimary} />
            <Text style={styles.cartBarActionText}>Confirm</Text>
          </View>
        </FeedbackPressable>
      ) : showFloatingCartBar ? (
        <FeedbackPressable
          style={styles.cartBar}
          pressedStyle={styles.primaryActionPressed}
          rippleColor={colors.primaryPressed}
          onPress={() => setStep('summary')}
        >
          <View>
            <Text style={styles.cartBarTitle}>{totals.rowCount} items in cart</Text>
            <Text style={styles.cartBarText}>Total quantity {totals.totalQuantity}</Text>
          </View>
          <View style={styles.cartBarAction}>
            <ShoppingCart size={16} color={colors.onPrimary} />
            <Text style={styles.cartBarActionText}>Review</Text>
          </View>
        </FeedbackPressable>
      ) : null}
      <Modal visible={godownSelectorOpen} transparent animationType="slide" onRequestClose={() => setGodownSelectorOpen(false)}>
        <View style={styles.modalOverlay}>
          <Pressable style={styles.modalScrim} onPress={() => setGodownSelectorOpen(false)} />
          <View style={styles.bottomSheetHalf}>
            <ScrollView
              contentContainerStyle={styles.bottomSheetContent}
              keyboardShouldPersistTaps="handled"
              showsVerticalScrollIndicator={false}
            >
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
              {keyboardInset > 0 && <View style={{ height: keyboardInset }} />}
            </ScrollView>
          </View>
        </View>
      </Modal>
      <Modal visible={groupSheetOpen} transparent animationType="slide" onRequestClose={() => setGroupSheetOpen(false)}>
        <View style={styles.modalOverlay}>
          <Pressable style={styles.modalScrim} onPress={() => setGroupSheetOpen(false)} />
          <View style={styles.bottomSheetTall}>
            <View style={styles.sheetStickyHeader}>
              <View style={styles.sheetHandle} />
              <View style={styles.sheetHeader}>
                <Text style={styles.kicker}>Browse products</Text>
                <Text style={styles.workspaceTitle}>All Product Groups</Text>
              </View>
              <TextInput
                value={itemSearch}
                onChangeText={setItemSearch}
                placeholder="Search product groups"
                placeholderTextColor="#9a9a9a"
                style={[styles.input, styles.groupSheetSearch]}
              />
            </View>
            <ScrollView
              contentContainerStyle={styles.bottomSheetContent}
              keyboardShouldPersistTaps="handled"
              showsVerticalScrollIndicator={false}
            >
              <FeedbackPressable
                style={[styles.groupSheetRow, !selectedGroup && styles.groupSheetRowActive]}
                pressedStyle={!selectedGroup ? styles.groupSheetRowActive : styles.groupSheetRowPressed}
                onPress={() => { chooseGroup(null); setGroupSheetOpen(false); }}
              >
                <View style={styles.groupSheetRowLogo}>
                  <Package size={18} color="#9a9a9a" />
                </View>
                <Text style={styles.groupSheetRowTitle}>All Products</Text>
              </FeedbackPressable>
              {groups.filter((group) => {
                const query = itemSearch.trim().toLowerCase();
                if (!query) return true;
                return [group.group_name, group.full_path, group.name].some((v) => String(v || '').toLowerCase().includes(query));
              }).map((group) => (
                <FeedbackPressable
                  key={group.name}
                  style={[styles.groupSheetRow, selectedGroup?.name === group.name && styles.groupSheetRowActive]}
                  pressedStyle={selectedGroup?.name === group.name ? styles.groupSheetRowActive : styles.groupSheetRowPressed}
                  onPress={() => { chooseGroup(group); setGroupSheetOpen(false); }}
                >
                  <GroupLogo
                    logoUrl={resolveLogoUrl(logoForGroupName(group.name))}
                    size={18}
                    fallbackLabel={group.group_name}
                    style={styles.groupSheetRowLogo}
                  />
                  <Text style={styles.groupSheetRowTitle}>{group.group_name}</Text>
                </FeedbackPressable>
              ))}
              <View style={styles.sheetFooterSpace} />
              {keyboardInset > 0 && <View style={{ height: keyboardInset }} />}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}
