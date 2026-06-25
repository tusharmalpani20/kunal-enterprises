import React from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';
import { ChevronLeft, ChevronRight, Plus, Trash2 } from 'lucide-react-native';

import { styles } from '../styles/appStyles';
import { formatIndianDate } from '../utils/orderFormatting';
import type { TallyItem } from '../types';

export function RequiredFieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <Text style={styles.fieldLabel}>
      {children}
      <Text style={styles.requiredAsterisk}> *</Text>
    </Text>
  );
}

export function Workspace({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <View style={styles.workspace}>
      <View style={styles.workspaceHeader}>
        {icon}
        <Text style={styles.workspaceTitle}>{title}</Text>
      </View>
      {children}
    </View>
  );
}

export function DraftCartRow({
  title,
  detail,
  onOpen,
  onClear,
}: {
  title: string;
  detail: string;
  onOpen: () => void;
  onClear: () => void;
}) {
  return (
    <View style={styles.draftCartRow}>
      <Pressable style={styles.draftCartOpen} onPress={onOpen}>
        <View style={styles.rowButtonTextBlock}>
          <Text style={styles.rowTitle}>{title}</Text>
          <Text style={styles.rowDetail}>{detail}</Text>
        </View>
        <View style={styles.rowChevron}>
          <ChevronRight size={18} color="#111111" />
        </View>
      </Pressable>
      <Pressable style={styles.draftCartClear} onPress={onClear}>
        <Trash2 size={15} color="#b42318" />
        <Text style={styles.draftCartClearText}>Clear</Text>
      </Pressable>
    </View>
  );
}

export function BackButton({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <Pressable style={styles.backButton} onPress={onPress}>
      <ChevronLeft size={16} color="#111111" />
      <Text style={styles.backButtonText}>{label}</Text>
    </Pressable>
  );
}

export function DatePickerButton({
  value,
  placeholder,
  disabled = false,
  onPress,
}: {
  value: string;
  placeholder: string;
  disabled?: boolean;
  onPress: () => void;
}) {
  const displayValue = formatIndianDate(value);
  return (
    <Pressable style={[styles.datePickerButton, disabled && styles.readOnlyInput]} disabled={disabled} onPress={onPress}>
      <Text style={[styles.datePickerText, !displayValue && styles.placeholderText]}>{displayValue || placeholder}</Text>
    </Pressable>
  );
}

export function ProfileReadOnlyField({ label, value }: { label: string; value: unknown }) {
  return (
    <>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        value={String(value || '')}
        editable={false}
        placeholder="-"
        placeholderTextColor="#9a9a9a"
        style={[styles.input, styles.readOnlyInput]}
      />
    </>
  );
}

export function TopLevelTab({
  label,
  active,
  icon,
  onPress,
}: {
  label: string;
  active: boolean;
  icon: React.ReactNode;
  onPress: () => void;
}) {
  return (
    <Pressable style={[styles.tabButton, active && styles.tabButtonActive]} onPress={onPress}>
      {icon}
      <Text style={[styles.tabButtonText, active && styles.tabButtonTextActive]}>{label}</Text>
    </Pressable>
  );
}

export function RowButton({
  title,
  detail,
  onPress,
  tone = 'default',
  actionLabel,
}: {
  title: string;
  detail: string;
  onPress: () => void;
  tone?: 'default' | 'warn';
  actionLabel?: string;
}) {
  return (
    <Pressable style={[styles.rowButton, tone === 'warn' && styles.warningRow]} onPress={onPress}>
      <View style={styles.rowButtonTextBlock}>
        <Text style={[styles.rowTitle, tone === 'warn' && styles.warningTitle]}>{title}</Text>
        <Text style={[styles.rowDetail, tone === 'warn' && styles.warningDetail]}>{detail}</Text>
      </View>
      {actionLabel ? (
        <View style={styles.rowAddButton}>
          <Plus size={14} color={tone === 'warn' ? '#c2410c' : '#111111'} />
          <Text style={[styles.rowAddButtonText, tone === 'warn' && styles.warningTitle]}>{actionLabel}</Text>
        </View>
      ) : (
        <View style={styles.rowChevron}>
          <ChevronRight size={18} color={tone === 'warn' ? '#c2410c' : '#111111'} />
        </View>
      )}
    </Pressable>
  );
}

export function ItemSearchRow({
  item,
  cartQuantity,
  onPress,
}: {
  item: TallyItem;
  cartQuantity: number;
  onPress: () => void;
}) {
  return (
    <Pressable style={styles.itemRow} onPress={onPress}>
      <View style={styles.itemRowText}>
        <Text style={styles.rowTitle}>{item.item_name}</Text>
        <Text style={styles.rowDetail}>{item.root_stock_group} · {item.uom}</Text>
        <Text style={styles.rowDetail}>Stock {item.total_closing_balance}</Text>
      </View>
      <View style={[styles.itemAddPill, cartQuantity > 0 && styles.itemAddPillActive]}>
        <Text style={[styles.itemAddPillText, cartQuantity > 0 && styles.itemAddPillTextActive]}>
          {cartQuantity > 0 ? `Qty ${cartQuantity}` : 'Add'}
        </Text>
      </View>
    </Pressable>
  );
}
