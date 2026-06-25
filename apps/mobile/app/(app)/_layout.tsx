import { Stack } from 'expo-router';
import React from 'react';

export default function AppLayout() {
  return (
    <Stack screenOptions={{ headerShown: false }}>
      {/* Top-level sections behave like tabs: swap instantly, no slide. */}
      <Stack.Screen name="order" options={{ animation: 'none' }} />
      <Stack.Screen name="customer" options={{ animation: 'none' }} />
      <Stack.Screen name="history" options={{ animation: 'none' }} />
      <Stack.Screen name="profile" options={{ animation: 'none' }} />
      {/* Drill-down screens keep the default push/slide animation. */}
      <Stack.Screen name="summary" />
      <Stack.Screen name="success" />
      <Stack.Screen name="detail" />
    </Stack>
  );
}
