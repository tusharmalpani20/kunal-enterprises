import React, { useEffect, useRef, useState } from 'react';
import { Keyboard, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, Text, TextInput, View } from 'react-native';
import { useOrderFlow } from '../flow/OrderFlowProvider';
import { QUICK_ORDER_TEXT_LIMIT } from '../domain/quickOrderFlow.mjs';
import { colors, styles } from '../styles/appStyles';
import { FeedbackPressable } from './orderUi';
import Toast from 'react-native-toast-message';

export function QuickOrderForm({ onSubmitted }: { onSubmitted?: () => void } = {}) {
  const { quickOrders } = useOrderFlow();
  const { text, setText, submitting, error, submit } = quickOrders;
  async function submitRequest() {
    const request = await submit();
    if (!request) return;
    Keyboard.dismiss();
    onSubmitted?.();
    Toast.show({ type: 'success', text1: 'Request sent', text2: 'Our team will review your order request.' });
  }
  return (
    <View style={styles.workspace}>
      <Text style={styles.rowDetail}>Type or paste the items and quantities you need. Our team will review your request and create an order.</Text>
      <Text style={styles.fieldLabel}>Your request</Text>
      <TextInput
        value={text}
        onChangeText={setText}
        multiline
        maxLength={QUICK_ORDER_TEXT_LIMIT}
        editable={!submitting}
        accessibilityLabel="Your order request"
        placeholder="For example: 2 cotton rolls and 3 lining rolls"
        placeholderTextColor="#9a9a9a"
        style={[styles.input, { minHeight: 140, textAlignVertical: 'top' }]}
      />
      <Text style={styles.helperText}>Submitted requests cannot be edited or cancelled.</Text>
      <FeedbackPressable
        style={styles.primaryAction}
        pressedStyle={styles.primaryActionPressed}
        rippleColor={colors.primaryPressed}
        disabled={submitting || !text.trim()}
        onPress={submitRequest}
      >
        <Text style={styles.primaryActionText}>{submitting ? 'Submitting...' : 'Submit request'}</Text>
      </FeedbackPressable>
      {error ? <Text style={styles.note}>{error}</Text> : null}
    </View>
  );
}

export function QuickOrderModal({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const { quickOrders, quickOrdersEnabled } = useOrderFlow();
  const { text, setText, submitting } = quickOrders;
  const warningOpen = useRef(false);
  const [showWarning, setShowWarning] = useState(false);

  function keepEditing() {
    warningOpen.current = false;
    setShowWarning(false);
  }

  useEffect(() => {
    if (!visible || !quickOrdersEnabled) keepEditing();
  }, [visible, quickOrdersEnabled]);

  function requestClose() {
    // Keep the request visible until submission finishes, and protect every dismissal path.
    if (quickOrders.isSubmitting()) return;
    if (warningOpen.current) { keepEditing(); return; }
    if (!text.trim()) { onClose(); return; }
    warningOpen.current = true;
    Keyboard.dismiss();
    setShowWarning(true);
  }

  return (
    <Modal visible={visible && quickOrdersEnabled} transparent animationType="slide" onRequestClose={requestClose}>
      <KeyboardAvoidingView style={styles.modalOverlay} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
        <Pressable style={styles.modalScrim} accessibilityLabel="Close Quick Order" accessibilityRole="button" onPress={requestClose} importantForAccessibility={showWarning ? 'no-hide-descendants' : 'auto'} />
        <View style={styles.bottomSheetTall} accessibilityElementsHidden={showWarning} importantForAccessibility={showWarning ? 'no-hide-descendants' : 'auto'}>
          <ScrollView contentContainerStyle={styles.bottomSheetContent} keyboardShouldPersistTaps="handled">
            <View style={styles.sheetHandle} />
            <View style={styles.appHeaderActions}>
              <Text style={[styles.workspaceTitle, { flex: 1 }]}>Quick Order</Text>
              <FeedbackPressable onPress={requestClose} disabled={submitting} style={styles.iconOnlyButton} accessibilityLabel="Close Quick Order">
                <Text style={styles.rowDetail}>✕</Text>
              </FeedbackPressable>
            </View>
            <QuickOrderForm onSubmitted={onClose} />
          </ScrollView>
        </View>
        {showWarning && (
          <View style={styles.draftWarningOverlay}>
            <Pressable style={styles.modalScrim} onPress={keepEditing} accessibilityRole="button" accessibilityLabel="Keep Editing" />
            <View style={styles.draftWarningCard} accessibilityViewIsModal>
              <Text style={styles.workspaceTitle} accessibilityRole="header">Discard your request?</Text>
              <Text style={styles.rowDetail}>Your written text will be lost.</Text>
              <View style={styles.actionRow}>
                <FeedbackPressable style={[styles.primaryAction, styles.draftWarningAction]} pressedStyle={styles.primaryActionPressed} rippleColor={colors.primaryPressed} onPress={keepEditing} accessibilityRole="button">
                  <Text style={styles.primaryActionText}>Keep Editing</Text>
                </FeedbackPressable>
                <FeedbackPressable style={[styles.secondaryAction, styles.draftWarningAction]} pressedStyle={styles.dangerButtonPressed} onPress={() => {
                  keepEditing();
                  setText('');
                  onClose();
                }} accessibilityRole="button">
                  <Text style={[styles.secondaryActionText, { color: '#b42318' }]}>Discard</Text>
                </FeedbackPressable>
              </View>
            </View>
          </View>
        )}
      </KeyboardAvoidingView>
    </Modal>
  );
}
