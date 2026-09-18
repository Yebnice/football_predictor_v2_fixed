# Deployment & Bug Audit — Football Predictor v2.6.0

**Audit date:** 2026-09-18

## Final deployment assessment

**Technical deployment readiness: 84/100**

The core application is suitable for a real-data beta deployment. It is not yet a fully hardened production payments platform or a multi-instance/high-availability system.

| Area | Score | Finding |
|---|---:|---|
| Application startup/build | 18/20 | Compile checks pass; Render start command and health check are valid. |
| Football data integration | 18/20 | Normalized multi-provider routing, free-first chain, caching, live-provider distinction and odds enrichment are implemented. |
| Tests/QA | 17/20 | 62 tests pass; 14 optional tests skip because Sofascore/Appwrite extras are not installed in the audit environment. |
| Security/auth | 16/20 | Production secret placeholders are blocked; malformed JWTs return 401; role checks are database-backed. In-memory rate limiting is not cluster-wide. |
| Deployment/operations | 15/20 | Postgres path is supported and Render/Supabase IPv4 guidance is hardened. Free hosting still has sleep/ephemeral-filesystem limits. |

## Bugs/errors corrected

### 1. Provider configuration was not consistently wired into the API
The backend could construct the provider chain without forwarding all configured football-data.org and TheSportsDB settings. This could make configured fallbacks appear enabled in configuration while the API ignored the credentials/settings.

**Fixed:** `build_provider_from_settings()` is now the single provider-construction path for both FastAPI and Streamlit, and the recursive provider builder forwards `football_data_enrich_form` correctly.

### 2. Free TheSportsDB V1 could be treated as a live-score provider
TheSportsDB documents livescores as part of its premium features; free V1 is not a valid live-score source. The old behavior could return non-live scheduled/past events when `live=True`.

**Fixed:** TheSportsDB V1 explicitly rejects live mode, allowing the composite provider to fall through to a live-capable provider.

### 3. TheSportsDB → API-Football odds enrichment was not attached to fixtures
The project already had an odds bridge, but a TheSportsDB fixture carrying an API-Football ID could still reach the prediction engine with an empty `odds` dictionary.

**Fixed:** `CompositeFootballProvider.fixture_by_id()` now performs best-effort odds enrichment when the primary fixture has no odds.

### 4. Production could start with placeholder secrets
Known placeholder values for `AUTH_JWT_SECRET` and `RNG_SALT` were previously only warnings.

**Fixed:** production startup now fails fast until both values are replaced with non-placeholder secrets.

### 5. Malformed JWTs could become server errors
A validly signed token without a usable `sub` claim could produce an internal error instead of a clean authorization failure.

**Fixed:** JWT decoding now validates the subject and returns HTTP 401 for malformed sessions.

### 6. Database migration failures could be hidden
The store previously had a fallback schema path that could conceal a real migration or connectivity problem.

**Fixed:** schema initialization now uses the versioned migration runner and fails fast on migration/connection errors.

### 7. Render + Supabase direct database endpoint could fail over IPv6
The project's earlier Render logs showed `Network is unreachable` when the Supabase direct `db.<project>.supabase.co` endpoint resolved to IPv6.

**Fixed:** the application now detects that specific Render/Supabase configuration and stops with an actionable message telling the deployer to use the Supabase shared Session pooler. This matches Supabase's current connection guidance for IPv4-only networks. 

### 8. LivescoreFootball fallback could be unusable without a configured league
The provider requires a league slug. The default configuration was blank, so it could not serve as a fallback until the user configured one.

**Fixed:** the default league is now `eng.1`, and the Render blueprint sets the same value.

### 9. Groq failures returned generic internal errors
An upstream Groq failure could propagate to the generic 500 handler.

**Fixed:** the match explanation endpoint now returns a clean 502 with an actionable provider message.

### 10. CI did not match the deployment Python line
Render was pinned to Python 3.12.x while CI used Python 3.11.

**Fixed:** CI now runs the core and optional Appwrite jobs on Python 3.12.

## Current verified test state

- `python -m compileall -q app frontend tests` — passed.
- `pytest -q` — **62 passed, 14 skipped**.
- The 14 skips are optional Sofascore/browser and Appwrite SDK tests; the CI workflow contains a separate Appwrite job that installs the optional SDK.
- Render YAML parses successfully and retains `python -m uvicorn app.api:app --host 0.0.0.0 --port $PORT`.
- FastAPI smoke checks for `/health` and `/providers` return HTTP 200 in the offline audit environment.
- A live TheSportsDB endpoint was independently verified on 2026-09-18 to return current Premier League fixture data. The local audit container itself does not have working external DNS, so the full `/fixtures` network call cannot be claimed as a container-side live test.

## Known deployment limitations

### Payments are not production payment verification yet
`/payment/usdt/verify`, `/payment/momo/verify` and `/payment/telecel/verify` are verification boundaries. They intentionally return `pending` or `unsupported` until a real server-side blockchain/merchant verification integration is configured. VVIP access should not be activated from a `pending` result.

### Free hosting is not high availability
Render's Free web services spin down after inactivity and lose local filesystem changes on spin-down/redeploy. Use external Postgres for persistent accounts/tips.

### Rate limiting is single-process
The current rate limiter is in-memory. It protects a single process but is not a shared/global limiter if the application is later scaled to multiple workers or instances.

### Sofascore is an optional scraping/browser adapter
It depends on browser automation and is not the primary sanctioned REST data source. Keep it last in the chain and optional.

### Prediction quality is separate from deployment correctness
The statistical engine is deterministic and tested for bounded/coherent probabilities, but that does not constitute proof of betting profitability or calibration on future matches. Corners/cards are still explicitly estimated when real per-match discipline data is unavailable.

## Recommended deployment order

1. Configure a persistent Postgres database.
2. On Supabase free, copy the **shared Session pooler** connection from the Connect dialog; do not manually substitute the direct `db.*.supabase.co` host for Render.
3. Deploy the Render API and verify `/health`, `/providers`, `/fixtures`, and `/slips/daily`.
4. Deploy Streamlit with the same provider settings and shared Postgres connection if a shared account/tips board is required.
5. Generate fresh production secrets and verify that no placeholder values are present.
6. Only enable additional API keys/features after confirming their current quota and coverage.
7. Treat the VVIP payment endpoints as inactive until a real verification provider has been integrated and tested end-to-end.
