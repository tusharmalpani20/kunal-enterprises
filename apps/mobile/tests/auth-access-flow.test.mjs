import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildCustomerSignupPayload,
  customerOtpRouteAfterAccessCheck,
  nextAuthStepFromCustomerOtp,
  nextStepFromCustomerAccessStatus,
  nextAuthStepFromSalesEmployeeOtp,
  otpRequestKey,
  otpCooldownSecondsFromResponse,
  otpResendState,
  pendingAccessRequestFromCustomerOtp,
  salesEmployeeSessionFromOtpResponse,
  shouldLogoutForApiError,
  shouldTrySalesEmployeeOtpAfterCustomerOtpError,
  shouldUseOtpResend,
  sessionFromOtpResponse,
  validateCustomerSignupInput,
} from '../src/domain/authAccessFlow.mjs';

test('customer signup payload captures required fields but never sends client code', () => {
  const payload = buildCustomerSignupPayload({
    customerName: 'Asha Textiles',
    businessLegalName: 'Asha Textiles Pvt Ltd',
    gstin: '27ABCDE1234F1Z5',
    mobileNumber: ' 9000000001 ',
    emailId: 'asha@example.com',
    dateOfBirth: '1990-01-02',
    dateOfAnniversary: '2015-03-04',
    clientCode: 'SHOULD-NOT-SEND',
  });

  assert.equal(payload.customer_name, 'Asha Textiles');
  assert.equal(payload.business_legal_name, 'Asha Textiles Pvt Ltd');
  assert.equal(payload.mobile_number, '9000000001');
  assert.equal(Object.hasOwn(payload, 'client_code'), false);
});

test('customer signup validates required fields before requesting OTP', () => {
  const invalid = validateCustomerSignupInput({
    customerName: '  ',
    businessLegalName: 'Asha Textiles Pvt Ltd',
    gstin: '',
    mobileNumber: '9000000001',
    emailId: 'asha@example.com',
    dateOfBirth: '1990-01-02',
    dateOfAnniversary: '',
  });
  const valid = validateCustomerSignupInput({
    customerName: 'Asha Textiles',
    businessLegalName: 'Asha Textiles Pvt Ltd',
    gstin: '27ABCDE1234F1Z5',
    mobileNumber: '9000000001',
    emailId: 'asha@example.com',
    dateOfBirth: '1990-01-02',
    dateOfAnniversary: '',
  });

  assert.equal(invalid.ok, false);
  assert.deepEqual(invalid.missingFields, ['Customer Name', 'GSTIN']);
  assert.match(invalid.message, /Customer Name/);
  assert.equal(valid.ok, true);
  assert.deepEqual(valid.missingFields, []);
});

test('customer signup requires date of birth but not date of anniversary', () => {
  const invalid = validateCustomerSignupInput({
    customerName: 'Asha Textiles',
    businessLegalName: 'Asha Textiles Pvt Ltd',
    gstin: '27ABCDE1234F1Z5',
    mobileNumber: '9000000001',
    emailId: 'asha@example.com',
    dateOfBirth: '',
    dateOfAnniversary: '',
  });

  assert.equal(invalid.ok, false);
  assert.deepEqual(invalid.missingFields, ['Date of Birth']);
});

test('customer OTP without app access routes to pending approval', () => {
  const response = {
    customer: '9000000001',
    status: 'Pending Admin Review',
    customer_app_access: false,
  };

  assert.equal(nextAuthStepFromCustomerOtp(response), 'pending_access');
  assert.equal(sessionFromOtpResponse(response), null);
  assert.deepEqual(pendingAccessRequestFromCustomerOtp({ otpResponse: response, mobileNumber: ' 9000000001 ' }), {
    identityType: 'Customer',
    customer: '9000000001',
    mobileNumber: '9000000001',
    status: 'Pending Admin Review',
  });
});

test('customer OTP with app access creates a customer session', () => {
  const response = {
    customer: '9000000001',
    status: 'Active',
    customer_app_access: true,
    access_token: 'token-123',
    identity_type: 'Customer',
    identity: '9000000001',
    customer_name: 'Asha Textiles',
  };

  assert.equal(nextAuthStepFromCustomerOtp(response), 'authenticated');
  assert.deepEqual(sessionFromOtpResponse(response), {
    accessToken: 'token-123',
    identityType: 'Customer',
    identity: '9000000001',
    displayName: 'Asha Textiles',
  });
});

test('customer access status routes active access to order home and removed access to pending state', () => {
  assert.equal(nextStepFromCustomerAccessStatus({ customer_app_access: true }), 'groups');
  assert.equal(nextStepFromCustomerAccessStatus({ customer_app_access: false }), 'pending');
});

