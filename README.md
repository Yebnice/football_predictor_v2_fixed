# Global AI Football Predictor v2

A modular football prediction platform built around a score-distribution engine, multi-market probabilities, controlled randomized slips, live fixtures, VIP access hooks, and optional Groq explanations.

## What is included

- Real provider adapter interface with configurable external providers.
- Historical/live fixture normalization.
- ELO + recent-form + home/away strength feature layer (falls back to xG when the provider supplies it).
- Poisson score-distribution engine.
- Multi-market probability engine:
  - 1X2, double chance, draw-no-bet
  - over/under 0.5 through 5.5 (match total) and 0.5 through 3.5 (each team)
  - BTTS yes/no
  - exact correct score (top 10 by probability)
  - winning margin (1, 2, 3+ either side)
- Corners & cards estimator (`app/corners_cards.py`), a separate module from the goals engine — see its own section below.
- Fair odds from model probabilities.
- Optional comparison against bookmaker odds when supplied by the provider (currently 1X2 only).
- Value/edge calculation, now exposed via `/match/{id}/value-bets`.
- Daily, weekly and monthly slip generators using controlled randomization after quality filtering.
- Daily: one slip with 5-10 eligible matches.
- Weekly: 5 different randomized slips, 20 matches each.
- Monthly: 5 different randomized slips, 30-50 matches each; at least 35 eligible matches are required so distinct 30+ selections are mathematically possible.
- FastAPI backend.
- Streamlit dashboard, including a public Free/VVIP tips feed and an admin board — see its own section below.
- Groq integration for natural-language match explanations, wired up at `/match/{id}/explain`; Groq is an explanation/assistant layer, not a replacement for the statistical model.
- Optional Appwrite mirror sync for profiles/tips when APPWRITE_* settings and the optional SDK are configured; the primary source of truth remains this app's database. The admin/VVIP board uses its own server-side accounts/roles system, not Appwrite Auth.
- USDT, MTN MoMo and Telecel payment service interfaces; provider verification remains server-side and must be configured with the applicable merchant/API credentials.

**Not implemented yet, despite being mentioned in earlier drafts of this README:** half-time/full-time matrix markets, Asian handicap/totals calculators, and an ML blend on top of the Poisson model. Corners/cards markets *are* now implemented (see below) — this line used to list them as missing; that's been corrected. If you need the remaining ones, they'd extend `FootballProbabilityEngine.markets()` and, for handicap, the provider's fixture normalization — they are not hidden hooks already wired in.

## Important

This package is a strong application foundation, not a guarantee of betting outcomes. Production accuracy requires a real historical dataset, out-of-sample validation, calibration, live-data verification and ongoing monitoring.

Payment connectors are intentionally isolated. Do not activate VIP from a user-submitted screenshot or unverified transaction hash. Server-side verification is required before a subscription becomes active.

## Corners & cards markets

`app/corners_cards.py` is a separate module from the goals engine, with its own tests (`tests/test_corners_cards.py`). It estimates:

- Total Corners: over/under 8.5, 9.5, 10.5, 11.5
- Total Cards: over/under 2.5, 3.5, 4.5
- Team Corners (each side): over/under 3.5, 4.5, 5.5

Model: corners and cards are each treated as independent Poisson counts for the home and away side, scaled from a `TeamDiscipline` average (corners/cards for and against per team) and a per-fixture league average, with a small home/away adjustment. No new data source is required. Real providers that do not populate `TeamDiscipline` fall back to fixture-level league averages, i.e. a neutral estimate for both sides until per-team corner/card history is added the same way `_recent_form()` already is for goals.

Every corners/cards `MarketPrediction` carries `metadata={"estimated": True, "basis": "...not live match stats"}` — check that flag in your own UI, since this is a model estimate, not scraped in-match data. The default league averages (9.6 total corners, 3.8 total cards) are documented with their sourcing/caveats directly in `app/schemas.py`'s `Fixture` docstring — the corners figure is anchored to FootyStats' cited Premier League/Champions League 2025-26 averages; the cards figure is a commonly-cited range, not a single sourced statistic, and is flagged as such in code.

## Admin board + VVIP tips

