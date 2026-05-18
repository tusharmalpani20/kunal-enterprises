# Require Client Code Mapping For Customer App Access

Customer App Access requires mobile verification, admin approval, and a valid unique client code mapped to the Tally customer alias in `mst_ledger.alias`. Customer records may exist without a client code so admins can review signups, but customers cannot order until the mapping is valid. This keeps mobile access tied to the Tally customer identity needed for reconciliation.
