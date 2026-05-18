# Use Custom JWT Mobile Auth

Mobile authentication will use an independent custom JWT/session flow instead of Frappe's normal Desk login/session model. Customers and sales employees authenticate with WhatsApp OTP and receive a mobile session that remains valid until logout, account disablement, or access removal. This keeps mobile auth aligned with OTP-based app access rules while preserving Frappe Desk authentication separately for internal portal users.
