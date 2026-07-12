import { mobileDisplayStatus } from './mobileFlow.mjs';
import { classifyApiFailure } from './sharedStateFlow.mjs';

export const CUSTOMER_EDITABLE_PROFILE_FIELDS = ['email_id', 'date_of_birth', 'date_of_anniversary'];
export const MOBILE_BLOCKED_ORDER_FIELDS = new Set([
  'amount',
  'total_amount',
  'tax',
  'tax_amount',
  'rate',
  'price',
  'discount',
  'discount_value',
  'manual_review_reason',
  'order_value',
]);

export function customerProfileForMobile(profile) {
  return {
    identity_type: 'Customer',
    customer: profile.customer,
    customer_name: profile.customer_name,
    business_legal_name: profile.business_legal_name,
    mobile_number: profile.mobile_number,
    email_id: profile.email_id,
    date_of_birth: profile.date_of_birth,
    date_of_anniversary: profile.date_of_anniversary,
    customer_app_access: Boolean(profile.customer_app_access),
    editable_fields: CUSTOMER_EDITABLE_PROFILE_FIELDS,
  };
}

export function editableCustomerProfilePatch(patch) {
  return Object.fromEntries(
    Object.entries(patch).filter(([field]) => CUSTOMER_EDITABLE_PROFILE_FIELDS.includes(field)),
  );
}

export function salesEmployeeProfileForMobile(profile) {
  return {
    identity_type: 'Sales Employee',
    sales_employee: profile.sales_employee,
    sales_employee_name: profile.sales_employee_name,
    mobile_number: profile.mobile_number,
    employee_code: profile.employee_code,
    status: profile.status,
    editable_fields: [],
  };
}

export async function loadProfileForMobile({ identityType, identity, getProfile }) {
  try {
    return {
      ok: true,
      profile: await getProfile(identityType, identity),
      state: { kind: 'idle' },
    };
  } catch (error) {
    return {
      ok: false,
      profile: null,
      state: classifyApiFailure(error),
    };
  }
}

export async function saveCustomerProfileForMobile({ customer, patch, updateCustomerProfile }) {
  try {
    return {
      ok: true,
      profile: await updateCustomerProfile(customer, editableCustomerProfilePatch(patch)),
      state: { kind: 'idle' },
    };
  } catch (error) {
    return {
      ok: false,
      profile: null,
      state: classifyApiFailure(error),
    };
  }
}

export function orderSummaryForMobile(order) {
  const safeOrder = stripBlockedOrderFields(order);
  return {
    ...safeOrder,
    display_status: mobileDisplayStatus(order.status),
  };
}

export function orderPlacedByLabel(order, viewerIdentityType) {
  if (order.placed_by_identity_type === viewerIdentityType) {
    return 'You';
  }
  if (order.placed_by_identity_type === 'Sales Employee') {
    return order.placed_by_name || order.sales_employee_name || order.placed_by || 'Sales Employee';
  }
  if (order.placed_by_identity_type === 'Customer') {
    return order.placed_by_name || order.customer_name || order.placed_by || 'Customer';
  }
  if (order.placed_by === 'You') {
    return 'You';
  }
  return order.placed_by_name || order.customer_name || order.placed_by || 'Customer';
}

export function customerOrderDetailForMobile(order) {
  return orderDetailForMobile(order, { viewerIdentityType: 'Customer' });
}

export function orderDetailForMobile(order, { viewerIdentityType = 'Customer' } = {}) {
  const { client_code: _clientCode, ...orderWithoutClientCode } = order;
  const { sales_employee_note: _salesNote, ...customerSafeOrder } = orderWithoutClientCode;
  const safeOrder = viewerIdentityType === 'Sales Employee' ? orderWithoutClientCode : customerSafeOrder;

  return {
    ...orderSummaryForMobile(stripBlockedOrderFields(safeOrder)),
    placed_by_label: orderPlacedByLabel(order, viewerIdentityType),
    godown_allocations: (order.godown_allocations || []).map(
      ({ stock_shown_at_order_time: _stockShown, stock_snapshot_at: _snapshotAt, ...allocation }) =>
        stripBlockedOrderFields(allocation),
    ),
  };
}

export function groupGodownAllocationsForMobile(allocations = []) {
  const groups = new Map();

  for (const allocation of allocations) {
    const godown = allocation.godown || 'Unassigned Godown';
    if (!groups.has(godown)) {
      groups.set(godown, []);
    }
    groups.get(godown).push(allocation);
  }

  return [...groups.entries()]
    .sort(([first], [second]) => first.localeCompare(second))
    .map(([godown, rows]) => ({ godown, rows }));
}

export function stripBlockedOrderFields(value) {
  if (Array.isArray(value)) {
    return value.map(stripBlockedOrderFields);
  }
  if (!value || typeof value !== 'object') {
    return value;
  }
  return Object.fromEntries(
    Object.entries(value)
      .filter(([field]) => !MOBILE_BLOCKED_ORDER_FIELDS.has(field))
      .map(([field, fieldValue]) => [field, stripBlockedOrderFields(fieldValue)]),
  );
}
