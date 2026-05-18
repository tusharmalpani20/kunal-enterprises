# Reconcile Orders By Tally Reference Number And Item Quantity

Order fulfillment reconciliation uses the portal Order reference entered in Tally's Reference Number field and synced as `trn_voucher.reference_number`. Fulfilled quantity is matched item-wise, not godown-wise, because operations may fulfill from a different godown than the customer selected. Sales Invoice is the primary fulfillment signal when present, Delivery Challan is provisional, and duplicated DC/Sales movement must be counted only once.