**Important correction on how this is built:** the original spec for this feature said to "enable Lovable Cloud." Lovable Cloud is a hosted backend (Supabase-based) tied specifically to projects built with Lovable's own app builder — it isn't something that can be switched on inside a separately-hosted FastAPI/Streamlit codebase like this one. Rather than skip the feature or silently misrepresent what was built, this uses a from-scratch equivalent that fits this stack, with the same data shape and security posture that was requested:

- `app/store.py` — SQLite (swap for Postgres if you run multiple instances). Three tables: `profiles` (email + password hash only — **no privilege flags live here**), `user_roles` (role grants as their own rows), `tips`.
- `app/auth.py` — password hashing via stdlib `hashlib.scrypt` (no new heavy dependency) and JWT sessions via the already-listed `PyJWT` package.
- `app/admin_board.py` — the routes themselves.

Endpoints:

| Method & path | Access | Purpose |
|---|---|---|
| `POST /auth/signup`, `POST /auth/login` | Public | Email/password accounts; returns a bearer token |
| `GET /tips` | Public (optional auth) | Free tips in full; VVIP tips as locked teasers unless the caller is VVIP or admin |
| `GET /tips/record?days=30` | Public | Won/Lost/win-rate from settled tips in the window |
| `GET/POST /admin/tips`, `PUT/DELETE /admin/tips/{id}` | Admin only | Create/edit/delete a tip |
| `POST /admin/tips/{id}/settle` | Admin only | Mark Won / Lost / Void |
| `GET /admin/members`, `POST /admin/members/{id}/vvip` | Admin only | Member list + VVIP toggle |

Security notes, since this replaces a Postgres-RLS-based design with plain SQL:

- There's no database-level row-level security here (SQLite doesn't have it) — the exact same guarantee is instead enforced in `admin_board.py`'s route layer: every admin route depends on `require_role("admin")`, which calls `Store.has_role()` **fresh against the database on every request**. JWTs carry only a user id and expiry, no role claims, specifically so that revoking VVIP or admin access takes effect immediately rather than waiting for a token to expire — there's a regression test (`test_revoking_vvip_relocks_immediately_without_a_new_token`) proving this.
- The first admin account is created via `ADMIN_BOOTSTRAP_EMAIL`/`ADMIN_BOOTSTRAP_PASSWORD` in `.env` — it only ever runs while no admin exists yet, so it's safe to leave set after your first login.
- A minimal admin UI (sign in/up, post/settle/delete tips, member VVIP toggles) is built into the Streamlit dashboard, running in-process against the same SQLite file as the API. That's a convenience for solo/local operation, not a substitute for the API's own auth in a real multi-user deployment — both enforce the same role checks either way.
- Out of scope, matching the original request: shots/possession/player props/half-time markets, Asian handicap, and VVIP payment collection (flag members manually via the admin board for now).

### Syncing to Appwrite (optional)

