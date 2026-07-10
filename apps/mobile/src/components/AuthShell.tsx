import React from 'react';
import { Image, ScrollView, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useOrderFlow } from '../flow/OrderFlowProvider';
import { styles } from '../styles/appStyles';

export function AuthShell({ children }: { children: React.ReactNode }) {
  const { step, customerAuthIntent } = useOrderFlow();

  return (
    <SafeAreaView style={styles.shell}>
      <ScrollView style={styles.shell} contentContainerStyle={[styles.page, styles.authPage]}>
        <View style={styles.authLogoWrap}>
          <Image
            source={require('../../assets/images/logo.png')}
            style={styles.brandLogo}
            resizeMode="contain"
            accessibilityRole="image"
            accessibilityLabel="Kunal Enterprises"
          />
        </View>

        <View style={styles.authCenter}>
          <View style={styles.authHeader}>
            <Text style={styles.authTitle}>
              {step === 'pending'
                ? 'Request received'
                : customerAuthIntent === 'signup'
                  ? 'Create your account'
                  : 'Sign in to order'}
            </Text>
            {step === 'pending' && (
              <Text style={styles.authSubtitle}>Ordering unlocks after approval.</Text>
            )}
          </View>

          {children}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
