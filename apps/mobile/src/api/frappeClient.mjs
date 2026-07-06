import { sortGodownStockForMobile } from '../domain/mobileFlow.mjs';
import { orderDetailForMobile, orderSummaryForMobile } from '../domain/profileHistoryFlow.mjs';
import { sanitizeCustomerForSalesEmployee } from '../domain/salesEmployeeFlow.mjs';

const METHODS = {
  startCustomerSignup: 'kunal_enterprises.api.otp.start_customer_signup',
  sendOtp: 'kunal_enterprises.api.otp.send_otp',
  resendOtp: 'kunal_enterprises.api.otp.resend_otp',
  verifyCustomerOtp: 'kunal_enterprises.api.otp.verify_customer_otp',
  verifySalesEmployeeOtp: 'kunal_enterprises.api.otp.verify_sales_employee_otp',
  currentSession: 'kunal_enterprises.api.token_verification.current_session',
  revokeToken: 'kunal_enterprises.api.token_verification.revoke_token',
  customerAccessStatus: 'kunal_enterprises.api.customer_access.status',
  allowedCustomers: 'kunal_enterprises.api.sales_employees.allowed_customers',
  allowedProductGroups: 'kunal_enterprises.api.product_groups.allowed',
  allowedItems: 'kunal_enterprises.api.product_groups.items',
  itemStock: 'kunal_enterprises.api.product_groups.item_stock',
  submitOrder: 'kunal_enterprises.api.orders.submit',
  orderHistory: 'kunal_enterprises.api.orders.history',
  orderDetail: 'kunal_enterprises.api.orders.detail',
  getProfile: 'kunal_enterprises.api.profile.get_profile',
  updateCustomerProfile: 'kunal_enterprises.api.profile.update_customer_profile',
};

export function createFrappeApiClient(call) {
  return {
    async startCustomerSignup(payload) {
      return unwrap(await call.post(METHODS.startCustomerSignup, { payload }));
    },

    async startCustomerOtp(mobileNumber) {
      return unwrap(
        await call.post(METHODS.sendOtp, {
          mobile_number: mobileNumber,
          identity_type: 'Customer',
        }),
      );
    },

    async startSalesEmployeeOtp(mobileNumber) {
      return unwrap(
        await call.post(METHODS.sendOtp, {
          mobile_number: mobileNumber,
          identity_type: 'Sales Employee',
        }),
      );
    },

    async resendOtp(mobileNumber, identityType) {
      return unwrap(
        await call.post(METHODS.resendOtp, {
          mobile_number: mobileNumber,
          identity_type: identityType,
        }),
      );
    },

    async verifyCustomerOtp(mobileNumber, otpCode) {
      return unwrap(
        await call.post(METHODS.verifyCustomerOtp, {
          mobile_number: mobileNumber,
          otp_code: otpCode,
        }),
      );
    },

    async verifySalesEmployeeOtp(mobileNumber, otpCode) {
      return unwrap(
        await call.post(METHODS.verifySalesEmployeeOtp, {
          mobile_number: mobileNumber,
          otp_code: otpCode,
        }),
      );
    },

    async currentSession() {
      return unwrap(await call.get(METHODS.currentSession));
    },

    async revokeToken() {
      return unwrap(await call.post(METHODS.revokeToken));
    },

    async customerAccessStatus(customer) {
      return unwrap(await call.get(METHODS.customerAccessStatus, { customer }));
    },

    async allowedCustomers(salesEmployee, search = '') {
      const data = unwrap(
        await call.get(METHODS.allowedCustomers, {
          sales_employee: salesEmployee,
          search,
        }),
      );
      return data.customers.map(sanitizeCustomerForSalesEmployee);
    },

    async allowedProductGroups(customer, salesEmployee = undefined) {
      const data = unwrap(
        await call.get(METHODS.allowedProductGroups, {
          customer,
          sales_employee: salesEmployee,
        }),
      );
      const groups = data.product_groups;
      const withLogos = groups.filter((g) => g.product_group_logo);
      console.log(`[api] allowedProductGroups — ${groups.length} groups, ${withLogos.length} with logos`);
      if (withLogos.length > 0) {
        console.log('[api] groups with logos:', withLogos.map((g) => `${g.name} -> ${g.product_group_logo}`).join(', '));
      } else {
        console.log('[api] no groups have logos in this response');
      }
      return groups;
    },

    async allowedItems(customer, productGroup, salesEmployee = undefined) {
      const data = unwrap(
        await call.get(METHODS.allowedItems, {
          customer,
          product_group: productGroup,
          sales_employee: salesEmployee,
        }),
      );
      return data.items;
    },

    async itemStock(customer, item, salesEmployee = undefined) {
      const data = unwrap(
        await call.get(METHODS.itemStock, {
          customer,
          item,
          sales_employee: salesEmployee,
        }),
      );
      return sortGodownStockForMobile(data.godowns);
    },

    async submitOrder(payload) {
      return unwrap(await call.post(METHODS.submitOrder, payload));
    },

    async orderHistory(customer, salesEmployee = undefined) {
      const data = unwrap(
        await call.get(METHODS.orderHistory, {
          customer,
          sales_employee: salesEmployee,
        }),
      );
      return data.orders.map(orderSummaryForMobile);
    },

    async orderDetail(order, options = {}) {
      return orderDetailForMobile(
        unwrap(
          await call.get(METHODS.orderDetail, {
            order,
            customer: options.customer,
            sales_employee: options.salesEmployee,
          }),
        ),
        { viewerIdentityType: options.salesEmployee ? 'Sales Employee' : 'Customer' },
      );
    },

    async getProfile(identityType, identity) {
      return unwrap(
        await call.get(METHODS.getProfile, {
          identity_type: identityType,
          identity,
        }),
      );
    },

    async updateCustomerProfile(customer, payload) {
      return unwrap(
        await call.post(METHODS.updateCustomerProfile, {
          customer,
          payload,
        }),
      );
    },
  };
}

export function unwrap(response) {
  const envelope = response?.message ?? response;
  if (!envelope) {
    throw new Error('Empty Frappe response');
  }
  if (envelope.success === false) {
    throw new Error(envelope.error?.message || envelope.message || 'Frappe API request failed');
  }
  return envelope.data ?? envelope;
}

export { METHODS as FRAPPE_METHODS };
