# Use PostgreSQL As Raw Tally Mirror And Frappe As Application Model

The `tally-database-loader` PostgreSQL database is the raw mirror of Tally data, not the application database used by mobile and portal business logic. Frappe imports/syncs required data into custom DocTypes so permissions, access rules, status, snapshots, and APIs remain under the application model. This keeps raw connector schema changes isolated from the customer/sales/portal experience.