`app/appwrite_sync.py` adds a genuine, working (not stub) one-way sync: after every signup, tip create/update/settle/delete, and VVIP grant/revoke, the app also best-effort mirrors that write into an Appwrite database using the official `appwrite` Python SDK (verified against SDK v24.0.0's real method signatures). It's a mirror, not a backend swap — SQLite stays the source of truth this app reads from, and a failed Appwrite call is logged and swallowed rather than breaking the request. There's no sync in the other direction: edits made directly in the Appwrite console won't flow back into this app.

This replaces the old `AppwriteAuthService` in `app/services/auth.py`, which was a dead stub — defined, but never called from anywhere in the app despite the config settings suggesting otherwise. That file has been removed.

**Full step-by-step Appwrite Console setup (creating the project, database, collections, attributes, permissions, and API key) is in the accompanying PDF guide** — it's long enough that it doesn't belong inline here. In short, once you've followed it, set `APPWRITE_ENDPOINT`, `APPWRITE_PROJECT_ID`, `APPWRITE_API_KEY`, `APPWRITE_DATABASE_ID`, `APPWRITE_PROFILES_COLLECTION_ID`, and `APPWRITE_TIPS_COLLECTION_ID` in `.env`, `pip install -r requirements-optional.txt`, and restart the app — `GET /health` will report `"appwrite_sync_configured": true` once it's live.

**Free-tier gotcha worth knowing before you rely on this for anything:** as of February 27, 2026, Appwrite auto-pauses free-tier projects with no development activity for 7 consecutive days (per Appwrite's own documentation). If your app syncs infrequently, your project can go to sleep and silently stop accepting writes until you manually resume it in the console — the PDF guide covers this.

## Sofascore provider (scores/fixtures only, no odds)

`FOOTBALL_PROVIDER=sofascore` wraps the third-party `EasySoccerData` package as a fallback for scores/fixtures when you don't want to deal with API-Football's free-plan season restriction. It is deliberately scores/fixtures-only — `/match/{id}/odds` and `/match/{id}/value-bets` will return nothing useful for it, since Sofascore's free site has no bookmaker odds.

**Read this before enabling it — it's a materially different kind of dependency than the REST-only providers above:**

- **Not a lightweight HTTP client.** It drives a real headless Chromium browser via Playwright to get past Sofascore's bot protection. Install with `pip install -r requirements-optional.txt` (not in the base `requirements.txt`, to keep the default install light), then run `playwright install chromium` once, or point `SOFASCORE_BROWSER_PATH` at an existing Chrome/Chromium binary.
- **Heavier at runtime.** A live browser process per app instance (~150-300MB RAM, multi-second startup). Likely won't run on a typical free-tier PaaS web dyno without a custom Docker image bundling Chromium. Call `provider.close()` (the FastAPI app already does this on shutdown) or the browser process leaks.
- **Licensing:** `EasySoccerData` is GPL-3.0 (per its own PyPI metadata). If you plan to distribute or run this app commercially, have that combination checked against GPL-3.0's terms — this is a fact to check, not legal advice, and no other dependency here carries that restriction.
- **Packaging gotcha we found:** `EasySoccerData`'s PyPI metadata only declares `httpx` as a dependency, but its Sofascore module unconditionally imports `playwright`. A bare `pip install EasySoccerData` will raise `ModuleNotFoundError` on a clean environment — `requirements-optional.txt` installs `playwright` alongside it for you, but you still need the separate `playwright install chromium` step.
- **It works by circumventing bot detection, not calling a sanctioned API.** Treat it as a fragile smoke-testing fallback, not a production data source, and check Sofascore's terms of service before relying on it further.

Practical differences from `ApiFootballProvider`: `get_events()` upstream only accepts a single date or `live=True` (no date range), so `fixtures()` makes one browser call per calendar day and is capped at 14 days per call (raises `ValueError` beyond that — pass `league`+`season` as Sofascore's own tournament/season ids, discoverable via `esd`'s `search()`, to use a single tournament lookup instead). `season` is left blank on returned fixtures since Sofascore's event payload doesn't include it directly.

## livescoreFootball provider (scores/fixtures only, no key, unverified response shape)

`FOOTBALL_PROVIDER=livescorefootball` wraps [rezarahiminia/livescoreFootball](https://github.com/rezarahiminia/livescoreFootball) (worldcup26.ir) — a free, open-source, no-API-key REST API for English and Spanish club football (Premier League, EFL, FA Cup, LaLiga, LaLiga 2, Copa del Rey, women's competitions).

**Fact-checked directly against the project's own GitHub README before integrating** (not taken on trust): the listener→MongoDB→read-only-API architecture, the England/Spain coverage, and the "no API key currently required" claim are all confirmed from the primary source, and the project has real, independent adoption (451 stars, 92 forks at the time of writing) — this is meaningfully more credible than some other football-data projects circulating with self-promotional or AI-targeted marketing copy attached (a different one was checked and rejected during this same review for exactly that reason).

**What's still unverified, and why the code below is written defensively:**

- **No API key is a current gap, not a guarantee.** The project's own docs state "API-key issuance and per-customer quotas are not implemented yet" — this could change without notice.
- **The exact JSON field names are not confirmed.** This sandbox has no network path to worldcup26.ir, so `_normalize_livescorefootball_fixture` in `app/data_providers.py` checks several plausible key names per field (`homeTeam`/`home_team`/`home`, etc.) rather than assuming one. If fields come back empty once you actually run this against the live API, that function is where to fix the mapping — log one real response first.
- **The underlying upstream data source isn't named.** The README calls the response shape "provider-compatible" without saying which provider; the league-slug convention (`eng.1`, `esp.1`) resembles ESPN's unofficial site API, but this isn't confirmed. Treat it with the same "likely unofficial source" caution as the Sofascore provider above.
- **No odds at all** — this source doesn't have them, so `/match/{id}/value-bets` will always be empty for fixtures from this provider (not a bug in this adapter).

Unlike API-Football, there's no "all leagues" fixtures endpoint here — every call needs a league slug (e.g. `eng.1` for the Premier League, `esp.1` for LaLiga; the full list is at `GET /get/soccer/leagues` on the live site). Set `LIVESCOREFOOTBALL_LEAGUE` in `.env`, or pass `league=` per call.

## Multi-provider football data (free-first)

The app is now provider-agnostic. Set `FOOTBALL_PROVIDER=auto` to use the configured chain in `FOOTBALL_PROVIDER_CHAIN`; providers that require credentials are skipped automatically when their key is missing. This means the default chain can stay broad without making a clean install fail because an optional provider is unavailable.

The recommended free-first chain is:

```text
thesportsdb -> api-football -> football-data -> livescorefootball -> sofascore
```

`FOOTBALL_PROVIDER_MODE=fallback` uses the first source that returns data. Set `FOOTBALL_PROVIDER_MODE=merge` to query every available source and de-duplicate identical fixtures, with earlier providers winning when records overlap. The `/providers` endpoint reports the active chain without exposing secrets.

### Current provider roles

| Provider | Current free access | Best role in this app | Notes |
|---|---|---|---|
| **API-Football / API-Sports** | 100 requests/day on the current free plan | Odds, events, lineups, fixtures and richer match data | Requires a free API key; free coverage can be season-limited. |
| **football-data.org** | Free forever; 10 calls/min on the free plan | Fixtures, schedules and competition data | Free scores/schedules are delayed; requires a free registered token. |
| **TheSportsDB V1** | Free shared key `123`; 30 requests/min currently documented | Zero-setup fixture/team fallback | V1 is free; V2/livescores are premium. |
| **Sofascore** | Optional | Scores/fixtures fallback | Browser automation, not a sanctioned REST API; keep optional. |
| **livescoreFootball** | Optional no-key community source | Selected league fixtures/scores | Coverage and availability can change; keep as a fallback only. |

These limits/features were checked against the providers' current documentation before this integration. API-Football currently advertises 100 requests/day on its free plan and access to endpoints including fixtures, odds, statistics, injuries and predictions; football-data.org currently lists 12 competitions and 10 calls/min on its free tier; TheSportsDB currently documents V1 as free with shared key `123` and a 30 requests/min free limit. citeturn888036search1turn888036search3turn888036search0

### Adding another API later

No prediction-engine changes are required. Add a class implementing the existing `FootballProvider` contract, register its short name in `build_provider()`, add its credentials/config fields to `Settings`, then place the name anywhere in `FOOTBALL_PROVIDER_CHAIN`. The composite router handles fallback, de-duplication and provider-specific lookup routing for you.

### Recommended `.env`

```text
FOOTBALL_PROVIDER=auto
FOOTBALL_PROVIDER_CHAIN=thesportsdb,api-football,football-data,livescorefootball,sofascore
FOOTBALL_PROVIDER_MODE=fallback
THESPORTSDB_API_KEY=123
THESPORTSDB_LEAGUE_ID=4328
FOOTBALL_DATA_API_KEY=
API_FOOTBALL_KEY=
```

With only the settings above, TheSportsDB V1 is the active real-data source/fallback. Adding `API_FOOTBALL_KEY` automatically makes API-Football available to the chain; adding `FOOTBALL_DATA_API_KEY` does the same for football-data.org.

## Run locally

PowerShell:

```powershell
cd C:\path\to\football_predictor_v2
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
streamlit run frontend\streamlit_app.py
```

`.env.example` now defaults to `FOOTBALL_PROVIDER=auto`, using a free-first provider chain. With the documented TheSportsDB V1 key `123`, the app can fetch real fixture data without a paid subscription. Add `API_FOOTBALL_KEY` and/or `FOOTBALL_DATA_API_KEY` later and the auto chain will make those providers available automatically.

API:

```powershell
python -m uvicorn app.api:app --reload --port 8000
```

## Real football API

Set `FOOTBALL_PROVIDER` to your implemented provider adapter and place its credentials in `.env`. The included generic REST adapter demonstrates the normalized contract; map endpoint names/fields to the provider you subscribe to.

## Groq

Set `GROQ_API_KEY`. The app can generate explanations such as why a market made the shortlist. Keep all Groq calls server-side.

## Appwrite

The `app/services/payments.py` module is a verification boundary only: USDT/MTN MoMo/Telecel calls return `pending` or `unsupported` until a real server-side merchant/blockchain verification integration is configured. Do not treat a `pending` response as successful payment or activate VVIP access from it.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The current offline suite reports **62 passed, 14 skipped** when optional browser/Appwrite dependencies are absent. The optional Appwrite CI job installs its SDK and runs those tests separately; the core suite requires no network access or live API keys.

## API-Football integration

The project now includes a first-class `ApiFootballProvider` for API-Football v3 using the `x-apisports-key` request header. Set:

```text
FOOTBALL_PROVIDER=api-football
FOOTBALL_API_BASE_URL=https://v3.football.api-sports.io
API_FOOTBALL_KEY=your_key_here
```

The backend normalizes API-Football fixtures into the internal schema and exposes provider-specific event, lineup, and odds routes under `/match/{fixture_id}/...`. Keep the API key server-side; never expose it in the frontend.

**Free-plan caveats (verified against api-football.com, Sept 2026):** the free plan is **100 requests/day**. API-Football states that all plans include the competitions/endpoints, while **Free plans are limited in available seasons**. If a free-key fixture query is empty, pass `league` and `season` explicitly and check the coverage/status available to your key instead of assuming the endpoint itself is unavailable. The app now caches identical provider reads for `PROVIDER_CACHE_TTL_SECONDS` (default 60s) to help stay under the daily cap while you iterate, and returns a clear message instead of a raw 500 if you hit the 429 rate limit.

## Newer endpoints

- `GET /match/{id}/value-bets?min_edge=0.05` — same markets as `/markets`, filtered to selections where the model's fair price beats the supplied bookmaker odds by at least `min_edge`. Only 1X2 currently carries bookmaker odds, so this is effectively a 1X2 value filter until another market's odds are wired in.
- `GET /match/{id}/explain` — runs the existing (previously unused) Groq explainer against a fixture's shortlist and returns the text.
- `GET /fixtures?league=&season=` — optional filters, mainly useful to work around the free-plan season restriction above.

## Free API recommendations for match data/analysis (implementation notes)

| Provider | Free tier | Good for | Watch out for |
|---|---|---|---|
| **API-Football** (api-sports.io) — used by `ApiFootballProvider` | 100 req/day; endpoints available, with free-plan season restrictions | Odds, lineups, events, statistics, fixtures | Daily cap and limited available seasons on the free plan |
| **Sofascore via `EasySoccerData`** — used by `SofascoreProvider` | Free, no key, no request cap seen in practice | Scores/fixtures fallback with no season restriction | No odds at all; needs Playwright+Chromium; GPL-3.0 dependency; scraping-via-browser-automation, not a sanctioned API — see the Sofascore section above before using it |
| **football-data.org** | 10 req/min, ~12 top competitions, no live scores, no lineups | Quick fixtures/results/standings smoke-testing without season restrictions | Scores are delayed on the free tier; no odds at all |
| **TheSportsDB** | Public free key (`123`), 30 req/min | Real fixtures/results/team data without a paid subscription | No free live scores; no betting odds; shared/rate-limited key |

The app now has normalized adapters for API-Football, football-data.org and TheSportsDB, plus optional livescoreFootball and Sofascore fallbacks. Provider selection is controlled by `FOOTBALL_PROVIDER_CHAIN` and `FOOTBALL_PROVIDER_MODE`, so additional APIs can be added behind the same interface without changing the prediction engine. TheSportsDB can supply free fixtures/form; API-Football can add odds/events/lineups when a key is available.

## Groq model

`llama-3.3-70b-versatile` (the model this project used to default to) was **decommissioned by Groq on 2026-08-16**. The default is now `openai/gpt-oss-120b`, Groq's current recommended general-purpose replacement — check `https://console.groq.com/docs/models` if you hit a model-not-found error later, since Groq's lineup changes over time.

