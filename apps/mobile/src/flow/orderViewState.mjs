export function isAuthSurface(step) {
  return step === 'auth' || step === 'pending';
}

export function signupAuthView({
  customerAuthIntent,
  otpSentAtMs,
  lastOtpRequestKey,
  currentOtpRequestKey,
  signupDetailsReview,
}) {
  const otpRequestedForCurrentFlow = Boolean(otpSentAtMs && lastOtpRequestKey === currentOtpRequestKey);
  const isSignupOtpFlow = customerAuthIntent === 'signup' && otpRequestedForCurrentFlow;
  const showSignupDetails = customerAuthIntent === 'signup' && (!isSignupOtpFlow || signupDetailsReview);
  const signupDetailsReadOnly = isSignupOtpFlow && signupDetailsReview;
  return { otpRequestedForCurrentFlow, isSignupOtpFlow, showSignupDetails, signupDetailsReadOnly };
}

export function showCartControls({ mode, step }) {
  const isOrderSection = appSectionForStep(step) === 'order';
  return isOrderSection && !(mode === 'Sales Employee' && step === 'customer');
}

export function shouldShowFloatingCartBar({ step, rowCount }) {
  const isOrderSection = appSectionForStep(step) === 'order';
  return !isAuthSurface(step) && isOrderSection && step !== 'summary' && rowCount > 0;
}

export function appSectionForStep(step) {
  if (step === 'history' || step === 'detail') {
    return 'history';
  }
  if (step === 'profile') {
    return 'profile';
  }
  return 'order';
}
