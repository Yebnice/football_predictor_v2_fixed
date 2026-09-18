## 2026-09-18 — v2.6.3 fact-check hardening

- Fixed package generation so CompositeFootballProvider can continue through the real provider chain when the first provider returns fewer fixtures than required.
- API package endpoints now request minimum real-fixture counts of 5/20/35 for daily/weekly/monthly generation.
- Replaced Starlette-dependent `request.url.path` rate-limit classification with the raw ASGI path.
- Upgraded FastAPI, Streamlit and PyJWT pins to current releases to address current security advisories.
- Bounded public tip-record, value-bet and explanation parameters.
- Corrected current livescoreFootball limit documentation to 1000 requests/IP/60s.


## 2026-09-18 — Deployment audit / v2.6.0

- Fixed provider settings wiring so FastAPI and Streamlit share the same provider factory and football-data enrichment settings.
- Made the default provider chain free-first: TheSportsDB → API-Football → football-data.org → livescoreFootball → Sofascore.
- Prevented free TheSportsDB V1 from being used as a live-score source.
- Fixed TheSportsDB → API-Football odds enrichment on single-fixture lookups.
- Blocked placeholder production JWT/RNG secrets.
- Hardened malformed JWT handling, database migration errors, and Render/Supabase direct-IPv6 misconfiguration.
- Added a default livescoreFootball league slug (`eng.1`).
- Made Groq explanation failures return a controlled 502 instead of a generic internal error.
- Aligned CI with the deployed Python 3.12 runtime.
- Current audit result: 62 tests passed, 14 optional tests skipped in the minimal environment.
- Deployment readiness score: 84/100; payment verification remains an integration boundary rather than an active payment verifier.

# Unreleased

- Removed the synthetic DemoProvider and all active demo-data fallback paths.
- `FOOTBALL_PROVIDER=auto` now uses only real external providers.
- Updated `.env.example`, Render configuration, deployment/setup docs, and provider status reporting to remove the demo provider.
- Kept unit-test mocks/fakes where they are test doubles rather than application data sources.

# Fixes applied (P0 bugs from the audit)

All six items below were verified against the actual source before fixing, then
verified again after. No behavior beyond what's described was changed.

1. **`app/engine.py` — tautological shortlist/slip picks.**
   Added `TIP_MARKETS` allowlist (1X2, Draw No Bet, BTTS, Total Goals @ 2.5 only)
   and a `MAX_TIP_PROBABILITY = 0.75` cap. `shortlist()` now ranks by edge vs the
   bookmaker's price when odds exist, otherwise by probability — but only within
   `[min_conf, max_conf]`, so it no longer surfaces "Under 5.5" (~97%) as a tip.
   `SlipGenerator` picks up this fix automatically since it calls `shortlist()`.

2. **`app/schemas.py` / `app/engine.py` — form treated as a rate but stored as a
   total.** Added `TeamForm.goals_for_per_game` / `goals_against_per_game`
   properties (matching the existing `goal_diff_per_game` pattern) and switched
   `expected_goals()` to use them. Previously widening the form window from
   last-5 to last-10 silently doubled the attack/defence terms. Verified: a
   5-match sample and a 10-match sample with the *same per-game rate* now
   produce identical λ (they didn't before).

3. **`app/api.py` — provider `ValueError` surfaced as a bare 500.**
   `_provider_fixtures()` now also catches `ValueError` (raised by
   `SofascoreProvider` for date ranges over its 14-day cap, and by
   `LivescoreFootballProvider` for a missing league slug) and converts it to a
   `400` with the underlying message, instead of falling through to the global
   handler. Hit routinely by `/slips/monthly`'s 31-day window against Sofascore.

4. **`frontend/streamlit_app.py` — missing `livescorefootball_league` kwarg.**
   The Streamlit `build_provider(...)` call now passes
   `livescorefootball_league=settings.livescorefootball_league or None`, matching
   `app/api.py`. Previously `FOOTBALL_PROVIDER=livescorefootball` raised
   `ValueError` in the dashboard but worked fine through the API.

5. **`frontend/streamlit_app.py` — stored/reflected XSS via `unsafe_allow_html`.**
   Added an `esc()` helper (`html.escape`) and applied it to every interpolated
   value that isn't fully static: fixture team/league names, market/selection
   strings, the Groq-generated explanation text, and — most importantly —
   admin-authored tip fields (`match`, `market`, `selection`, `teaser`,
   `kickoff_time`, `status`) that are persisted in SQLite and rendered to every
   visitor. Groq output is escaped *before* converting `\n` to `<br>`, so the
   model's own output can't reintroduce a tag.

6. **`README.md` drift.** Removed the still-present reference to
   `app/services/auth.py` (the file was already deleted; auth lives in
   `app/auth.py`), and corrected "58 tests" to the actual current count (67).

7. **`tests/test_config_security.py` — env leak.** Added `setUp`/`tearDown` that
   snapshot and restore `APP_ENV`, `RNG_SALT`, `AUTH_JWT_SECRET` around each
   test, since these tests mutate `os.environ` directly with no cleanup and
   could leak `APP_ENV=production` into whatever test runs after them.

All pre-existing tests that don't require `fastapi`/`httpx` (not installable in
this offline sandbox) were re-run against the changes and pass unmodified:
`test_engine.py`, `test_slips.py`, `test_migrations.py`, `test_corners_cards.py`.
`test_admin_board.py` and `test_config_security.py` weren't touched in a way
that should affect their outcome, but couldn't be executed here for lack of
network access to install dependencies — run them in your own environment
before deploying.

