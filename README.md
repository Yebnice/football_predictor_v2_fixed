# PjDigitalServices

A pay-per-order storefront for airtime, data bundles, ECG and water bills,
and AFA registration. Customers pay you directly through Paystack for each
order — there's no wallet to pre-fund. Runs as a normal website and installs
like an app on phones (Add to Home Screen).

## Pages

- `/` — marketing landing page
- `/mtn-data`, `/at-data`, `/telecel-data` — the real tiered product structure (see below): MTN Master/Express, AT iShare/BigTime, Telecel Group Share, each with Single/Bulk/Excel
- `/data` — a simpler, faster alternative: live commission bundles, single purchase only, any network, no tiers to think about
- `/airtime` — instant top-up, all three networks
- `/bills` — ECG electricity (meter lookup, then prepaid top-up) and Ghana Water (account lookup returns a fixed bill amount)
- `/afa` — AFA farmer registration, with the real fields Techlink requires and the live registration fee
- `/tv` — DSTV, GOtv, StarTimes — smartcard validated before payment, fixed amount due
- `/checker` — BECE/WASSCE result checker: buy a voucher, or have Techlink look up the result for you (not instant)
- `/faq` — searchable FAQ, adapted from Techlink's real FAQ content (draft — please review the wording)
- `/dashboard` — customer order tracking
- `/track` — same lookup as the dashboard, for a customer who doesn't want to save their details
- `/register` — customers save name/email/phone for faster checkout next time
- `/feedback` — complaints and general feedback, land in the admin inbox
- `/admin` — sales totals, all orders, and the feedback inbox, password-protected

A chat bubble in the corner (`components/ChatWidget.js`) answers common
questions with canned responses — a simple keyword matcher, not a paid AI
service.

**No wallet balance anywhere, Paystack everywhere** — confirmed across the
whole app, including the new tiered pages: there's no "Wallet Balance"
display like the real Techlink site shows (that's their internal agent
wallet; this storefront never had one after the earlier redesign), and
every purchase — single, bulk, or Excel — goes through the same Paystack
popup as the rest of the site, never a "Wallet / Mobile Money" choice.

## MTN / AT / Telecel Data — the real tiered structure

Your screenshots showed the real product structure, and it's genuinely
different from a simple bundle list:

- **MTN Data**: MTN Master, MTN Express, MTN EVD/Airtime
- **AT Data**: AT iShare, AT BigTime, AT EVD/Airtime
- **Telecel Data**: Telecel Group Share, Telecel EVD/Airtime

Each of those has three ways to order, all built and working:
**Single** (one recipient), **Bulk** (paste a list, one `phone size` pair
per line, matching the exact format shown on the real site), and **Excel**
(upload a `.csv`/`.xlsx` file — parsed client-side, same underlying order
as Bulk).

**On Excel specifically** — a deliberate simplification worth knowing
about: rather than forwarding the raw file to Techlink's own
`/orders/excel` endpoint, this app parses the file in the browser and
submits it through the same JSON bulk endpoint (`/orders/bulk`) as the
Bulk tab. Same outcome for the customer (upload a file, place a bulk
order), but far simpler and more secure to build — no server-side file
storage, no multipart forwarding, and it stays inside the same
verify-then-fulfil security pattern as everything else. If you specifically
need the file itself preserved or forwarded to Techlink's own Excel
endpoint (e.g. for their own template-column mapping), that's a distinct,
addable change.

**Pricing for this catalogue** works slightly differently from the
"Quick data top-up" page: `lib/agentProducts.js` holds a reference copy of
the real prices you provided (for the tier picker to feel instant), but the
amount actually charged is always re-confirmed live against
`GET /products?category=...` at the moment of purchase — so a stale local
number can never overcharge or undercharge a customer, it would just show
briefly wrong before checkout and get corrected at payment.

