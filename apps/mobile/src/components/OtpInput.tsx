import React, { useRef } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { fonts } from '../styles/appStyles';

interface OtpInputProps {
  otpValue: string;
  onOtpChange: (otp: string) => void;
  length?: number;
}

export function OtpInput({ otpValue, onOtpChange, length = 4 }: OtpInputProps) {
  const inputRef = useRef<TextInput>(null);
  const cells = Array.from({ length }, (_, i) => otpValue[i] ?? '');

  const handleChange = (value: string) => {
    const digits = value.replace(/\D/g, '').slice(0, length);
    onOtpChange(digits);
  };

  const focusInput = () => {
    inputRef.current?.focus();
  };

  return (
    <Pressable onPress={focusInput} style={otpStyles.container}>
      <TextInput
        ref={inputRef}
        testID="otp-input"
        value={otpValue}
        onChangeText={handleChange}
        keyboardType="number-pad"
        textContentType="oneTimeCode"
        maxLength={length}
        autoFocus
        caretHidden
        style={otpStyles.hiddenInput}
      />
      <View style={otpStyles.row}>
        {cells.map((char, index) => (
          <Text key={index} style={otpStyles.cell}>
            {char}
          </Text>
        ))}
      </View>
    </Pressable>
  );
}

const otpStyles = StyleSheet.create({
  container: {
    position: 'relative',
  },
  hiddenInput: {
    position: 'absolute',
    bottom: 0,
    width: '100%',
    height: 1,
    opacity: 0,
  },
  row: {
    flexDirection: 'row',
    gap: 16,
  },
  cell: {
    flex: 1,
    height: 64,
    borderWidth: 1,
    borderColor: '#d8d8d8',
    borderRadius: 8,
    backgroundColor: '#ffffff',
    color: '#111111',
    fontSize: 22,
    lineHeight: 64,
    textAlign: 'center',
    fontFamily: fonts.medium,
  },
});
