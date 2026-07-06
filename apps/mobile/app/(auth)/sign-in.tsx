import React from 'react';
import { Text, TextInput, View } from 'react-native';
import { ChevronLeft } from 'lucide-react-native';

import { AuthShell } from '../../src/components/AuthShell';
import { DatePickerButton, FeedbackPressable, RequiredFieldLabel } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { colors, styles } from '../../src/styles/appStyles';

export default function SignInScreen() {
  const {
    mobileNumber, setMobileNumber,
    otpCode, setOtpCode,
    customerAuthIntent, setCustomerAuthIntent,
    signupDetailsReview, setSignupDetailsReview,
    signupCustomerName, setSignupCustomerName,
    signupBusinessLegalName, setSignupBusinessLegalName,
    signupGstin, setSignupGstin,
    signupEmailId, setSignupEmailId,
    signupDateOfBirth,
    signupDateOfAnniversary,
    setDatePickerTarget,
    setOtpIdentityType,
    setOtpSentAtMs,
    setLastOtpRequestKey,
    setMode,
    setSystemState,
    resend,
    isSignupOtpFlow,
    showSignupDetails,
    signupDetailsReadOnly,
    otpRequestedForCurrentFlow,
    requestOtp,
    verifyOtp,
    editSignupDetails,
  } = useOrderFlow();

  return (
    <AuthShell>
      <View style={styles.authForm}>
        {(!isSignupOtpFlow || signupDetailsReview) && (
          <>
            <RequiredFieldLabel>Mobile Number</RequiredFieldLabel>
            <TextInput
              value={mobileNumber}
              onChangeText={setMobileNumber}
              editable={!signupDetailsReadOnly}
              keyboardType="phone-pad"
              placeholder="Enter mobile number"
              placeholderTextColor="#9a9a9a"
              style={[styles.input, signupDetailsReadOnly && styles.readOnlyInput]}
            />
          </>
        )}
        {showSignupDetails && (
          <>
            <RequiredFieldLabel>Customer Name</RequiredFieldLabel>
            <TextInput
              value={signupCustomerName}
              onChangeText={setSignupCustomerName}
              editable={!signupDetailsReadOnly}
              placeholder="Enter customer name"
              placeholderTextColor="#9a9a9a"
              style={[styles.input, signupDetailsReadOnly && styles.readOnlyInput]}
            />
            <RequiredFieldLabel>Business / Legal Name</RequiredFieldLabel>
            <TextInput
              value={signupBusinessLegalName}
              onChangeText={setSignupBusinessLegalName}
              editable={!signupDetailsReadOnly}
              placeholder="Enter business or legal name"
              placeholderTextColor="#9a9a9a"
              style={[styles.input, signupDetailsReadOnly && styles.readOnlyInput]}
            />
            <RequiredFieldLabel>GSTIN</RequiredFieldLabel>
            <TextInput
              value={signupGstin}
              onChangeText={setSignupGstin}
              editable={!signupDetailsReadOnly}
              autoCapitalize="characters"
              placeholder="Enter GSTIN"
              placeholderTextColor="#9a9a9a"
              style={[styles.input, signupDetailsReadOnly && styles.readOnlyInput]}
            />
            <RequiredFieldLabel>Email ID</RequiredFieldLabel>
            <TextInput
              value={signupEmailId}
              onChangeText={setSignupEmailId}
              editable={!signupDetailsReadOnly}
              keyboardType="email-address"
              autoCapitalize="none"
              placeholder="Enter email address"
              placeholderTextColor="#9a9a9a"
              style={[styles.input, signupDetailsReadOnly && styles.readOnlyInput]}
            />
            <RequiredFieldLabel>Date of Birth</RequiredFieldLabel>
            <DatePickerButton
              value={signupDateOfBirth}
              placeholder="DD-MM-YYYY"
              disabled={signupDetailsReadOnly}
              onPress={() => setDatePickerTarget('signupDateOfBirth')}
            />
            <Text style={styles.fieldLabel}>Date of Anniversary</Text>
            <DatePickerButton
              value={signupDateOfAnniversary}
              placeholder="DD-MM-YYYY"
              disabled={signupDetailsReadOnly}
              onPress={() => setDatePickerTarget('signupDateOfAnniversary')}
            />
          </>
        )}
        {otpRequestedForCurrentFlow && !signupDetailsReview && (
          <>
            {isSignupOtpFlow && (
              <FeedbackPressable style={styles.backButton} onPress={() => setSignupDetailsReview(true)}>
                <ChevronLeft size={16} color="#111111" />
                <Text style={styles.backButtonText}>Back to details</Text>
              </FeedbackPressable>
            )}
            <Text style={styles.fieldLabel}>OTP</Text>
            <TextInput
              value={otpCode}
              onChangeText={(value) => setOtpCode(value.toUpperCase())}
              autoCapitalize="characters"
              autoCorrect={false}
              placeholder="Enter WhatsApp OTP"
              placeholderTextColor="#9a9a9a"
              style={styles.input}
            />
          </>
        )}
        {signupDetailsReadOnly ? (
          <View style={styles.authSplitActions}>
            <FeedbackPressable style={[styles.secondaryAction, styles.authSecondaryAction]} onPress={editSignupDetails}>
              <Text style={styles.secondaryActionText}>Edit details</Text>
            </FeedbackPressable>
            <FeedbackPressable
              style={[styles.primaryAction, styles.authInlinePrimaryAction]}
              pressedStyle={styles.primaryActionPressed}
              rippleColor={colors.primaryPressed}
              onPress={() => setSignupDetailsReview(false)}
            >
              <Text style={styles.primaryActionText}>Continue to OTP</Text>
            </FeedbackPressable>
          </View>
        ) : (
          <FeedbackPressable
            style={[styles.primaryAction, styles.authPrimaryAction]}
            pressedStyle={styles.primaryActionPressed}
            rippleColor={colors.primaryPressed}
            onPress={otpRequestedForCurrentFlow ? verifyOtp : requestOtp}
          >
            <Text style={styles.primaryActionText}>
              {otpRequestedForCurrentFlow
                ? 'Verify OTP'
                : customerAuthIntent === 'signup'
                  ? 'Send OTP and create request'
                  : 'Send OTP'}
            </Text>
          </FeedbackPressable>
        )}
        {otpRequestedForCurrentFlow && !signupDetailsReview && (
          <FeedbackPressable style={styles.textAction} onPress={requestOtp}>
            <Text style={styles.textActionText}>
              {resend.canResend ? 'Resend OTP' : `Resend available in ${resend.secondsRemaining}s`}
            </Text>
          </FeedbackPressable>
        )}
        <FeedbackPressable
          style={styles.authTextAction}
          onPress={() => {
            setCustomerAuthIntent(customerAuthIntent === 'signup' ? 'login' : 'signup');
            setMode('Customer');
            setOtpIdentityType(null);
            setSignupDetailsReview(false);
            setOtpSentAtMs(null);
            setLastOtpRequestKey(null);
            setOtpCode('');
            setSystemState({ kind: 'idle' });
          }}
        >
          <Text style={styles.textActionText}>
            {customerAuthIntent === 'signup' ? 'Already have access? Sign in' : 'New customer? Create account'}
          </Text>
        </FeedbackPressable>
      </View>
    </AuthShell>
  );
}
