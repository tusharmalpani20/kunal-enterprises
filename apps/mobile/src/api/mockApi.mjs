import {
  filterAllowedCustomers,
  sanitizeCustomerForSalesEmployee,
  salesEmployeeHistory,
} from '../domain/salesEmployeeFlow.mjs';
import {
  customerOrderDetailForMobile,
  customerProfileForMobile,
  orderDetailForMobile,
  orderSummaryForMobile,
  salesEmployeeProfileForMobile,
} from '../domain/profileHistoryFlow.mjs';
import { sortGodownStockForMobile } from '../domain/mobileFlow.mjs';

const productGroups = [
  { name: 'Cotton Fabric', group_name: 'Cotton Fabric', full_path: 'Cotton Fabric' },
  { name: 'Lining', group_name: 'Lining', full_path: 'Lining' },
];

const items = [
  {
    name: 'ITEM-COTTON-001',
    item_name: 'Cotton 40s',
    root_stock_group: 'Cotton Fabric',
    uom: 'PCS',
    total_closing_balance: 12,
  },
  {
    name: 'ITEM-LINING-001',
    item_name: 'Plain Lining',
    root_stock_group: 'Lining',
    uom: 'PCS',
    total_closing_balance: 0,
  },
];

const stock = [
  {
    item: 'ITEM-COTTON-001',
    godown: 'Main Godown',
    quantity: 12,
    uom: 'PCS',
    synced_at: '2026-05-19 12:05:00',
  },
  {
    item: 'ITEM-COTTON-001',
    godown: 'Zero Godown',
    quantity: 0,
    uom: 'PCS',
    synced_at: '2026-05-19 12:05:00',
  },
];

const customers = [
  {
    customer: 'CUST-001',
    customer_name: 'Asha Textiles',
    business_legal_name: 'Asha Textiles Pvt Ltd',
    client_code: 'ASHA-LEDGER-001',
  },
  {
    customer: 'CUST-002',
    customer_name: 'Bharat Stores',
    business_legal_name: 'Bharat Stores LLP',
    client_code: 'BHARAT-LEDGER-002',
  },
];

const orders = [
  {
    name: 'KE-26-05-0001',
    portal_reference_number: 'KE-26-05-0001',
    customer: 'CUST-001',
    customer_name: 'Asha Textiles',
    sales_employee: 'SE-001',
    status: 'Manual Review',
    total_quantity: 4,
  },
  {
    name: 'KE-26-05-0002',
    portal_reference_number: 'KE-26-05-0002',
    customer: 'CUST-001',
    customer_name: 'Asha Textiles',
    sales_employee: 'SE-002',
    status: 'Completed',
    total_quantity: 2,
  },
];

const orderDetails = {
  'KE-26-05-0001': {
    name: 'KE-26-05-0001',
    portal_reference_number: 'KE-26-05-0001',
    status: 'Manual Review',
    placed_by: 'Ravi Sales',
    sales_employee_note: 'Call before dispatch',
    client_code: 'ASHA-LEDGER-001',
    godown_allocations: [
      {
        item: 'ITEM-COTTON-001',
        godown: 'Main Godown',
        requested_quantity: 4,
        stock_shown_at_order_time: 12,
      },
    ],
  },
};

const customerProfile = {
  customer: 'CUST-001',
  customer_name: 'Asha Textiles',
  business_legal_name: 'Asha Textiles Pvt Ltd',
  mobile_number: '9000000001',
  email_id: 'asha@example.com',
  date_of_birth: '1990-01-02',
  date_of_anniversary: '2015-03-04',
  customer_app_access: true,
  client_code: 'ASHA-LEDGER-001',
};

const salesEmployeeProfile = {
  sales_employee: 'SE-001',
  sales_employee_name: 'Ravi Sales',
  mobile_number: '9000000101',
  employee_code: 'EMP-01',
  status: 'Active',
};

const otpResponses = {
  '9000000001': {
    customer: '9000000001',
    status: 'Pending Admin Review',
    customer_app_access: false,
  },
  '9000000003': {
    customer: '9000000003',
    status: 'Active',
    customer_app_access: true,
    access_token: 'mock-customer-token',
    token: 'MAT-MOCK-001',
    identity_type: 'Customer',
    identity: '9000000003',
    customer_name: 'Asha Textiles',
  },
};

const salesEmployeeOtpResponses = {
  '9000000101': {
    sales_employee: 'SE-001',
    status: 'Active',
    access_token: 'mock-sales-token',
    token: 'MAT-MOCK-SE-001',
    identity_type: 'Sales Employee',
    identity: 'SE-001',
    sales_employee_name: 'Ravi Sales',
  },
  '9000000102': {
    sales_employee: 'SE-002',
    status: 'Disabled',
  },
};

const mockSessions = {
  'mock-customer-token': {
    identity_type: 'Customer',
    identity: 'CUST-001',
    customer: 'CUST-001',
  },
  'mock-sales-token': {
    identity_type: 'Sales Employee',
    identity: 'SE-001',
    sales_employee: 'SE-001',
  },
};

