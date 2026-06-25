import React from 'react';
import { Image, SafeAreaView, ScrollView, Text, View } from 'react-native';

import { requestBanner } from '../domain/sharedStateFlow.mjs';
import { useOrderFlow } from '../flow/OrderFlowProvider';
import { styles } from '../styles/appStyles';

export function AuthShell({ children }: { children: React.ReactNode }) {
  const { step, customerAuthIntent, systemState } = useOrderFlow();
  const banner = requestBanner(systemState);

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
          {banner && (
            <View style={styles.banner}>
              <Text style={styles.bannerTitle}>{banner.title}</Text>
              <Text style={styles.bannerText}>{banner.message}</Text>
            </View>
          )}

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
