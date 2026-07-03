export function buildCustomerSignupPayload(input) {
  return {
    customer_name: String(input.customerName || '').trim(),
    business_legal_name: String(input.businessLegalName || '').trim(),
    gstin: String(input.gstin || '').trim(),
    mobile_number: String(input.mobileNumber || '').trim(),
    email_id: String(input.emailId || '').trim(),
    date_of_birth: String(input.dateOfBirth || '').trim(),
    date_of_anniversary: String(input.dateOfAnniversary || '').trim(),
  };
}

const CUSTOMER_SIGNUP_REQUIRED_FIELDS = [
  ['customerName', 'Customer Name'],
  ['businessLegalName', 'Business / Legal Name'],
  ['gstin', 'GSTIN'],
  ['mobileNumber', 'Mobile Number'],
  ['emailId', 'Email ID'],
  ['dateOfBirth', 'Date of Birth'],
];

export function validateCustomerSignupInput(input) {
  const missingFields = CUSTOMER_SIGNUP_REQUIRED_FIELDS.filter(([field]) => !String(input?.[field] || '').trim()).map(
    ([, label]) => label,
  );
  return {
    ok: missingFields.length === 0,
    missingFields,
    message: missingFields.length ? `Enter ${missingFields.join(', ')} before starting signup.` : '',
  };
}

export function nextAuthStepFromCustomerOtp(response) {
  if (response.customer_app_access && response.access_token) {
    return 'authenticated';
  }
  if (response.status === 'Rejected' || response.status === 'Disabled') {
    return 'blocked';
  }
  return 'pending_access';
}

export function nextStepFromCustomerAccessStatus(response) {
  return response?.customer_app_access ? 'groups' : 'pending';
}

export function pendingAccessRequestFromCustomerOtp({ otpResponse, mobileNumber }) {
  if (!otpResponse || otpResponse.customer_app_access || !otpResponse.customer) {
    return null;
  }
  return {
    identityType: 'Customer',
    customer: otpResponse.customer,
    mobileNumber: String(mobileNumber || '').trim(),
    status: otpResponse.status || 'Pending Admin Review',
  };
}

export async function customerOtpRouteAfterAccessCheck({ otpResponse, customerAccessStatus }) {
  const session = sessionFromOtpResponse(otpResponse);
  const authStep = nextAuthStepFromCustomerOtp(otpResponse);
  if (!session) {
    return {
      session: null,
      step: authStep === 'pending_access' ? 'pending' : 'auth',
    };
  }
  if (otpResponse.customer_app_access) {
    return {
      session,
      step: 'groups',
    };
  }
  const accessStatus = await customerAccessStatus(session.identity);
  return {
    session,
    step: nextStepFromCustomerAccessStatus(accessStatus),
  };
}

export function nextAuthStepFromSalesEmployeeOtp(response) {
  if (response.status === 'Rejected' || response.status === 'Disabled' || response.status === 'Inactive') {
    return 'blocked';
  }
  if (response.sales_employee && response.access_token) {
    return 'authenticated';
  }
  return 'pending_access';
}

export function sessionFromOtpResponse(response) {
  if (!response.customer_app_access || !response.access_token) {
    return null;
  }
  return {
    accessToken: response.access_token,
    identityType: response.identity_type,
    identity: response.identity,
    displayName: response.customer_name || '',
  };
}

export function salesEmployeeSessionFromOtpResponse(response) {
  if (!response.sales_employee || !response.access_token) {
    return null;
  }
  return {
    accessToken: response.access_token,
    identityType: response.identity_type,
    identity: response.identity,
    displayName: response.sales_employee_name || '',
  };
}

export function otpResendState({ lastSentAtMs, nowMs, waitSeconds = 45 }) {
  if (!lastSentAtMs) {
    return { canResend: true, secondsRemaining: 0 };
  }
  const elapsedSeconds = Math.max(0, Math.floor((nowMs - lastSentAtMs) / 1000));
  const secondsRemaining = Math.max(0, waitSeconds - elapsedSeconds);
  return {
    canResend: secondsRemaining === 0,
    secondsRemaining,
  };
}

export function otpCooldownSecondsFromResponse(response, fallbackSeconds = 45) {
  const cooldownSeconds = Number(response?.cooldown_seconds);
  if (!Number.isFinite(cooldownSeconds) || cooldownSeconds <= 0) {
    return fallbackSeconds;
  }
  return cooldownSeconds;
}

export function otpRequestKey({ mode, mobileNumber, customerAuthIntent = '' }) {
  return [mode, customerAuthIntent, String(mobileNumber || '').trim()].join(':');
}

export function shouldUseOtpResend({ lastSentAtMs, canResend, currentRequestKey, lastRequestKey }) {
  if (!lastSentAtMs || !canResend) {
    return false;
  }
  if (currentRequestKey || lastRequestKey) {
    return currentRequestKey === lastRequestKey;
  }
  return true;
}

export function shouldLogoutForApiError(message) {
  return ['Invalid or inactive token', 'App Update Required', 'Error verifying token'].includes(message);
}

export function shouldTrySalesEmployeeOtpAfterCustomerOtpError(message) {
  return /Customer was not found for this mobile number/i.test(String(message || ''));
}