**MTN Master's real delivery time** — this is the "note under the master
data plan" you asked me to check. Your screenshot showed a live queue with
a **20.2 hour** wait on one order and a typical wait of **6.4 hours**
across 128 deliveries — meaningfully slower than the FAQ's general
"30 minutes to a few hours" framing. I've put this directly on the MTN
Master tab as a visible warning (`sellingNotes` in `lib/agentProducts.js`),
along with the other real selling rules from your screenshots: verify the
number first (wrong numbers aren't refunded), check the line has no
outstanding balance, and Turbonet/Broadband SIMs aren't eligible for
Master. The same treatment applies to AT iShare/BigTime (AirtelTigo-only
number prefixes, checked live on the form) and general "no duplicate
orders" advice on bulk orders.

**One thing I did NOT bring into the app, on purpose**: the real site's
"no social media ads" rule (advertising these bundles on social media gets
the Techlink account deleted). That's a policy aimed at **you**, the
account holder, not something to put on a customer-facing page — just
flagging it here so you don't lose your API access by advertising the
bundles themselves on social media. Advertising your own storefront is a
different thing and presumably fine — if you're unsure where that line is,
worth confirming with Techlink directly.

## On pricing — what's live vs what's fixed

You shared real screenshots of the agent site, and they confirmed something
important: **data bundle prices are not fixed** — MTN's own catalogue alone
has ~30 different SKUs split across No Expiry / Hourly / Night / Daily /
Weekly / Monthly, and AirtelTigo's is a completely different set (BigTime,
Fuse Voice and Data, Sika Kokoo, XXL Family Pack). AT and Telecel each have
their own separate pricing too, and the docs are explicit that this catalog
comes from the provider live so "nothing drifts out of sync."

Given that, I did **not** hardcode your screenshots into the app — copying
today's prices into code would make them wrong the moment Techlink updates
their catalogue. Instead, `/data` calls `GET /data/bundles` live, every
time, through `pages/api/techlink/data-bundles.js`. Once your API key is
set, whatever a customer sees is whatever Techlink is actually charging you
right now — always correct, no maintenance.

The same live-lookup approach is used for:
- **AFA fee** — pulled from `GET /products/afa-price` (your screenshot showed GHS 12.00 today; the app doesn't hardcode that number, it asks Techlink)
- **Water bill amount** — resolved from `POST /korba/validate`, not typed by the customer
- **TV subscription amount** — resolved from smartcard validation, not typed by the customer
- **Result checker prices** — pulled from `GET /products/checker-prices` and `GET /result-check-service/prices`

The only prices a customer types themselves are airtime top-up amount and
ECG top-up amount, because those are genuinely open-ended (you decide how
much airtime or electricity you want) — Techlink's docs confirm both are
priced by amount, not by catalogue.

**Worth knowing — airtime has no built-in margin.** The docs state the
airtime service fee (currently 2%, live at `GET /products/airtime-fee`,
proxied here at `/api/techlink/airtime-fee`) is charged to **your own**
Techlink wallet, not the customer — "the wallet is debited with the total."
Since your customer pays you exactly the face value they asked for via
Paystack, and Techlink then takes face value **plus** 2% from your wallet,
airtime orders lose you a small amount by default unless you build a markup
into what you charge. Data bundles, water, TV and AFA don't have this
issue — their prices already come straight from Techlink's own catalogue.
Simplest fix if you want one: charge the customer face value × 1.02 (or
round up) instead of the exact amount they typed — that's a one-line change
in `pages/airtime.js` and `pages/api/orders/create.js` if you want it; I
left it as pure pass-through for now rather than guessing your margin
strategy for you.

**On water and TV validation** — I flagged this as ambiguous earlier, but a
closer re-read of the docs resolved most of it: water bill validation is
confirmed as `POST /korba/validate`, and TV smartcard validation is
confirmed as `POST /provider/validate`. The one remaining thing worth a
quick live test: that shared `/provider/validate` path takes a `"service"`
field for GWCL water validation but a `"billType"` field for TV validation,
per the docs' own examples — a small naming quirk on a shared endpoint,
not real uncertainty about which endpoint to call.

## Customer dashboard

`/dashboard` is not a full login system — it remembers the email a customer
used at checkout (saved in their browser) and looks up every order tied to
that email or phone via `/api/orders/track`. This matters because several
services aren't instant:
- The result-checker "check it for you" service is a manual lookup — no immediate delivery.
- Any order can, in practice, sit briefly if Techlink's own fulfillment is delayed (the docs mention this for the general order flow too — "providers settle asynchronously").

The dashboard tells the customer plainly when something is still pending. If
you want real accounts with passwords later, that's a bigger addition (see
"What I didn't build" below).

