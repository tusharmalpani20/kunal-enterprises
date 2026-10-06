export type IdentityType = 'Customer' | 'Sales Employee';

export interface ProductGroup {
  name: string;
  group_name: string;
  full_path: string;
  product_group_logo: string | null;
}

export interface TallyItem {
  name: string;
  item_name: string;
  immediate_stock_group?: string;
  root_stock_group: string;
  mobile_summary_group?: string;
  mobile_summary_group_name?: string;
  mobile_summary_group_logo?: string | null;
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
  godown?: string | null;
  quantity: number;
  stockShownAtOrderTime?: number;
  stockSnapshotAt?: string;
}

export interface AllowedCustomer {
  customer: string;
  customer_name: string;
  business_legal_name: string;
  client_code: string;
}

export interface AllowedCustomerFixture extends AllowedCustomer {
  client_code: string;
}

export interface OrderSummary {
  entry_type?: 'order' | 'quick_order';
  order_source?: string;
  quick_order_request?: string | null;
  name: string;
  portal_reference_number: string;
  customer: string;
  customer_name?: string;
  sales_employee?: string;
  status: string;
  display_status?: string;
  confirmation_datetime?: string | null;
  total_quantity?: number;
}

export interface OrderDetail extends OrderSummary {
  quick_order_text?: string | null;
  placed_by?: string;
  placed_by_identity_type?: IdentityType;
  placed_by_name?: string;
  placed_by_label?: string;
  items?: Array<{
    item: string;
    item_name?: string;
    root_stock_group?: string;
    unit?: string;
    requested_quantity: number;
    fulfilled_quantity?: number;
    pending_quantity?: number;
    status?: string;
  }>;
  godown_allocations?: Array<{
    item: string;
    item_name?: string;
    unit?: string;
    godown?: string | null;
    requested_quantity: number;
    fulfilled_quantity?: number;
    pending_quantity?: number;
  }>;
}


export interface QuickOrderRequest {
  name: string;
  request?: string;
  status: 'Pending Review' | 'In Review' | 'Converted to Order' | 'Rejected';
  text: string;
  confirmation_datetime?: string | null;
  order?: string | null;
  portal_reference_number?: string | null;
  rejection_reason?: string | null;
}
