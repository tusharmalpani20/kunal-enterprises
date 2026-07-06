import React from 'react';
import { ActivityIndicator, ScrollView, Text, TextInput, View } from 'react-native';
import { Maximize2 } from 'lucide-react-native';
import { AppShell } from '../../src/components/AppShell';
import { FeedbackPressable, GroupLogo, ItemSearchRow } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { colors, styles } from '../../src/styles/appStyles';
import { cartQuantityForItem } from '../../src/utils/orderFormatting';
import type { TallyItem } from '../../src/types';

export default function OrderScreen() {
  const {
    groups,
    catalogLoading,
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
    <AppShell>
      <View style={styles.workspace}>
        <View style={styles.searchPanel}>
          <Text style={styles.fieldLabel}>Search products</Text>
          <TextInput
            value={itemSearch}
            onChangeText={setItemSearch}
            placeholder="Search item or product group"
            style={styles.input}
          />
        </View>
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
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.groupChips}>
          <FeedbackPressable
            style={[styles.groupChip, !selectedGroup && styles.groupChipActive]}
            pressedStyle={!selectedGroup ? styles.groupChipActivePressed : styles.buttonPressed}
            rippleColor={!selectedGroup ? colors.primaryPressed : '#eeeeee'}
            onPress={() => chooseGroup(null)}
          >
            <Text style={[styles.groupChipText, !selectedGroup && styles.groupChipTextActive]}>All</Text>
          </FeedbackPressable>
          {renderedGroups.map((group) => (
            <FeedbackPressable
              key={group.name}
              style={[styles.groupChip, selectedGroup?.name === group.name && styles.groupChipActive]}
              pressedStyle={selectedGroup?.name === group.name ? styles.groupChipActivePressed : styles.buttonPressed}
              rippleColor={selectedGroup?.name === group.name ? colors.primaryPressed : '#eeeeee'}
              onPress={() => chooseGroup(group)}
            >
              <GroupLogo logoUrl={resolveLogoUrl(logoForGroupName(group.name))} size={12} fallbackLabel={group.group_name} style={styles.groupChipLogo} />
              <Text style={[styles.groupChipText, selectedGroup?.name === group.name && styles.groupChipTextActive]}>
                {group.group_name}
              </Text>
            </FeedbackPressable>
          ))}
        </ScrollView>
        {catalogLoading ? (
          <View style={styles.loadingProducts}>
            <ActivityIndicator color="#111111" />
            <Text style={styles.helperText}>Loading products</Text>
          </View>
        ) : renderedItems.map((item: TallyItem) => (
            <ItemSearchRow
              key={item.name}
              item={item}
              logoUrl={resolveLogoUrl(logoForTallyItem(item))}
              cartQuantity={cartQuantityForItem(cart, item.name)}
              onPress={() => chooseItem(item)}
            />
          ))}
        {!catalogLoading && visibleItems.length === 0 && (
          <Text style={styles.helperText}>No items match this search and product group filter.</Text>
        )}
        {!catalogLoading && visibleItems.length > renderedItems.length && (
          <Text style={styles.helperText}>
            Showing {renderedItems.length} of {visibleItems.length} matches. Refine search to narrow results.
          </Text>
        )}
      </View>
    </AppShell>
  );
}