## Should document services (business registration, passports, merchant SIM, affidavits) be added?

Short answer: **the API supports it, but I'd hold off** — here's why.

Every one of those four services (`/business/register`, `/passport/apply`,
`/merchant-sim/apply`, `/affidavit/apply`) is `multipart/form-data` with 10+
required fields including photo/document uploads (Ghana Card, signatures,
birth certificates), and some require a Bearer JWT login flow rather than
just your API key. That's a meaningfully different, much larger product —
closer to a government-services portal than an airtime/data storefront.
Building it properly means: file upload handling and storage, a login
system (the JWT auth endpoints aren't wired up anywhere in this project),
and careful validation matching each service's specific required-field list.

If you want this later, it's a real, scoped project on its own — happy to
build it as a phase 2 once the core storefront is live and proven. For now
I'd rather ship what's here solidly than half-build four complex document
flows.

## What changed from the wallet version

- The wallet balance / "top up wallet" screen is gone.
- Every purchase (airtime, data, bills, AFA) now opens a Paystack payment
  popup for the customer's card, mobile money, or bank transfer.
- Fulfillment (actually sending the airtime/data/bill payment via Techlink)
  only happens **after** your server independently confirms the payment
  with Paystack — never based on what the browser reports. This is what
  stops someone from faking a success message to get a free order.


## Before you can take real payments

1. **Get a real Techlink API key.** The endpoints are all wired up
   correctly now (based on your PDF documentation and screenshots) — the
   only missing piece is your actual key. Get one from your Techlink agent
   dashboard (Auth & API Keys → Create key), set `TECHLINK_API_KEY` in your
   environment (`tlg_test_...` while testing, `tlg_live_...` once live),
   and everything in `lib/techlink.js` will start making real calls.

2. **Get your Paystack keys.** Dashboard → Settings → API Keys & Webhooks.
   Use the test keys first (`sk_test_...` / `pk_test_...`).

## Database — detailed Supabase workflow

Orders, customers, and feedback are stored in **Postgres, via Supabase**
(`lib/store.js`, `lib/customers.js`, `lib/feedback.js` — all now talk to
Supabase instead of an in-memory array). Supabase was chosen because:

- Free tier is enough for a store this size to start on.
- It's plain Postgres underneath — if you ever outgrow Supabase, the data
  moves to any other Postgres host with no rewrite.
- One dashboard to browse orders/customers/feedback as tables, without
  writing SQL, if you ever want to look something up by hand.

**Important — Supabase is a database only.** It does not host your website
and has nothing to do with your domain name. It stores data; Vercel (or
another host) runs the actual Next.js app and serves it to visitors. See
"Domain and hosting" below for that half.

**Exactly what to do, in order:**

1. **Create the project.** Go to [supabase.com](https://supabase.com) →
   sign up (free) → **New project**. Pick a name (e.g. "pjdigitalservices"),
   set a database password (save it somewhere — you likely won't need it
   again since the app connects via API key, not this password), pick a
   region close to Ghana (Europe West is typically the closest available
   region), and create the project. Takes about 2 minutes to provision.

2. **Run the schema.** In the left sidebar, click **SQL Editor** → **New
   query**. Open `supabase/schema.sql` from this project on your computer,
   copy its entire contents, paste into the editor, and click **Run**. You
   should see "Success. No rows returned." This creates three tables:
   `orders`, `customers`, `feedback`. Confirm by clicking **Table Editor**
   in the sidebar — you should see all three listed, empty.

3. **Get your credentials.** Sidebar → **Project Settings** (gear icon) →
   **API**. Copy two values:
   - **Project URL** (looks like `https://xxxxx.supabase.co`) → this is `SUPABASE_URL`
   - **service_role secret** (under "Project API keys" — NOT the `anon`/`public` one) → this is `SUPABASE_SERVICE_ROLE_KEY`

4. **Put them in your environment.** Locally, paste both into `.env.local`.
   Once you deploy (see the deployment workflow further down), paste the
   same two values into Vercel's Project Settings → Environment Variables.

5. **Verify the connection.** Run the app locally (`npm run dev`), place
   one test order all the way through (with Paystack test keys), then check
   Supabase's **Table Editor → orders** — your test order should appear as
   a row. If it doesn't, double check the two env vars are spelled exactly
   right and that you ran the schema in step 2.

**Keeping the schema in sync later:** if I (or you) add a new field to an
order in the future, the change shows up as a comment at the top of
`supabase/schema.sql` (an `alter table ...` line) — run just that one line
in the SQL Editor rather than the whole file again, so you don't lose
existing data.

**Row Level Security:** Supabase turns RLS on by default for new tables,
and that's fine left as-is — this app only ever talks to Postgres using the
`service_role` key from server-side code, which bypasses RLS entirely. You
don't need to write any policies.

## Domain and hosting

Supabase does **not** provide web hosting or a domain — it's the database
only. For the actual website:

- **Hosting: Vercel** (recommended, already covered in the deployment
  workflow below). Free tier is enough to start, it's built by the same
  team as Next.js so it "just works" with zero config, and it gives you a
  free `https://yourproject.vercel.app` URL immediately with HTTPS already
  set up.
- **Domain name:** buy one separately from any registrar — Namecheap,
  GoDaddy, or a Ghanaian registrar if you want a `.com.gh` — then attach it
  in Vercel under **Project Settings → Domains**. Vercel gives you DNS
  records to add at your registrar; once added (usually live within an
  hour), your custom domain serves the same app over HTTPS automatically.
- You do not need a domain to launch — the free `vercel.app` URL is a real,
  working, secure address. A custom domain is purely about branding
  (`pjdigitalservices.com` instead of `pjdigitalservices.vercel.app`) and can be
  added at any time without redeploying anything.

## Is this compatible with desktop, mobile, and Android 9+?

Yes. This is a standard responsive website (not a native app), so it runs
in any modern browser on any device — desktop Windows/Mac/Linux, iPhone,
and Android. Specifically on Android 9: Android's Chrome browser
auto-updates independently of the OS version, so an Android 9 phone today
is almost certainly running a recent Chrome release, and everything this
app uses (fetch, CSS Grid/Flexbox, service workers for the "Add to Home
Screen" install prompt) has been supported in Chrome since well before
Android 9 shipped in 2018. The layout is built mobile-first with a single
responsive breakpoint approach (flexible grids, wrapping navigation), so it
resizes cleanly from a small phone screen up to a wide desktop monitor
without a separate mobile version to maintain.

One caveat: very old or unusual browsers (Internet Explorer, or Android's
old stock "Internet" browser predating Chrome) aren't tested against and
may render imperfectly — but for a Ghanaian customer base on Chrome
(by far the dominant browser on Android), this is a non-issue.

## Setup

```bash
npm install
cp .env.example .env.local
## Production hardening applied in v1.1.0

This version includes the production fixes identified during the security/architecture review:

- Upgraded the app target from unsupported Next.js 14 to Next.js 16.3.3 / React 19.2. Next.js currently lists 16.x as Active LTS and 14.x as unsupported; Vercel also issued an August 2026 security release for 16.3.3 and 15.5.24.
- Replaced the browser-stored admin password/header with an HttpOnly, signed admin session cookie. Set `ADMIN_SESSION_SECRET` to a long random secret. The shared `ADMIN_PASSWORD` remains server-side only.
- Customer order tracking now requires both the exact order reference and checkout email and returns only customer-safe order fields.
- Fulfillment is now an atomic claim/state flow: `pending -> payment_verified/ready -> processing -> fulfilled` with retryable failures. This prevents a webhook and browser callback from both sending the same order to Techlink.
- Paystack webhooks verify the signature/payment and acknowledge quickly; the actual Techlink fulfillment is handled by the browser callback or `/api/jobs/fulfill`. Paystack's current webhook guidance specifically recommends returning HTTP 200 promptly and notes failed webhooks are retried.
- Added a protected fulfillment worker endpoint using `CRON_SECRET`. Configure an external scheduler or your hosting platform's cron facility to call `POST /api/jobs/fulfill` with `Authorization: Bearer $CRON_SECRET`.
- Added basic API rate limiting for order creation, tracking, feedback and AI chat. For a multi-instance deployment, also use your host/WAF or a distributed rate limiter.
- Added an optional AI support route. With `GEMINI_API_KEY` set, the chat uses `GEMINI_MODEL` (default `gemini-flash-latest`); without a key it automatically falls back to the built-in FAQ assistant. Live order context is only fetched when the customer supplies both reference and checkout email.
- The AI is support-only: it cannot charge customers, cannot bypass Paystack, and is instructed not to request or repeat card/PIN/Ghana Card details.

### Required deployment steps

1. Run the updated `supabase/schema.sql` migration on your existing database (or create the fresh schema).
2. Add `ADMIN_SESSION_SECRET` and `CRON_SECRET`; rotate any old admin password/header secrets that may have been exposed during development.
3. Set `PAYSTACK_SECRET_KEY`, `NEXT_PUBLIC_PAYSTACK_PUBLIC_KEY`, `TECHLINK_API_KEY` and `SUPABASE_URL`. Prefer Supabase's current `sb_secret_...` server key where your project provides it; otherwise the legacy service-role key remains supported but must stay backend-only.
4. If using AI, set `GEMINI_API_KEY` and optionally `GEMINI_MODEL`.
5. Configure your scheduler to call `/api/jobs/fulfill` regularly. The worker retries failed fulfillment up to `MAX_FULFILLMENT_ATTEMPTS`; after that, an admin should inspect the order.
6. Complete Paystack test-mode and Techlink test-key transactions before switching to live credentials.


# fill in .env.local with your real keys (Supabase, Paystack, Techlink)
npm run dev
```

Visit `http://localhost:3000`.

## Environment variables

| Variable | Where it's used |
|---|---|
| `SUPABASE_URL` | Server only — database connection |
| `SUPABASE_SERVICE_ROLE_KEY` | Server only — database connection |
| `PAYSTACK_SECRET_KEY` | Server only — verifying payments |
| `NEXT_PUBLIC_PAYSTACK_PUBLIC_KEY` | Browser — opening the payment popup |
| `TECHLINK_API_BASE_URL` | Server only — calling Techlink |
| `TECHLINK_API_KEY` | Server only — calling Techlink |
| `ADMIN_PASSWORD` | Server only — gates `/admin` |
| `NEXT_PUBLIC_SITE_URL` | Your deployed domain |

Never put a secret key in anything prefixed `NEXT_PUBLIC_` — those get
shipped to the browser in plain text.

## How a purchase works

1. Customer fills in the form and clicks pay → `pages/api/orders/create.js`
   creates a pending order **priced by the server**, not the browser.
2. Paystack Popup opens (`pages/index.js`) using the public key.
3. On success, the browser calls `pages/api/orders/verify.js`, which asks
   Paystack directly to confirm the payment really went through, checks the
   amount matches, and only then calls Techlink to deliver the order.
4. Set up the Paystack webhook (`pages/api/paystack/webhook.js`) as a second,
   more reliable path — see below.

## Setting up the Paystack webhook

In your Paystack dashboard → Settings → API Keys & Webhooks, set the webhook
URL to:

```
https://yourdomain.com/api/paystack/webhook
```

This matters because the `verify` call above only fires if the customer's
browser is still open. The webhook fires from Paystack's servers regardless,
so orders still get delivered if someone closes the tab right after paying.
Both paths are safe to have running together — fulfillment only ever
happens once per order.

## Full deployment workflow

Follow this in order — each step depends on the one before it.

**1. Database.** Do the Supabase setup above (create project, run
`supabase/schema.sql`, grab the URL and service role key).

**2. Techlink.** Get the confirmed endpoint details from your Postman
collection and fill in `lib/techlink.js` (see the section below). Nothing
downstream matters if this step is skipped — orders will "succeed" on
payment but never actually deliver.

**3. Paystack test keys.** Get your **test** keys from the Paystack
dashboard (Settings → API Keys & Webhooks). Put them in `.env.local` as
`PAYSTACK_SECRET_KEY` / `NEXT_PUBLIC_PAYSTACK_PUBLIC_KEY`.

**4. Run it locally and test the full loop.**
```bash
npm install
npm run dev
```
Go through every flow — airtime, data, bills, AFA — using
[Paystack's test card numbers](https://paystack.com/docs/payments/test-payments)
(no real money moves with test keys). Confirm: the order appears in
`/admin`, the amount matches, and `fulfilled` becomes `true`.

**5. Push to GitHub.** Commit everything except `.env.local` (already
covered by a typical `.gitignore` — double check it's not committed, since
it would contain live secrets once you fill it in for step 8).

**6. Deploy to Vercel** (made by the creators of Next.js; free tier is
enough to start):
   - Import the GitHub repo at [vercel.com](https://vercel.com).
   - Add every variable from `.env.example` under Project Settings →
     Environment Variables — still using the Paystack **test** keys for now.
   - Deploy. You'll get a `https://yourproject.vercel.app` URL.

   Any other Node.js host (Render, Railway, your own VPS) works too —
   `npm run build` then `npm run start`.

**7. Point the Paystack webhook at your deployed URL.** Paystack dashboard
→ Settings → API Keys & Webhooks → webhook URL:
`https://yourproject.vercel.app/api/paystack/webhook`. Still using test
mode, place one more test order and confirm the webhook fired (Paystack's
dashboard shows webhook delivery logs).

**8. Set your admin password and confirm `/admin` is locked.** Set
`ADMIN_PASSWORD` in Vercel's environment variables, redeploy, and check
that `/admin` asks for it.

**9. Switch to live Paystack keys.** Once steps 4–8 all check out, replace
the test keys with live keys (`sk_live_...` / `pk_live_...`) in Vercel's
environment variables and redeploy. Update the webhook URL in the live
mode view of the Paystack dashboard too — test and live mode have separate
webhook settings.

**10. Add your own domain** (optional) under Vercel → Settings → Domains,
and update `NEXT_PUBLIC_SITE_URL` to match.

**11. Add real PWA icons** at `public/icons/icon-192.png` and
`icon-512.png` so "Add to Home Screen" shows your actual logo instead of
nothing.

**12. Do one real, small live-money order yourself** before telling
customers you're open — pay with your own card/momo for the cheapest
airtime amount, confirm it actually lands on your phone, and check it shows
correctly in `/admin`.

After that, you're live. Keep an eye on `/admin` and the Paystack dashboard
for the first few days in case anything about Techlink's real behavior
(error formats, delays) needs a tweak in `lib/techlink.js`.

## Making it installable as an app

This is already a PWA (`public/manifest.json` + `public/sw.js`). Once
deployed on `https://`, visitors on Android/Chrome get an "Install app"
prompt, and on iPhone they can use Safari's Share → "Add to Home Screen".
No app store submission needed.

If you specifically want a listing in the Google Play Store / Apple App
Store later, the standard route is wrapping this same website with
[Capacitor](https://capacitorjs.com/) — it packages a web app into a native
app shell without rewriting anything here. That's a separate step to take
once the website itself is live and working.

## Still to do

- [ ] Get a real `TECHLINK_API_KEY` (`tlg_test_...` first) and do one live test of `/provider/validate` for both water (GWCL) and TV to confirm the field-naming quirk noted above
- [ ] Run `supabase/schema.sql` in your Supabase project and fill in `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` (see the detailed workflow above)
- [ ] Set `ADMIN_PASSWORD` before deploying publicly
- [ ] Add real icon files at `public/icons/icon-192.png` and `icon-512.png`
- [ ] Work through the deployment workflow above, in order
- [ ] Review and tweak the homepage copy in `pages/index.js` to taste
- [ ] Decide if/when you want document services (business reg, passports, merchant SIM, affidavits) as a phase 2
- [ ] Review the FAQ wording on `/faq` — it's adapted from Techlink's real FAQ content but written by me, not you
- [ ] If you also want a real MTN Master delivery-status widget (queue position, live "typical wait" like the real site shows), that needs `GET /orders/dashboard/stats` wired up — not built yet, happy to add once you confirm you want it
- [ ] Run `npm run build` locally once you have real keys, just to catch anything this sandbox couldn't test (see note below)


## Support complaint transaction requirements (v1.2.2)
For data and airtime complaints, the support form and chatbot require Transaction ID, Amount, Data/Airtime Requested, Recipient/Beneficiary, Transaction Date & Time, Transaction Details, and the complaint description. For other products, the normal support form is used with transaction details relevant to the service.