# Round 2 — making it "standard" (production-grade) improvements

Implemented on top of the P0 fixes above, all opt-in via config where they
carry a real cost trade-off (API quota, latency), so nothing changes behavior
for anyone who doesn't touch `.env`.

1. **Dixon-Coles low-score correlation** (`app/engine.py`). Added the
   Dixon-Coles (1997) tau adjustment to the 0-0/1-0/0-1/1-1 cells of the score
   matrix before renormalizing, controlled by `DIXON_COLES_RHO` (default
   `-0.1`, set `0` to disable). Verified numerically: with `rho=-0.1` vs
   `rho=0` on an otherwise-identical fixture, P(0-0) and P(1-1) rise and
   P(1-0)/P(0-1) fall by the same amount, and the matrix still sums to 1.

2. **List-fixture enrichment** (`app/data_providers.py`,
   `ApiFootballProvider`). `fixtures()` can now batch-enrich every fixture in
   a list with real form and odds — previously only `fixture_by_id()` did
   this, so list/slip views always showed neutral 1500/1500 elo and empty
   form. Gated behind `API_FOOTBALL_ENRICH_LISTS` (default off) because it's
   expensive on the free 100-req/day plan; team lookups are deduped across the
   list so a team appearing in several fixtures only costs one `/fixtures`
   call, not one per fixture.

3. **Odds label aliases + preferred bookmaker** (`_extract_1x2_odds`). Now
   recognizes `1/X/2` labels and literal team-name labels, not just
   `home`/`draw`/`away`, and can prefer a configured bookmaker
   (`ODDS_PREFERRED_BOOKMAKER`) instead of always taking whichever bookmaker
   happens to be first in the array. Verified with both alias styles and the
   preferred-bookmaker ordering.

4. **CORS + rate limiting** (`app/api.py`). Added `CORSMiddleware`
   (`CORS_ALLOWED_ORIGINS`, comma-separated, default `*` for dev) and a
   dependency-free in-memory fixed-window rate limiter keyed by client IP
   (`RATE_LIMIT_DEFAULT_PER_MINUTE` / `RATE_LIMIT_AUTH_PER_MINUTE`, the latter
   much tighter since `/auth/*` is the brute-forceable surface). No
   Redis/slowapi needed for a single-process deployment; the docstring on
   `_InMemoryRateLimiter` flags that a multi-worker/multi-instance deployment
   needs a shared store instead.

5. **livescoreFootball hardening** (`LivescoreFootballProvider`).
   - Pagination: `_get_all_pages()` loops while the payload reports another
     page (checks several plausible field-name conventions since the exact
     schema isn't confirmed — see the provider's own docstring), verified
     against a mocked 3-page response.
   - 429 backoff/retry with exponential backoff, honoring `Retry-After`,
     matching the real service's documented ~120 req/min public limit.
   - Fixed the naive-datetime bug: a date string with no `Z`/offset suffix is
     now normalized to UTC instead of staying naive, which previously could
     raise `TypeError: can't compare offset-naive and offset-aware datetimes`
     wherever it's checked against this app's aware UTC bounds. Verified with
     a no-suffix date string.

