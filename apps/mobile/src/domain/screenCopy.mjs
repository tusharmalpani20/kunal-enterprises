export function orderHeaderSubtitle({ mode, selectedCustomer }) {
  if (mode === 'Customer') {
    return 'Product Group first. Stock is latest synced, not a reservation.';
  }

  if (selectedCustomer) {
    return `${selectedCustomer.customer_name} selected.`;
  }

  return 'Select a Customer before ordering. Search can match internal records without showing them.';
}

export function pendingAccessMessage() {
  return 'Ordering unlocks after admin approval and active Customer App Access.';
}
