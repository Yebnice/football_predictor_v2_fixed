# PjDigitalServices — Production Audit & Hardening Changelog

## What was reviewed

The project was reviewed layer-by-layer across the Next.js application, API routes, Paystack flow, Techlink integration, Supabase storage, customer order tracking, admin area, PWA files and customer-support chatbot.

Current external facts were checked against official documentation for Next.js, Paystack, Supabase and Google Gemini.

## Major fixes applied

### 1. Framework/security baseline
- Targeted Next.js 16.2.x (Active LTS) and React 19.2.
- Added Node.js >=20.9 engine requirement.
- This matches the current Next.js support guidance: 16.x is Active LTS; 14.x is unsupported.

### 2. Admin authentication
- Removed browser localStorage storage of the admin password.
- Removed the `x-admin-key` authentication pattern.
- Added an HttpOnly, signed, expiring admin session cookie.
- Added login throttling.
- Added `/api/admin/login`, `/api/admin/logout`, and `/api/admin/me`.
- Missing `ADMIN_SESSION_SECRET` now fails closed instead of making the admin page public.

### 3. Customer order privacy
- Removed broad public searches by phone/email.
- Customer tracking now requires the exact order reference plus checkout email.
- Public tracking responses contain only customer-safe order fields.
- The admin endpoint remains able to retrieve full records after authentication.

### 4. Payment/fulfillment hardening
- Added a payment/fulfillment state machine:
  `pending -> payment_verified/ready -> processing -> fulfilled`
  with retryable `failed` fulfillment state.
- Added an atomic fulfillment claim so browser verification and Paystack webhook processing cannot both submit the same order to Techlink.
- Added payment amount and currency verification.
- Added a scheduled fulfillment worker endpoint at `/api/jobs/fulfill`.
- Failed fulfillment is retryable up to `MAX_FULFILLMENT_ATTEMPTS`.

### 5. Paystack webhook behavior
- Webhook signature validation is timing-safe.
- Webhook verifies the payment before marking the order ready.
- Webhook acknowledges quickly instead of performing long-running Techlink fulfillment inside the webhook request.

### 6. API abuse controls
- Added basic rate limiting for order creation, order tracking, feedback and AI chat.
- This is intentionally a lightweight application-level safety net; distributed deployments should also use the hosting platform's WAF/rate-limiter or a shared limiter.

