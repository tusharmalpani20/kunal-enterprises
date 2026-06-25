import { Stack } from 'expo-router';
import React from 'react';
import Toast from 'react-native-toast-message';
import { useFonts } from '@expo-google-fonts/figtree/useFonts';
import { Figtree_400Regular } from '@expo-google-fonts/figtree/400Regular';
import { Figtree_500Medium } from '@expo-google-fonts/figtree/500Medium';
import { Figtree_600SemiBold } from '@expo-google-fonts/figtree/600SemiBold';

import { AuthProvider } from '../src/providers/auth';
import { FrappeProvider } from '../src/providers/frappe';
import { OrderFlowProvider } from '../src/flow/OrderFlowProvider';
import { GlobalDateModal } from '../src/components/GlobalDateModal';

export default function RootLayout() {
  const [fontsLoaded] = useFonts({
    Figtree_400Regular,
    Figtree_500Medium,
    Figtree_600SemiBold,
  });

  if (!fontsLoaded) {
    return null;
  }

  return (
    <AuthProvider>
      <FrappeProvider>
        <OrderFlowProvider>
          <>
            <Stack screenOptions={{ headerShown: false }} />
            <GlobalDateModal />
            <Toast />
          </>
        </OrderFlowProvider>
      </FrappeProvider>
    </AuthProvider>
  );
}
