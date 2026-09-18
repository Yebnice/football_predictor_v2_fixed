# PjDigitalServices — Deployment Process Flow

This walks through the three services you asked about, in the order they
actually need to happen (Supabase first — Vercel needs its keys; Brevo last
— it's optional and only affects the escalation feature). Paystack and
Techlink credentials are assumed already in hand; they're referenced only
where the order matters.

---

## 1. Supabase

**1.1 Create the project**
- New project at supabase.com → note the **Project URL** and, in
  Project Settings → API, the **service role key** (or the newer
  `sb_secret_...` secret key if your project has migrated to Supabase's
  new key format — either works, `lib/supabaseClient.js` accepts both via
  `SUPABASE_SECRET_KEY` or `SUPABASE_SERVICE_ROLE_KEY`).
- Never use the `anon`/publishable key for this app — every table has RLS
  enabled with no public policies, so only the secret/service-role key
  (server-side only) can read or write.

**1.2 Run the schema**
- SQL Editor → paste the full contents of `supabase/schema.sql` → Run.
  This version has been corrected to include all columns the app code
  actually uses (the previous package was missing four manual-review
  columns that would have caused runtime errors — now fixed).
- If you're upgrading an **existing** database that already ran an older
  schema, you don't need the migration files anymore for a fresh
  install — but if you're patching an existing production DB, run
  `supabase/migration_v1_2.sql` and `supabase/migration_v1_2_2.sql` too;
  both use `add column if not exists`, so they're safe to run even if
  some columns already exist.

**1.3 Sanity-check**
- Table Editor → confirm `orders`, `customers`, and `feedback` exist and
  `orders` has `fulfillment_status`, `manual_review_at`,
  `manual_review_resolution`, `manual_review_resolved_at`, and
  `urgent_review_notified_at` columns.

---

## 2. Vercel

**2.1 Import the repo**
- New Project → import the GitHub repo (push this codebase to GitHub
  first if it isn't already). Framework preset: Next.js — Vercel detects
  it automatically.

**2.2 Environment variables**
Set these in Project Settings → Environment Variables (Production, and
Preview if you want staging to work too):

| Variable | Required | Notes |
|---|---|---|
| `SUPABASE_URL` | Yes | From step 1.1 |
| `SUPABASE_SERVICE_ROLE_KEY` (or `SUPABASE_SECRET_KEY`) | Yes | From step 1.1 — server only |
| `PAYSTACK_SECRET_KEY` | Yes | Paystack dashboard → API Keys. Use `sk_test_...` until you're ready to go live |
| `NEXT_PUBLIC_PAYSTACK_PUBLIC_KEY` | Yes | Same page, `pk_test_...`/`pk_live_...` |
| `TECHLINK_API_KEY` | Yes | `tlg_test_...` while testing, `tlg_live_...` for real orders |
| `ADMIN_PASSWORD` | Yes | Pick something strong — this gates `/admin` |
| `ADMIN_SESSION_SECRET` | Yes | Random string, **32+ characters** (`openssl rand -base64 32`) |
| `CRON_SECRET` | Yes | Random string — protects `/api/jobs/fulfill` |
| `NEXT_PUBLIC_SITE_URL` | Yes | Your production URL, e.g. `https://pjdigitalservices.com` |
| `GEMINI_API_KEY` | Optional | Enables the live AI agent in chat; omit and the chatbot still works in FAQ-only mode |
| `GEMINI_MODEL` | Optional | Defaults to `gemini-flash-latest` if unset |
| `RESEND_API_KEY`, `NOTIFICATION_FROM_EMAIL`, `ADMIN_ALERT_EMAIL` | Optional | Stale-order email alerts |
| `BREVO_API_KEY`, `BREVO_SMS_SENDER` | Optional | SMS escalation leg — see section 3 |
| `MAX_FULFILLMENT_ATTEMPTS`, `FULFILLMENT_STALE_MINUTES`, `URGENT_REVIEW_MINUTES`, `FULFILLMENT_BATCH_SIZE` | Optional | Tuning knobs, sensible defaults exist in code |

**2.3 Deploy**
- Trigger the first deploy. Watch the build log — this is the first real
  `next build` this project has had in this whole process (I could only
  static-check it, not compile it), so this is where any real compile
  error would surface.

**2.4 Point Paystack at your webhook**
- Paystack Dashboard → Settings → API Keys & Webhooks → Webhook URL:
  `https://<your-domain>/api/paystack/webhook`
- This only works once the app is deployed and publicly reachable —
  Paystack can't call `localhost`.

**2.5 Schedule the fulfillment worker**
`/api/jobs/fulfill` has to be called regularly or orders will sit in
`ready` state indefinitely. Two easy options on Vercel:

- **Vercel Cron** (simplest): add a `vercel.json` with:
  ```json
  {
    "crons": [{ "path": "/api/jobs/fulfill", "schedule": "*/2 * * * *" }]
  }
  ```
  Vercel Cron calls this with its own auth, so you'd adapt the route to
  check Vercel's cron signature instead of/in addition to the Bearer
  token — or simpler, keep the existing `Authorization: Bearer
  <CRON_SECRET>` check and use an external scheduler (below) if you'd
  rather not touch the auth code.
- **External scheduler** (no code change needed): a service like
  cron-job.org, GitHub Actions on a schedule, or your own server, hitting:
  ```
  POST https://<your-domain>/api/jobs/fulfill
  Authorization: Bearer <CRON_SECRET>
  ```
  every 1–5 minutes.

**2.6 Custom domain**
- Project Settings → Domains → add `pjdigitalservices.online` (and, if you
  want `www` too, add `www.pjdigitalservices.online` — Vercel will offer to
  redirect one to the other).
- Vercel shows you the exact records to add, but for a typical apex + www
  setup on Vercel they are:
  | Type | Name | Value |
  |---|---|---|
  | A | `@` | `76.76.21.21` |
  | CNAME | `www` | `cname.vercel-dns.com` |

  Always use the exact value Vercel's dashboard shows you for *your*
  project over the generic ones above — occasionally it's a project-specific
  alias instead. Add these at whoever you registered the domain through
  (your registrar's DNS panel), not in Vercel, unless you delegate the
  domain's nameservers to Vercel entirely (Vercel will offer this option too).
- DNS propagation is usually minutes, occasionally a few hours. Vercel
  auto-issues an SSL certificate once it verifies the records.
- Update `NEXT_PUBLIC_SITE_URL` to `https://pjdigitalservices.online` and
  redeploy — this value is used in outbound emails and the admin-alert
  link, so it needs to match the live domain.
- **If you set `NOTIFICATION_FROM_EMAIL` to an address on this domain**
  (e.g. `alerts@pjdigitalservices.online`), you must verify the domain
  in Resend first (Resend dashboard → Domains → add
  `pjdigitalservices.online` → add the SPF/DKIM DNS records it gives you).
  Sending from an unverified domain will fail outright or land in spam —
  this step isn't optional once you're on your own domain, and it wasn't
  called out earlier in this doc when there was no real domain yet.
- Paystack's webhook URL (step 2.4) and the cron target (step 2.5) should
  both be updated to use `https://pjdigitalservices.online/...` once the
  domain is live, rather than the `*.vercel.app` URL you tested with.

---

## 3. Brevo (optional — only affects the SMS escalation feature)

This only fires when an order sits in manual review past
`URGENT_REVIEW_MINUTES` (default 30). Everything else in the app works
without Brevo configured at all. Escalation now has two independent legs:
an SMS via Brevo, and an email via the Resend integration you already set
up in section 2.2/step "Optional — Stale-order email alerts". Either, both,
or neither can be configured; each is attempted and logged independently,
so a failure on one never blocks the other.

**3.1 Account and API key**
- Create a Brevo account → **SMTP & API** → **API Keys** → generate a key
  → set as `BREVO_API_KEY`.
- Brevo's transactional SMS is metered separately from its email plan —
  confirm your account has SMS credit (or top up) before relying on this
  in production; a zero-balance account will fail sends with a 4xx error
  that's logged but otherwise silent to the customer, by design.

**3.2 Sender ID**
- Set `BREVO_SMS_SENDER` to the name you want alerts to appear "from".
  Brevo caps alphanumeric sender IDs at **11 characters**, letters and
  digits only (no spaces/punctuation) — e.g. `PjDigital`. If unset, the
  code defaults to `PjDigital`.
- Note: alphanumeric sender IDs are not deliverable to every country's
  carriers (notably the US/Canada, which require a registered numeric
  sender). Since this app is Ghana-focused this is normally fine, but
  confirm deliverability to `ADMIN_SMS_TO`'s network before depending on
  it operationally.

**3.3 Recipient**
- Set `ADMIN_SMS_TO` to the phone that should receive urgent alerts, as
  digits with country code (e.g. `233240000000`). A leading `+` is
  accepted and stripped automatically. No template approval or opt-in
  flow is needed — Brevo's transactional SMS type is meant for exactly
  this kind of operational alert.

**3.4 Email leg (no new setup)**
- The second escalation channel reuses `ADMIN_ALERT_EMAIL` and
  `RESEND_API_KEY`/`NOTIFICATION_FROM_EMAIL` from section 2.2. If you
  already configured those for stale-order alerts, the urgent escalation
  email will fire automatically once an order crosses
  `URGENT_REVIEW_MINUTES` — nothing further to do here.

**3.5 Test it**
- Force an order into manual review (or lower `URGENT_REVIEW_MINUTES` to
  1 temporarily in a test environment) and confirm the SMS and/or email
  alert arrives, then restore the normal value.
- Check both the SMS and email legs independently at least once — since
  they're now decoupled, a config mistake on one (e.g. wrong
  `BREVO_SMS_SENDER`) won't be obvious from the other succeeding.

---

## 4. End-to-end test checklist before calling it "live"

1. `npm install && npm run build` succeeds locally with no errors.
2. Full checkout with a **Paystack test card**: place a small data/airtime
   order → pay → confirm the order reaches `fulfilled` (via the browser
   callback or, if you close the tab early, via the webhook + scheduled
   worker within a couple of minutes).
3. Force a webhook retry: temporarily break something server-side and
   confirm Paystack sees a 500 and retries (per the v1.1.1 hardening
   note, the webhook now returns 500 on internal errors instead of a
   false "received: true").
4. Test the water and TV validate flows specifically — the code's own
   comments flag `service` vs `billType` as a naming quirk on a shared
   Techlink endpoint; confirm both resolve correctly against a real
   account/smartcard before trusting them for customers.
5. Log into `/admin` with `ADMIN_PASSWORD`, confirm the session cookie
   works and manual-review orders display correctly (this is what
   exercises the schema fix from section 1.2).
6. Open the chat widget: ask an FAQ-style question, try "Track my order"
   with a real reference+email, and submit a test complaint through
   "Report a problem" — confirm it lands in `/admin` → Feedback.
7. If `GEMINI_API_KEY` is set, confirm chat replies are clearly
   AI-generated (not just canned FAQ text) and that removing the key
   falls back to FAQ mode without errors.
8. Do **not** enable automatic stale-claim retries in
   `recoverStaleProcessingOrders` beyond what ships by default until
   you've confirmed with Techlink that resubmitting a transaction
   reference is safe/idempotent — this is flagged as an open question in
   the project's own changelog, not something I've verified.
