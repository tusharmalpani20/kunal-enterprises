import { sortGodownStockForMobile } from '../domain/mobileFlow.mjs';
import { orderDetailForMobile, orderSummaryForMobile } from '../domain/profileHistoryFlow.mjs';
import { MAX_CUSTOMER_SEARCH_RESULTS, sanitizeCustomerForSalesEmployee } from '../domain/salesEmployeeFlow.mjs';

const METHODS = {
  startCustomerSignup: 'kunal_enterprises.api.otp.start_customer_signup',
  sendOtp: 'kunal_enterprises.api.otp.send_otp',
  sendLoginOtp: 'kunal_enterprises.api.otp.send_login_otp',
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
  quickOrderSubmit: 'kunal_enterprises.api.quick_orders.submit',
  quickOrderHistory: 'kunal_enterprises.api.quick_orders.history',
  quickOrderDetail: 'kunal_enterprises.api.quick_orders.detail',
  orderHistory: 'kunal_enterprises.api.orders.history',
  orderDetail: 'kunal_enterprises.api.orders.detail',
  getProfile: 'kunal_enterprises.api.profile.get_profile',
  updateCustomerProfile: 'kunal_enterprises.api.profile.update_customer_profile',
};

export function createFrappeApiClient(call) {
  return {
    async startCustomerSignup(payload) {
      return postOtp(call, METHODS.startCustomerSignup, { payload });
    },

    async startCustomerOtp(mobileNumber) {
      return postOtp(call, METHODS.sendOtp, {
        mobile_number: mobileNumber,
        identity_type: 'Customer',
      });
    },

    async startLoginOtp(mobileNumber) {
      return postOtp(call, METHODS.sendLoginOtp, { mobile_number: mobileNumber });
    },

    async startSalesEmployeeOtp(mobileNumber) {
      return postOtp(call, METHODS.sendOtp, {
        mobile_number: mobileNumber,
        identity_type: 'Sales Employee',
      });
    },

    async resendOtp(mobileNumber, identityType) {
      return postOtp(call, METHODS.resendOtp, {
        mobile_number: mobileNumber,
        identity_type: identityType,
      });
    },

    async verifyCustomerOtp(mobileNumber, otpCode) {
      return postOtp(call, METHODS.verifyCustomerOtp, {
        mobile_number: mobileNumber,
        otp_code: otpCode,
      });
    },

    async verifySalesEmployeeOtp(mobileNumber, otpCode) {
      return postOtp(call, METHODS.verifySalesEmployeeOtp, {
        mobile_number: mobileNumber,
        otp_code: otpCode,
      });
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

    async allowedCustomers(salesEmployee, search = '', limit) {
      const params = {
        sales_employee: salesEmployee,
        search,
      };
      if (limit !== undefined) {
        params.limit = limit;
      }
      const data = unwrap(
        await call.get(METHODS.allowedCustomers, params),
      );
      return data.customers.slice(0, limit ?? MAX_CUSTOMER_SEARCH_RESULTS).map(sanitizeCustomerForSalesEmployee);
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

    async allowedItemsPage(customer, productGroup, salesEmployee = undefined, options = {}) {
      const params = {
        customer,
        product_group: productGroup,
        sales_employee: salesEmployee,
      };
      const search = String(options.search || '').trim();
      if (search) {
        params.search = search;
      }
      if (options.limit !== undefined) {
        params.limit = options.limit;
      }
      if (options.offset !== undefined) {
        params.offset = options.offset;
      }
      const data = unwrap(
        await call.get(METHODS.allowedItems, params),
      );
      return data;
    },

    async allowedItems(customer, productGroup, salesEmployee = undefined, options = {}) {
      const data = await this.allowedItemsPage(customer, productGroup, salesEmployee, options);
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

    async quickOrderSubmit(text, customer) {
      return unwrap(await call.post(METHODS.quickOrderSubmit, { text, customer }));
    },

    async quickOrderHistory(customer, options = {}) {
      return unwrap(await call.get(METHODS.quickOrderHistory, {
        customer, limit: options.limit ?? 20, offset: options.offset ?? 0,
      }));
    },

    async quickOrderDetail(request, customer) {
      return unwrap(await call.get(METHODS.quickOrderDetail, { request, customer }));
    },

    async orderHistory(customer, salesEmployee = undefined, options = {}) {
      const data = unwrap(
        await call.get(METHODS.orderHistory, {
          customer,
          sales_employee: salesEmployee,
          limit: options.limit ?? 20,
          offset: options.offset ?? 0,
          ...(options.includeQuickOrders ? { include_quick_orders: 1 } : {}),
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

async function postOtp(call, method, params) {
  try {
    return unwrap(await call.post(method, params));
  } catch (error) {
    if (/timeout|network request failed|failed to fetch|data.*undefined|undefined.*data|couldn'?t connect/i.test(String(error?.message || error))) {
      throw new Error('Unable to reach the server. Please check your connection and try again.');
    }
    throw error;
  }
}

export { METHODS as FRAPPE_METHODS };