test('active customer OTP routes to order home from the verified OTP response', async () => {
  let checkedAccessStatus = false;
  const route = await customerOtpRouteAfterAccessCheck({
    otpResponse: {
      customer: 'CUST-001',
      customer_app_access: true,
      access_token: 'token-123',
      identity_type: 'Customer',
      identity: 'CUST-001',
      customer_name: 'Asha Textiles',
    },
    customerAccessStatus: async () => {
      checkedAccessStatus = true;
      return { customer_app_access: true };
    },
  });

  assert.equal(route.step, 'groups');
  assert.equal(checkedAccessStatus, false);
  assert.deepEqual(route.session, {
    accessToken: 'token-123',
    identityType: 'Customer',
    identity: 'CUST-001',
    displayName: 'Asha Textiles',
  });
});

test('sales employee OTP with active status creates a sales employee session', () => {
  const response = {
    sales_employee: 'SE-001',
    status: 'Active',
    access_token: 'token-se',
    identity_type: 'Sales Employee',
    identity: 'SE-001',
    sales_employee_name: 'Ravi Sales',
  };

  assert.equal(nextAuthStepFromSalesEmployeeOtp(response), 'authenticated');
  assert.deepEqual(salesEmployeeSessionFromOtpResponse(response), {
    accessToken: 'token-se',
    identityType: 'Sales Employee',
    identity: 'SE-001',
    displayName: 'Ravi Sales',
  });
});

test('disabled sales employee OTP routes to blocked access', () => {
  const response = {
    sales_employee: 'SE-002',
    status: 'Disabled',
  };

  assert.equal(nextAuthStepFromSalesEmployeeOtp(response), 'blocked');
  assert.equal(salesEmployeeSessionFromOtpResponse(response), null);
});

test('OTP resend state enforces countdown before resend', () => {
  assert.deepEqual(otpResendState({ lastSentAtMs: 1000, nowMs: 30000, waitSeconds: 45 }), {
    canResend: false,
    secondsRemaining: 16,
  });
  assert.deepEqual(otpResendState({ lastSentAtMs: 1000, nowMs: 47000, waitSeconds: 45 }), {
    canResend: true,
    secondsRemaining: 0,
  });
});

test('OTP resend countdown uses backend-defined cooldown when returned', () => {
  assert.equal(otpCooldownSecondsFromResponse({ cooldown_seconds: 60 }, 45), 60);
  assert.equal(otpCooldownSecondsFromResponse({ cooldown_seconds: 0 }, 45), 45);
  assert.equal(otpCooldownSecondsFromResponse({}, 45), 45);
});

test('OTP resend is used only after a previous send and completed cooldown', () => {
  assert.equal(shouldUseOtpResend({ lastSentAtMs: null, canResend: true }), false);
  assert.equal(shouldUseOtpResend({ lastSentAtMs: 1000, canResend: false }), false);
  assert.equal(shouldUseOtpResend({ lastSentAtMs: 1000, canResend: true }), true);
});

test('OTP resend is scoped to the same auth identity and mobile number', () => {
  const firstRequestKey = otpRequestKey({
    mode: 'Customer',
    customerAuthIntent: 'login',
    mobileNumber: ' 9000000001 ',
  });

  assert.equal(firstRequestKey, 'Customer:login:9000000001');
  assert.equal(
    shouldUseOtpResend({
      lastSentAtMs: 1000,
      canResend: true,
      currentRequestKey: firstRequestKey,
      lastRequestKey: firstRequestKey,
    }),
    true,
  );
  assert.equal(
    shouldUseOtpResend({
      lastSentAtMs: 1000,
      canResend: true,
      currentRequestKey: otpRequestKey({
        mode: 'Customer',
        customerAuthIntent: 'signup',
        mobileNumber: '9000000001',
      }),
      lastRequestKey: firstRequestKey,
    }),
    false,
  );
  assert.equal(
    shouldUseOtpResend({
      lastSentAtMs: 1000,
      canResend: true,
      currentRequestKey: otpRequestKey({
        mode: 'Sales Employee',
        mobileNumber: '9000000101',
      }),
      lastRequestKey: firstRequestKey,
    }),
    false,
  );
});

test('invalid-token backend errors trigger mobile logout', () => {
  assert.equal(shouldLogoutForApiError('Invalid or inactive token'), true);
  assert.equal(shouldLogoutForApiError('App Update Required'), true);
  assert.equal(shouldLogoutForApiError('Backend validation error'), false);
});

test('sign in can infer sales employee login only after customer mobile lookup misses', () => {
  assert.equal(shouldTrySalesEmployeeOtpAfterCustomerOtpError('Customer was not found for this mobile number'), true);
  assert.equal(shouldTrySalesEmployeeOtpAfterCustomerOtpError('Customer cannot receive OTP in current status'), false);
});