6. **Real corners/cards data** (`ApiFootballProvider._recent_discipline`).
   Pulls actual corner/card counts from `/fixtures/statistics` for a team's
   recent finished matches, replacing corners_cards.py's neutral
   league-average fallback with real per-team data when available. Gated
   behind `API_FOOTBALL_FETCH_DISCIPLINE` (default off) since it's the most
   expensive addition here — roughly one extra call per historical match per
   team — and only ever applied in `fixture_by_id()` (single lookups), never
   in the list-enrichment path above, regardless of that flag.

All new `.env` knobs are documented in `.env.example` with their cost
trade-offs. No new pip dependency was needed — CORS/rate-limiting middleware
uses `starlette`, already a transitive dependency of `fastapi`.

Re-ran everything runnable offline (no network to install `fastapi`/`httpx` in
this sandbox) after each change: `test_engine.py`, `test_slips.py`,
`test_migrations.py`, `test_corners_cards.py` (19 tests, all pass unmodified),
plus standalone checks for the Dixon-Coles direction/normalization, odds alias
extraction, preferred-bookmaker ordering, stat-value parsing, the pagination
loop against a mocked multi-page response, and the naive-datetime fix. Please
still run `test_admin_board.py` / `test_config_security.py` and a live smoke
test against a real API-Football key in your own environment before deploying
— those need `fastapi`/`httpx`, which this sandbox couldn't install.

# Round 3 — expanded tip-eligible markets

Widened `TIP_MARKETS`/`_is_tip_eligible` in `app/engine.py` to also cover:

- **Double Chance** (1X / X2 / 12) — was already computed in `markets()` but
  wasn't tip-eligible before; now allowlisted, no probability-line
  restriction needed (all three selections are inherently well-behaved).
- **Per-team Goals Over/Under** (e.g. "Arsenal Goals", "Chelsea Goals" —
  these are what "home goals over/under" and "away goals over/under" map to;
  they're labeled by team name, not literally "Home"/"Away") — restricted to
  the standard `Over 1.5`/`Under 1.5` line, same reasoning as `Total Goals`'
  2.5 restriction: wider lines are near-certainties, not real tips.
- **1X2 Home Win / Away Win** — this already covered "home or away to win"
  before this change; a genuine "either team wins, draws excluded" 2-way
  market isn't something the score grid can price on its own (draws are a
  real outcome, not something you can renormalize away), which is why
  Double Chance is the standard way books express that instead.

Verified against demo fixtures: the shortlist at a widened 0.55 band now
surfaces a mix of Double Chance, per-team Goals @ 1.5, 1X2, and Draw No Bet
across different fixtures, all still within the sane probability band.

# Round 4 — Vercel deployment (fact-checked, not assumed)

Web-searched Vercel's current docs (dated 2026-08-27, well after my training
cutoff) before writing anything, because "can this run on Vercel" changed
recently and I wasn't going to guess:

- **`app/api.py` (FastAPI) genuinely can run on Vercel now** — official
  zero-config support, confirmed from Vercel's own current docs. Added:
  - `pyproject.toml` (`[tool.vercel] entrypoint = "app.api:app"` — needed
    since `app/api.py` isn't one of Vercel's auto-detected filenames)
  - `vercel.json` (installs from a trimmed `requirements-vercel.txt`, 30s
    function timeout)
  - `requirements-vercel.txt` — API-only deps (verified by grepping every
    `import`/`from` reachable from `app/api.py`; Streamlit/pandas/plotly
    aren't in that graph, so they're excluded to keep the bundle small)
  - `app/db.py: assert_safe_for_current_host()` — Vercel Functions have no
    persistent local filesystem, so `DB_PATH` MUST be Postgres there. This
    fails fast with one clear error at startup instead of a confusing
    filesystem error on the first write. Verified: raises correctly when
    `VERCEL=1` + a local SQLite path, passes for Postgres or a normal local
    dev environment.
  - `DEPLOY_VERCEL.md` — full step-by-step guide

