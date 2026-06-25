import React from 'react';
import { Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { Search } from 'lucide-react-native';

import { AppShell } from '../../src/components/AppShell';
import { ItemSearchRow, Workspace } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { styles } from '../../src/styles/orderScreen';
import { cartQuantityForItem } from '../../src/utils/orderFormatting';
import type { TallyItem } from '../../src/types';

export default function OrderScreen() {
  const {
    groups,
    selectedGroup,
    chooseGroup,
    renderedGroups,
    renderedItems,
    visibleItems,
    cart,
    chooseItem,
    itemSearch, setItemSearch,
  } = useOrderFlow();

  return (
    <AppShell>
      <Workspace title="Order" icon={<Search size={18} color="#111111" />}>
        <View style={styles.searchPanel}>
          <Text style={styles.fieldLabel}>Search products</Text>
          <TextInput
            value={itemSearch}
            onChangeText={setItemSearch}
            placeholder="Search item or product group"
            style={styles.input}
          />
        </View>
        <Text style={styles.fieldLabel}>Product groups ({groups.length})</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.groupChips}>
          <Pressable style={[styles.groupChip, !selectedGroup && styles.groupChipActive]} onPress={() => chooseGroup(null)}>
            <Text style={[styles.groupChipText, !selectedGroup && styles.groupChipTextActive]}>All</Text>
          </Pressable>
          {renderedGroups.map((group) => (
            <Pressable
              key={group.name}
              style={[styles.groupChip, selectedGroup?.name === group.name && styles.groupChipActive]}
              onPress={() => chooseGroup(group)}
            >
              <Text style={[styles.groupChipText, selectedGroup?.name === group.name && styles.groupChipTextActive]}>
                {group.group_name}
              </Text>
            </Pressable>
          ))}
        </ScrollView>
        {renderedItems.map((item: TallyItem) => (
          <ItemSearchRow
            key={item.name}
            item={item}
            cartQuantity={cartQuantityForItem(cart, item.name)}
            onPress={() => chooseItem(item)}
          />
        ))}
        {visibleItems.length === 0 && (
          <Text style={styles.helperText}>No items match this search and product group filter.</Text>
        )}
        {visibleItems.length > renderedItems.length && (
          <Text style={styles.helperText}>
            Showing {renderedItems.length} of {visibleItems.length} matches. Refine search to narrow results.
          </Text>
        )}
      </Workspace>
    </AppShell>
  );
}
