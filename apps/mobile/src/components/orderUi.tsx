import React, { useEffect, useState } from 'react';
import { Image, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import type { PressableProps, StyleProp, ViewStyle } from 'react-native';
import { ChevronLeft, ChevronRight, Package, Plus, Trash2 } from 'lucide-react-native';

import { colors, styles } from '../styles/appStyles';
import { formatIndianDate } from '../utils/orderFormatting';
import type { TallyItem } from '../types';

type FeedbackPressableProps = PressableProps & {
  pressedStyle?: StyleProp<ViewStyle>;
  rippleColor?: string;
};

export function FeedbackPressable({
  style,
  pressedStyle = styles.buttonPressed,
  rippleColor = '#eeeeee',
  ...props
}: FeedbackPressableProps) {
  return (
    <Pressable
      {...props}
      android_ripple={{ color: rippleColor, ...props.android_ripple }}
      style={({ pressed }) => [style as StyleProp<ViewStyle>, pressed && pressedStyle]}
    />
  );
}

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
      <FeedbackPressable style={styles.draftCartOpen} onPress={onOpen}>
        <View style={styles.rowButtonTextBlock}>
          <Text style={styles.rowTitle}>{title}</Text>
          <Text style={styles.rowDetail}>{detail}</Text>
        </View>
        <View style={styles.rowChevron}>
          <ChevronRight size={18} color="#111111" />
        </View>
      </FeedbackPressable>
      <FeedbackPressable style={styles.draftCartClear} onPress={onClear} rippleColor="#fee2e2" pressedStyle={styles.dangerButtonPressed}>
        <Trash2 size={15} color="#b42318" />
        <Text style={styles.draftCartClearText}>Clear</Text>
      </FeedbackPressable>
    </View>
  );
}

export function BackButton({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <FeedbackPressable style={styles.backButton} onPress={onPress}>
      <ChevronLeft size={16} color="#111111" />
      <Text style={styles.backButtonText}>{label}</Text>
    </FeedbackPressable>
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
    <FeedbackPressable style={[styles.datePickerButton, disabled && styles.readOnlyInput]} disabled={disabled} onPress={onPress}>
      <Text style={[styles.datePickerText, !displayValue && styles.placeholderText]}>{displayValue || placeholder}</Text>
    </FeedbackPressable>
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
    <FeedbackPressable
      style={[styles.tabButton, active && styles.tabButtonActive]}
      pressedStyle={active ? styles.tabButtonActivePressed : styles.buttonPressed}
      rippleColor={active ? colors.primaryPressed : '#eeeeee'}
      onPress={onPress}
    >
      {icon}
      <Text style={[styles.tabButtonText, active && styles.tabButtonTextActive]}>{label}</Text>
    </FeedbackPressable>
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
    <FeedbackPressable
      rippleColor={tone === 'warn' ? '#fed7aa' : '#eeeeee'}
      pressedStyle={tone === 'warn' ? styles.warningRowPressed : styles.rowButtonPressed}
      style={[styles.rowButton, tone === 'warn' && styles.warningRow]}
      onPress={onPress}
    >
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
    </FeedbackPressable>
  );
}

export function GroupLogo({
  logoUrl,
  size,
  fallbackLabel,
  style,
}: {
  logoUrl?: string | null;
  size: number;
  fallbackLabel?: string;
  style?: StyleProp<ViewStyle>;
}) {
  const resolved = logoUrl || null;
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setFailed(false);
  }, [resolved]);

  if (resolved && !failed) {
    return (
      <View style={[style, { alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }]}>
        <Image
          source={{ uri: resolved }}
          style={StyleSheet.absoluteFillObject}
          resizeMode="contain"
          onError={(error) => {
            console.log(`[GroupLogo] image load failed for ${fallbackLabel || 'unknown'}: ${resolved}`, error?.nativeEvent?.error || '');
            setFailed(true);
          }}
          onLoad={() => {
            console.log(`[GroupLogo] image loaded for ${fallbackLabel || 'unknown'}: ${resolved}`);
          }}
          accessibilityRole="image"
          accessibilityLabel={fallbackLabel || 'Product group'}
        />
      </View>
    );
  }
  return (
    <View
      style={[style, { alignItems: 'center', justifyContent: 'center' }]}
      accessibilityRole="image"
      accessibilityLabel={fallbackLabel || 'Product group'}
    >
      <Package size={size} color="#9a9a9a" />
    </View>
  );
}

export function ItemSearchRow({
  item,
  cartQuantity,
  logoUrl,
  onPress,
}: {
  item: TallyItem;
  cartQuantity: number;
  logoUrl?: string | null;
  onPress: () => void;
}) {
  return (
    <FeedbackPressable style={styles.itemRow} pressedStyle={styles.rowButtonPressed} onPress={onPress}>
      <GroupLogo logoUrl={logoUrl} size={24} fallbackLabel={item.item_name} style={styles.itemRowLogo} />
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
    </FeedbackPressable>
  );
}
