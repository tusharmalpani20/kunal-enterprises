# Use Frappe Custom App, Not ERPNext

The portal/backend will be built as a custom Frappe app, not as an ERPNext implementation. Tally remains the inventory/accounting source of truth, while Frappe owns the application workflow: customer approval, sales employee access, Product Group permissions, Orders, PDFs, WhatsApp logs, and reconciliation state. This avoids forcing the business process into ERPNext inventory/accounting models when the operational system of record is already Tally.