### 7. AI customer support
- Reworked the chatbot into a hybrid assistant.
- No AI key: built-in FAQ mode still works.
- With `GEMINI_API_KEY`: the server uses the Gemini API with `GEMINI_MODEL` (default `gemini-3.8-flash`, Google's GA Flash-tier model released September 2, 2026). Support-chat replies request Google's LOW thinking level, since Annette answers short support questions rather than doing deep multi-step reasoning.
- Added secure order lookup inside chat only when both order reference and checkout email are supplied.
- The AI is prohibited from charging customers, bypassing Paystack, inventing live prices/statuses, or requesting/repeating PINs and sensitive identity information.
- Added a secure “Track my order” flow inside the chat widget.

## Required database migration

Run the updated `supabase/schema.sql` against the existing database. The important new order columns are:

- `fulfillment_status`
- `fulfillment_attempts`
- `last_fulfillment_error`
- `payment_verified_at`
- `payment_amount`

The schema file includes an idempotent migration block for existing deployments.

## Required environment values

Set these in deployment secrets:

- `PAYSTACK_SECRET_KEY`
- `NEXT_PUBLIC_PAYSTACK_PUBLIC_KEY`
- `TECHLINK_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` (or migrate to Supabase's newer `sb_secret_...` key)
- `ADMIN_PASSWORD`
- `ADMIN_SESSION_SECRET`
- `CRON_SECRET`
- `NEXT_PUBLIC_SITE_URL`
- Optional: `GEMINI_API_KEY`
- Optional: `GEMINI_MODEL`

## Scheduler requirement

The fulfillment worker must be called regularly in production:

`POST /api/jobs/fulfill`

with:

`Authorization: Bearer <CRON_SECRET>`

A hosting cron, external scheduler or equivalent should run this frequently enough for your service-level expectations.

## What was not falsely certified

I did not claim a live Paystack/Techlink transaction passed because no production credentials were supplied. The Techlink client was audited against the documentation already bundled/referenced by the project, but private endpoint behavior still needs a real test-key transaction before go-live.

## Build verification note

Node syntax checks passed for the modified server-side JavaScript and the modified JSX files were parsed successfully with TypeScript's JSX parser. A full `npm install`/`next build` could not be completed in this environment because dependency installation timed out on package-network access; run `npm install` followed by `npm run build` in your normal development environment before deployment.

## v1.1.1 hardening pass

- Added `processing_started_at` to support stale-worker detection.
- Stale fulfillment claims are moved to `manual_review`, not automatically retried, because Techlink idempotency has not been independently confirmed.
- Added rate limiting to public payment verification.
- Paystack webhook now returns HTTP 500 on internal processing errors so Paystack can retry instead of receiving a misleading success acknowledgement.
- Added explicit stale-fulfillment recovery processing to the scheduled worker.

### Remaining production gate
Before enabling automatic retries after a stale provider call, confirm Techlink supports idempotent transaction/reference submission or exposes a safe transaction-status lookup.

## v1.2.0 support/notification hardening
- Preserved official SLA wording in the FAQ.
- Updated FAQ failure wording so it no longer promises blind automatic retries.
- Added stale-order admin email notifications (optional via Resend).
- Added neutral customer delay notification: order is still processing; apologize for delay; do not mention payment review.
- Added notification deduplication timestamps to prevent repeat alerts.
- Added Admin > Manual Review view.
- Added `/api/orders/manual-review` admin endpoint.
- Added environment configuration for notification email delivery.

### v1.2.0 operational notes
- Run `supabase/migration_v1_2.sql` on an existing database before deploying this version.
- Configure `RESEND_API_KEY`, `NOTIFICATION_FROM_EMAIL`, and `ADMIN_ALERT_EMAIL` to enable automatic stale-order email alerts.
- Customer delay email deliberately says the order is still processing and apologizes for the delay; it does not say that payment is under review.
- Official service SLA wording in `pages/faq.js` has been preserved.


## v1.2.1 approved hardening additions
- Added admin-authorized manual-review actions: confirm fulfilled or authorize retry, each requiring an audit note.
- Added optional Twilio WhatsApp/SMS urgent escalation for manual-review orders.
- Fixed notification state so a notification is only recorded as sent after the provider reports success.
- Added Resend per-event idempotency keys instead of one global key.
- Preserved official provider SLA wording; customer delay messages say the order is still processing and apologize for the delay.


## v1.2.1 — final hardening review — September 15, 2026
- Added admin-authorized manual-review resolution/retry actions with mandatory notes.
- Added optional Twilio WhatsApp/SMS escalation; WhatsApp requires a configured approved content template.
- Added support-case lookup by case reference plus the contact detail used when submitting the case.
- Added throttling to public provider lookup endpoints and customer registration.
- Sanitized public order result/error fields.
- Fixed notification state so failed email delivery can be retried; Resend uses a unique per-event idempotency key.
- Stale processing recovery now always moves eligible stale claims to manual review, including orders at the maximum attempt count.
- Preserved the official SLA wording supplied with the project; only fulfillment/retry language was corrected.


Release: v1.2.1. Full npm install/build remains a deployment-environment verification step because package installation timed out in the audit container.


## v1.2.2 — Support transaction evidence requirements
- Data and airtime complaints now require Transaction ID, Amount, Data/Airtime Requested, Recipient/Beneficiary, Transaction Date & Time, Transaction Details, and complaint description.
- Other product complaints use the standard support form with transaction details relevant to the service.
- Email or phone is required so support can follow up and customers can track their case.
- The chatbot includes a structured complaint form and submits to the same server-side validation as the Feedback page.
- Admin feedback view displays service, transaction ID, amount, requested data, beneficiary, transaction time and transaction details.
- Added v1.2.2 Supabase migration: `supabase/migration_v1_2_2.sql`.


## v1.2.3 — Escalation provider swap (Twilio → Brevo)
- Replaced the Twilio WhatsApp/SMS urgent-escalation integration with Brevo transactional SMS. Brevo has no direct WhatsApp-template equivalent, so the WhatsApp leg is dropped; the admin-alert **email** channel (via the existing Resend integration) is now the second, independent escalation channel in its place.
- New env vars: `BREVO_API_KEY`, `BREVO_SMS_SENDER` (optional, defaults to `PjDigital`). Removed: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_SMS_FROM`, `TWILIO_WHATSAPP_FROM`, `TWILIO_WHATSAPP_CONTENT_SID`, `ADMIN_WHATSAPP_TO`. `ADMIN_SMS_TO` is unchanged.
- Fixed a pre-existing bug in `recoverAndListReadyOrders`: the two escalation channels were tried inside one `try/catch`, so if the first channel's send call threw, the second channel was silently never attempted for that cycle. Each channel now has its own `try/catch`, so a failure on one never blocks the other.
- No schema changes required for this release.


## v1.2.4 — Pre-launch fixes (dependency, authz, and a broken endpoint)
- **`xlsx` dependency**: the npm registry only ever published up to `0.18.5`, which carries two unpatched high-severity CVEs (CVE-2023-30533 prototype pollution, CVE-2024-22363 ReDoS) — and this app parses customer-uploaded Excel files client-side (`components/TierShop.js`, embedded in the public `/mtn-data`, `/at-data`, `/telecel-data` pages), so this was public attack surface. Switched `package.json` to install the fixed `0.20.3` build directly from SheetJS's own CDN distribution (`https://cdn.sheetjs.com/`), which is the vendor's documented distribution channel since they stopped publishing to npm.
- **`next` dependency**: `^16.3.3` was never a published version — `npm install` would have failed outright. Repinned to `^16.2.10`, a real, current release (16.2.5 was itself a security release).
- **`POST /api/customers/register` was completely broken**: it called `rateLimit(...)` without ever importing it, so every request threw an unhandled `ReferenceError` before reaching the try/catch. The "create an account" autofill feature has never worked. Added the missing import.
- **Order/case tracking authorization bypass**: `.ilike("email", ...)` in `findCustomerOrder` (store.js) and `findCustomerCase` (feedback.js) let a SQL wildcard in the submitted email (e.g. `%@%`, or a bare `%`) match any record regardless of its real email, given a known/guessed reference. Switched both to exact `.eq()`. Also switched support-case reference generation from `Math.random()` to `crypto.randomBytes`.
- Added baseline security headers (`X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, `Strict-Transport-Security`) to `next.config.js`, which previously set none.
- Fixed a case-sensitivity bug in the result-checker "lookup" fulfillment path (`lib/techlink.js`): sent uppercase `BECE`/`WASSCE` to `/result-check-service/request`, which the API's own docs example shows as lowercase — paid lookup orders could fail fulfillment over letter case.
- Replaced the Twilio WhatsApp/SMS escalation with Brevo transactional SMS + the existing Resend email as the second channel (see `.env.example` and DEPLOYMENT.md section 3).
- Chat widget and AI system prompt now consistently introduce the assistant as "Annette."
