import React from 'react';
import { Modal, Platform, Pressable, Text, View } from 'react-native';
import DateTimePicker from '@react-native-community/datetimepicker';

import { useOrderFlow } from '../flow/OrderFlowProvider';
import { styles } from '../styles/appStyles';
import { formatIndianDate } from '../utils/orderFormatting';

export function GlobalDateModal() {
  const { datePickerTarget, setDatePickerTarget, activeDatePickerValue, activeDatePickerDate, handleDatePickerChange } =
    useOrderFlow();

  return (
    <Modal visible={Boolean(datePickerTarget)} transparent animationType="slide" onRequestClose={() => setDatePickerTarget(null)}>
      <View style={styles.modalOverlay}>
        <Pressable style={styles.modalScrim} onPress={() => setDatePickerTarget(null)} />
        <View style={styles.bottomSheet}>
          <View style={styles.sheetHandle} />
          <Text style={styles.workspaceTitle}>Select date</Text>
          <Text style={styles.rowDetail}>{formatIndianDate(activeDatePickerValue) || 'DD-MM-YYYY'}</Text>
          {datePickerTarget && (
            <View style={styles.datePickerFrame}>
              <DateTimePicker
                value={activeDatePickerDate}
                mode="date"
                display={Platform.OS === 'ios' ? 'spinner' : 'default'}
                locale="en-IN"
                onChange={handleDatePickerChange}
                style={styles.nativeDatePicker}
              />
            </View>
          )}
          {Platform.OS === 'ios' && (
            <Pressable style={styles.primaryAction} onPress={() => setDatePickerTarget(null)}>
              <Text style={styles.primaryActionText}>Done</Text>
            </Pressable>
          )}
        </View>
      </View>
    </Modal>
  );
}
