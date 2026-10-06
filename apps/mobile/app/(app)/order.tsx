import React, { useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, Text, TextInput, View } from 'react-native';
import { ChevronDown, Maximize2 } from 'lucide-react-native';
import { AppShell } from '../../src/components/AppShell';
import { QuickOrderModal } from '../../src/components/QuickOrderModal';
import { FeedbackPressable, GroupLogo, ItemSearchRow } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { colors, styles } from '../../src/styles/appStyles';
import { cartQuantityForItem } from '../../src/utils/orderFormatting';
import type { TallyItem } from '../../src/types';

export default function OrderScreen() {
  const [quickOrderOpen, setQuickOrderOpen] = useState(false);
  const {
    quickOrdersEnabled,
    groups,
    itemsLoading,
    itemsTotalCount, itemsAllCount, itemsHasMore, itemsMoreLoading, loadMoreItems,
    selectedGroup,
    chooseGroup,
    renderedGroups,
    renderedItems,
    visibleItems,
    cart,
    chooseItem,
    itemSearch, setItemSearch,
    groupSheetOpen, setGroupSheetOpen,
    logoForGroupName,
    logoForTallyItem,
    resolveLogoUrl,
  } = useOrderFlow();

  return (
    <>
    <AppShell itemList={{
      searchHeader: (
        <View style={styles.searchPanel}>
          <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
            <Text style={styles.fieldLabel}>Search products</Text>
            {quickOrdersEnabled && (
              <FeedbackPressable onPress={() => setQuickOrderOpen(true)} style={{ paddingVertical: 10, paddingHorizontal: 4 }} accessibilityRole="button">
                <Text style={[styles.utilityText, { color: colors.brandGreen, textDecorationLine: 'underline' }]}>Quick Order</Text>
              </FeedbackPressable>
            )}
          </View>
          <TextInput
            value={itemSearch}
            onChangeText={setItemSearch}
            placeholder="Search item or product group"
            style={styles.input}
          />
        </View>
      ),
      items: itemsLoading ? [] : renderedItems,
      renderItem: (item: TallyItem) => (
        <ItemSearchRow
          item={item}
          logoUrl={resolveLogoUrl(logoForTallyItem(item))}
          cartQuantity={cartQuantityForItem(cart, item.name)}
          onPress={() => chooseItem(item)}
        />
      ),
      footer: !itemsLoading && itemsTotalCount !== null ? (
        <View style={{ gap: 12, alignItems: 'center', paddingTop: 20, paddingBottom: 24 }}>
          <Text style={styles.helperText}>Showing {renderedItems.length} of {itemsTotalCount} products</Text>
          {itemsHasMore && <FeedbackPressable
            style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, minHeight: 44, paddingHorizontal: 24, paddingVertical: 10, borderRadius: 24, backgroundColor: colors.brandGreen }}
            pressedStyle={styles.primaryActionPressed}
            onPress={loadMoreItems} disabled={itemsMoreLoading} accessibilityRole="button"
          >
            {itemsMoreLoading ? <ActivityIndicator color={colors.onPrimary} /> : <ChevronDown size={16} color={colors.onPrimary} />}
            <Text style={[styles.secondaryActionText, { color: colors.onPrimary }]}>{itemsMoreLoading ? 'Loading more…' : 'Load more'}</Text>
          </FeedbackPressable>}
        </View>
      ) : null,
    }}>
      <View style={styles.workspace}>
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <Text style={styles.fieldLabel}>Product groups ({groups.length})</Text>
          <FeedbackPressable
            style={{ padding: 4 }}
            pressedStyle={styles.iconButtonPressed}
            onPress={() => setGroupSheetOpen(true)}
          >
            <Maximize2 size={12} color="#111111" />
          </FeedbackPressable>
        </View>
        <FlatList
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.groupChips}
          data={[null, ...renderedGroups]}
          keyExtractor={group => group ? `group:${group.name}` : 'all'}
          initialNumToRender={8}
          maxToRenderPerBatch={8}
          windowSize={5}
          extraData={`${selectedGroup?.name || ''}:${itemsAllCount}`}
          renderItem={({ item: group }) => {
            const active = group ? selectedGroup?.name === group.name : !selectedGroup;
            return (
              <Pressable
                style={[styles.groupChip, active && styles.groupChipActive]}
                android_ripple={{ color: active ? colors.primaryPressed : '#eeeeee' }}
                accessibilityRole="button"
                accessibilityState={{ selected: active }}
                onPress={() => chooseGroup(group)}
              >
                {group ? <GroupLogo logoUrl={resolveLogoUrl(logoForGroupName(group.name))} size={12} fallbackLabel={group.group_name} style={styles.groupChipLogo} /> : null}
                <Text style={[styles.groupChipText, active && styles.groupChipTextActive]}>
                  {group?.group_name || (itemsAllCount === null ? 'All' : `All (${itemsAllCount})`)}
                </Text>
              </Pressable>
            );
          }}
        />
        {itemsLoading ? (
          <View style={styles.loadingProducts}>
            <ActivityIndicator color="#111111" />
            <Text style={styles.helperText}>Loading products</Text>
          </View>
        ) : null}
        {!itemsLoading && visibleItems.length === 0 && (
          <Text style={styles.helperText}>No items match this search and product group filter.</Text>
        )}
      </View>
    </AppShell>
    <QuickOrderModal visible={quickOrderOpen} onClose={() => setQuickOrderOpen(false)} />
    </>
  );
}
