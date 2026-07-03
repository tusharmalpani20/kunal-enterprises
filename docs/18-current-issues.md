# Current Issues

Brief tracker for issues found during local Frappe/mobile testing.

## Mobile Signup And Approval Flow

- iOS Simulator could not reliably reach `http://kunal.localhost:8000`; local mobile default was changed to `http://127.0.0.1:8000`.
- OTP verification errors were shown as `[object Object]`; the app now unwraps nested Frappe error messages.
- After Customer approval, mobile login briefly failed with `Invalid or inactive token` because the app checked access using the pre-login API handle; the post-OTP route now uses the verified OTP response.
- Stale validation banners stayed visible after successful login; successful OTP now clears the banner state.
- Local OTP testing depends on viewing `Mobile OTP` in Frappe Desk; production needs WhatsApp provider delivery verified end to end.

## Mobile Order Flow

- Product group search and back navigation work in the Simulator.
- A dev-only stock snapshot generator now exists at `kunal_enterprises.integrations.tally_postgres.seed_dev_stock_snapshots`.
- The generator writes deterministic fake rows to `rpt_stock_godown_balance`; the normal stock import then syncs those rows into `Tally Stock Snapshot`.
- Local dev seed/import run `TSR-13095` completed with `21679` stock rows seen, `21679` processed, and `0` errors.
- Remaining production caveat: fake dev stock is only for product testing. Production still needs a real Tally-computed stock-by-godown report validated against Tally.
