import assert from 'node:assert/strict';
import test from 'node:test';

import {
  appSectionForStep,
  isAuthSurface,
  shouldShowFloatingCartBar,
  showCartControls,
  signupAuthView,
} from '../src/flow/orderViewState.mjs';

test('history and detail steps belong to the history section', () => {
  assert.equal(appSectionForStep('history'), 'history');
  assert.equal(appSectionForStep('detail'), 'history');
});

test('profile step belongs to the profile section, everything else is order', () => {
  assert.equal(appSectionForStep('profile'), 'profile');
  assert.equal(appSectionForStep('groups'), 'order');
  assert.equal(appSectionForStep('summary'), 'order');
  assert.equal(appSectionForStep('auth'), 'order');
});

test('auth and pending steps are auth surfaces, others are not', () => {
  assert.equal(isAuthSurface('auth'), true);
  assert.equal(isAuthSurface('pending'), true);
  assert.equal(isAuthSurface('groups'), false);
  assert.equal(isAuthSurface('profile'), false);
});

test('cart controls show in the order section except sales-employee customer selection', () => {
  assert.equal(showCartControls({ mode: 'Customer', step: 'groups' }), true);
  assert.equal(showCartControls({ mode: 'Sales Employee', step: 'groups' }), true);
  // Sales employee picking a customer has no cart context yet
  assert.equal(showCartControls({ mode: 'Sales Employee', step: 'customer' }), false);
  // Non-order sections never show cart controls
  assert.equal(showCartControls({ mode: 'Customer', step: 'history' }), false);
  assert.equal(showCartControls({ mode: 'Customer', step: 'profile' }), false);
});

test('login flow before OTP: no OTP requested, no signup details', () => {
  const view = signupAuthView({
    customerAuthIntent: 'login',
    otpSentAtMs: null,
    lastOtpRequestKey: null,
    currentOtpRequestKey: 'Customer:99:login',
    signupDetailsReview: false,
  });
  assert.equal(view.otpRequestedForCurrentFlow, false);
  assert.equal(view.isSignupOtpFlow, false);
  assert.equal(view.showSignupDetails, false);
  assert.equal(view.signupDetailsReadOnly, false);
});

test('OTP is requested only when sent key matches the current request key', () => {
  const base = {
    customerAuthIntent: 'login',
    otpSentAtMs: 123,
    signupDetailsReview: false,
    currentOtpRequestKey: 'Customer:99:login',
  };
  assert.equal(signupAuthView({ ...base, lastOtpRequestKey: 'Customer:99:login' }).otpRequestedForCurrentFlow, true);
  assert.equal(signupAuthView({ ...base, lastOtpRequestKey: 'Customer:88:login' }).otpRequestedForCurrentFlow, false);
});

test('signup before OTP shows details; after OTP hides them unless reviewing', () => {
  const beforeOtp = signupAuthView({
    customerAuthIntent: 'signup',
    otpSentAtMs: null,
    lastOtpRequestKey: null,
    currentOtpRequestKey: 'Customer:99:signup',
    signupDetailsReview: false,
  });
  assert.equal(beforeOtp.showSignupDetails, true);
  assert.equal(beforeOtp.isSignupOtpFlow, false);

  const afterOtp = signupAuthView({
    customerAuthIntent: 'signup',
    otpSentAtMs: 123,
    lastOtpRequestKey: 'Customer:99:signup',
    currentOtpRequestKey: 'Customer:99:signup',
    signupDetailsReview: false,
  });
  assert.equal(afterOtp.isSignupOtpFlow, true);
  assert.equal(afterOtp.showSignupDetails, false);
  assert.equal(afterOtp.signupDetailsReadOnly, false);
});

test('signup OTP flow while reviewing shows details read-only', () => {
  const reviewing = signupAuthView({
    customerAuthIntent: 'signup',
    otpSentAtMs: 123,
    lastOtpRequestKey: 'Customer:99:signup',
    currentOtpRequestKey: 'Customer:99:signup',
    signupDetailsReview: true,
  });
  assert.equal(reviewing.isSignupOtpFlow, true);
  assert.equal(reviewing.showSignupDetails, true);
  assert.equal(reviewing.signupDetailsReadOnly, true);
});

test('floating cart bar shows in order section with items, off the summary step', () => {
  assert.equal(shouldShowFloatingCartBar({ step: 'groups', rowCount: 2 }), true);
  // empty cart hides the bar
  assert.equal(shouldShowFloatingCartBar({ step: 'groups', rowCount: 0 }), false);
  // summary already shows the cart, so the bar is hidden there
  assert.equal(shouldShowFloatingCartBar({ step: 'summary', rowCount: 2 }), false);
  // auth surfaces and non-order sections never show it
  assert.equal(shouldShowFloatingCartBar({ step: 'auth', rowCount: 2 }), false);
  assert.equal(shouldShowFloatingCartBar({ step: 'history', rowCount: 2 }), false);
});