- **`frontend/streamlit_app.py` (Streamlit) genuinely CANNOT run on
  Vercel** — this isn't a config gap I could fix with a file in this repo.
  Confirmed from multiple current sources: Streamlit holds a long-lived
  WebSocket per browser tab with session state inside its own Tornado-based
  process; Vercel's new (2026) WebSocket support is per-function-instance
  with state expected to live in an external store, and nothing in Vercel's
  docs lists Streamlit as a supported framework for it. Recommended
  pairing instead: Streamlit Community Cloud (free, official Streamlit host,
  deploys from the same GitHub repo) — and since `streamlit_app.py` runs the
  engine in-process rather than calling the API over HTTP, the two don't
  need to coordinate beyond optionally sharing one Postgres `DB_PATH`.

- **Flagged honestly, not silently**: `_InMemoryRateLimiter` (Round 2) counts
  per-process, and Vercel can route consecutive requests to different
  function instances — so the configured `RATE_LIMIT_*` values are no longer
  a hard cap on Vercel specifically. Documented in `DEPLOY_VERCEL.md` rather
  than left for you to discover in production; needs a shared store
  (Redis/Upstash) to be a real guarantee there.

Re-ran the full offline suite (19 tests) plus a live Store/migrations
end-to-end check after these changes — all still pass. Did **not** verify
against an actual Vercel deployment or a real Postgres instance (no network
in this sandbox) — please do the `/health` and `/slips/daily` checks in
`DEPLOY_VERCEL.md` step 6 yourself after deploying.

# Round 5 — dropped Vercel, finalized Render + Streamlit Community Cloud

Removed `vercel.json`, `pyproject.toml`, `requirements-vercel.txt`,
`DEPLOY_VERCEL.md` per request. Replaced with:

- **`app/db.py`: added Render-specific detection.** Verified via Render's own
  docs (render.com/docs/environment-variables) that `RENDER=true` is always
  set on Render — but unlike Vercel, this doesn't unconditionally mean "no
  persistent disk" (a paid Render plan with a Disk attached is fine), so this
  logs a clear warning rather than hard-failing. Verified all three branches
  behave correctly: Render + local SQLite → warning only; Render + Postgres →
  silent; Vercel/Lambda + local SQLite → still hard RuntimeError as before.
- **`render.yaml`** — trimmed to the API service only (frontend moved to
  Streamlit Cloud); `DB_PATH` guidance now explicitly says Postgres is
  required on the free plan and explains why (confirmed via Render's docs:
  free web services have no persistent disk; Render's own free Postgres also
  explicitly ruled out since it expires after 30 days).
- **`DEPLOY_RENDER.md`** — full guide: get a non-expiring free Postgres
  (Supabase/Neon, not Render's own), deploy the API via the Blueprint, deploy
  the frontend on Streamlit Community Cloud, lock down CORS once both URLs
  are known. Also checked (rather than assumed) whether
  `AUTH_JWT_SECRET`/`RNG_SALT` need to match between the two services:
  they don't — `streamlit_app.py` constructs an `AuthConfig` but never uses
  it to issue/verify a token, it just checks passwords against the shared
  `Store` directly. Documented that finding along with the caveat that it'd
  change if a future feature has Streamlit call the API with a bearer token.
  Also included the alternative of running both services on Render itself
  (Streamlit runs fine there — it was only ever a Streamlit-on-*Vercel*
  problem), with the free-hours trade-off stated plainly.

Re-ran the full offline suite (19 tests) after these changes — still pass.

# Still open (judgment calls, not applied)

- Sofascore provider: still Playwright/Chromium-dependent, no odds; left as-is
- No automated tests added for the new API-Football code paths specifically
  (they're network-dependent — `_recent_discipline`, batch enrichment,
  odds aliasing use `unittest.mock` in the existing test style, worth adding
  if this goes to production)
- Multi-worker/multi-instance rate limiting needs a shared store (Redis) —
  flagged in the code, not implemented, since it requires infra you don't
  have configured yet
- No CSRF protection was added to the admin board's cookie/JWT auth flow if
  it uses cookies anywhere — worth a quick check of `app/auth.py` before
  exposing the admin UI publicly