const customerAccessStatuses = {
  'CUST-001': {
    customer: 'CUST-001',
    customer_app_access: true,
    checklist: {
      mobile_verified: true,
      admin_approved: true,
      valid_client_code: true,
      active_status: true,
    },
  },
  'CUST-PENDING': {
    customer: 'CUST-PENDING',
    customer_app_access: false,
    checklist: {
      mobile_verified: true,
      admin_approved: false,
      valid_client_code: false,
      active_status: false,
    },
  },
};

export const mockApi = {
  async startCustomerSignup(payload) {
    return {
      customer: payload.mobile_number,
      status: 'Pending OTP',
      next_step: 'verify_otp',
    };
  },

  async startCustomerOtp(mobileNumber) {
    if (!otpResponses[mobileNumber]) {
      throw new Error('Customer was not found for this mobile number');
    }
    return {
      mobile_number: mobileNumber,
      identity_type: 'Customer',
      status: 'Pending OTP',
      next_step: 'verify_otp',
      cooldown_seconds: 45,
      expires_in_seconds: 300,
    };
  },

  async verifyCustomerOtp(mobileNumber, _otpCode) {
    return otpResponses[mobileNumber] || otpResponses['9000000001'];
  },

  async startSalesEmployeeOtp(mobileNumber) {
    if (!salesEmployeeOtpResponses[mobileNumber]) {
      throw new Error('Sales Employee was not found for this mobile number');
    }
    return {
      sales_employee: salesEmployeeOtpResponses[mobileNumber]?.sales_employee || null,
      status: 'Pending OTP',
      next_step: 'verify_otp',
      cooldown_seconds: 45,
      expires_in_seconds: 300,
    };
  },

  async resendOtp(mobileNumber, identityType) {
    return {
      mobile_number: mobileNumber,
      identity_type: identityType,
      status: 'Pending OTP',
      next_step: 'verify_otp',
      cooldown_seconds: 45,
      expires_in_seconds: 300,
    };
  },

  async verifySalesEmployeeOtp(mobileNumber, _otpCode) {
    return salesEmployeeOtpResponses[mobileNumber] || salesEmployeeOtpResponses['9000000101'];
  },

  async currentSession(headers = {}) {
    const token = authTokenFromHeaders(headers);
    const session = mockSessions[token];
    if (!session) {
      throw new Error('Invalid or inactive token');
    }
    return session;
  },

  async revokeToken(headers = {}) {
    const token = authTokenFromHeaders(headers);
    return {
      revoked: Boolean(mockSessions[token]),
    };
  },

  async customerAccessStatus(customer) {
    return customerAccessStatuses[customer] || customerAccessStatuses['CUST-PENDING'];
  },

  async allowedProductGroups(_customer, _salesEmployee) {
    return productGroups;
  },

  async allowedItems(_customer, productGroup) {
    return items.filter((item) => item.root_stock_group === productGroup);
  },

  async itemStock(_customer, item) {
    return sortGodownStockForMobile(stock.filter((row) => row.item === item));
  },

  async allowedCustomers(_salesEmployee, search = '') {
    return filterAllowedCustomers(customers, search).map(sanitizeCustomerForSalesEmployee);
  },

  async submitOrder(payload) {
    return {
      order: 'KE-26-05-0001',
      portal_reference_number: 'KE-26-05-0001',
      status: 'Placed',
      total_item_count: new Set(payload.allocations.map((row) => row.item)).size,
      total_quantity: payload.allocations.reduce((total, row) => total + row.quantity, 0),
    };
  },

  async orderHistory(customer, salesEmployee = undefined) {
    const scoped = salesEmployee ? salesEmployeeHistory(orders, salesEmployee) : orders.filter((order) => order.customer === customer);
    return scoped.map(orderSummaryForMobile);
  },

  async orderHistoryForSalesEmployee(salesEmployee) {
    return salesEmployeeHistory(orders, salesEmployee).map(orderSummaryForMobile);
  },

  async orderHistoryForCustomer(customer) {
    return orders.filter((order) => order.customer === customer).map(orderSummaryForMobile);
  },

  async orderDetail(order, options = {}) {
    return orderDetailForMobile(orderDetails[order], {
      viewerIdentityType: options.salesEmployee ? 'Sales Employee' : 'Customer',
    });
  },

  async orderDetailForCustomer(order) {
    return customerOrderDetailForMobile(orderDetails[order]);
  },

  async getProfile(identityType, _identity) {
    if (identityType === 'Customer') {
      return customerProfileForMobile(customerProfile);
    }
    return salesEmployeeProfileForMobile(salesEmployeeProfile);
  },

  async updateCustomerProfile(customer, payload) {
    return customerProfileForMobile({
      ...customerProfile,
      customer,
      ...payload,
    });
  },
};

function authTokenFromHeaders(headers) {
  return String(headers['Auth-Token'] || '').replace(/^Bearer\s+/i, '');
}
