# Enhance Tally Database Loader For Godown-Wise Stock Snapshot

Godown-wise stock should come from a Tally-computed stock snapshot exported by enhancing `tally-database-loader`, not from naive summation of transaction rows. Demo data showed Delivery Challan and Sales voucher rows can duplicate the same physical movement, making raw transaction-derived stock unsafe without complex de-duplication. Adding a generic stock-by-godown snapshot export keeps the connector useful upstream and gives Frappe a clean `Tally Stock Snapshot` source.
