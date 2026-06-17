export type IdentityType = 'Customer' | 'Sales Employee';

export interface ProductGroup {
  name: string;
  group_name: string;
  full_path: string;
}

export interface TallyItem {
  name: string;
  item_name: string;
  root_stock_group: string;
  uom: string;
  total_closing_balance: number;
}

export interface ItemStock {
  item: string;
  godown: string;
  quantity: number;
  uom: string;
  synced_at?: string;
  as_on_date?: string;
}

export interface CartAllocation {
  item: string;
  itemName: string;
  godown: string;
  quantity: number;
  stockShownAtOrderTime: number;
  stockSnapshotAt?: string;
}

export interface AllowedCustomer {
  customer: string;
  customer_name: string;
  business_legal_name: string;
}

export interface AllowedCustomerFixture extends AllowedCustomer {
  client_code: string;
}

export interface OrderSummary {
  name: string;
  portal_reference_number: string;
  customer: string;
  customer_name?: string;
  sales_employee?: string;
  status: string;
  display_status?: string;
  total_quantity?: number;
}

export interface OrderDetail extends OrderSummary {
  placed_by?: string;
  placed_by_label?: string;
  godown_allocations?: Array<{
    item: string;
    godown: string;
    requested_quantity: number;
  }>;
}
