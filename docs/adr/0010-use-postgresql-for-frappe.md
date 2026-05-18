# Use PostgreSQL For Frappe

Frappe will be deployed with PostgreSQL as its application database. The Tally connector also writes to PostgreSQL as the raw Tally mirror, but the two databases/schemas remain separate logical stores: connector PostgreSQL is the integration mirror, while Frappe PostgreSQL is the application database. This keeps the stack consistent while preserving the boundary between raw Tally data and Frappe DocTypes.
