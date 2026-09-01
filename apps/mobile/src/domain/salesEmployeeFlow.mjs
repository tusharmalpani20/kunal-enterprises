import { orderAllocationForApi } from './mobileFlow.mjs';

export const MIN_CUSTOMER_SEARCH_LENGTH = 2;
export const MAX_CUSTOMER_SEARCH_RESULTS = 60;

export function customerSearchQuery(value) {
  const query = (value || '').trim();
  return query.length >= MIN_CUSTOMER_SEARCH_LENGTH ? query : null;
}

export function filterAllowedCustomers(customers, search) {
  const query = (search || '').trim().toLowerCase();
  if (query.length < MIN_CUSTOMER_SEARCH_LENGTH) {
    return [];
  }

  return customers.filter((customer) =>
    [customer.customer, customer.customer_name, customer.business_legal_name, customer.client_code].some((value) =>
      String(value || '').toLowerCase().includes(query),
    ),
  );
}

export function sanitizeCustomerForSalesEmployee(customer) {
  return {
    customer: customer.customer,
    customer_name: customer.customer_name,
    business_legal_name: customer.business_legal_name,
    client_code: customer.client_code,
  };
}

export function buildSalesEmployeeOrderPayload({ salesEmployee, customer, allocations, note }) {
  if (!salesEmployee) {
    throw new Error('Sales Employee is required');
  }
  if (!customer) {
    throw new Error('Customer is required');
  }

	return {
		customer,
		sales_employee: salesEmployee,
		sales_employee_note: note || undefined,
		allocations: allocations.map(orderAllocationForApi),
	};
}

export function salesEmployeeOrderGuard({ selectedCustomer, allocations }) {
  if (!selectedCustomer?.customer) {
    return {
      canSubmit: false,
      step: 'customer',
      state: { kind: 'validation_error', message: 'Select a Customer before ordering.' },
    };
  }

  if (!Array.isArray(allocations) || allocations.length === 0) {
    return {
      canSubmit: false,
      step: 'summary',
      state: { kind: 'validation_error', message: 'Add at least one item before confirming the order.' },
    };
  }

  return {
    canSubmit: true,
    step: 'summary',
    state: { kind: 'idle' },
  };
}

export function salesEmployeeHistory(orders, salesEmployee) {
  return orders.filter((order) => order.sales_employee === salesEmployee);
}
