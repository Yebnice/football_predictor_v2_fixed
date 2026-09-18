# Deployment Fact-Check Audit — v2.6.1

Date: 2026-09-18

## Result

The project was re-audited at the code-path level after the previous deployment review. Confirmed bugs found in the prior build were fixed and regression-tested.

Test status after fixes: **65 passed, 14 skipped, 0 failed**.
Python compile checks: **passed**.
Render Blueprint YAML parse: **passed**.
FastAPI `/health`: **200** with the real configured provider chain.
FastAPI `/providers`: **200** and reports active providers without secrets.

A true end-to-end live-data test could not be executed from this sandbox because outbound DNS/network access is blocked and Streamlit itself is not installed in this audit runtime. Provider API behavior was therefore checked against current primary documentation/current public responses where available, while local code paths were tested with mocks.

## Confirmed bugs fixed

### 1. TheSportsDB free league schedule could under-fill slips
The current free `eventsnextleague.php?id=4328` response returns only one upcoming event in the current public response. That was incompatible with the app's daily (5–10) and weekly (20) slip requirements. The provider now uses the documented `eventsseason.php` schedule for non-live windows and falls back to rolling feeds only if the season endpoint fails. TheSportsDB currently documents the season schedule endpoint and its V1 free limits; the current public league-next response was checked directly on 2026-09-18.

Sources: https://www.thesportsdb.com/documentation and the current endpoint response.

### 2. Historical form leakage
The season feed contains an entire season. The previous form calculation could use matches occurring after the fixture being predicted. This is target leakage and can artificially improve historical/backtest predictions. Form now uses only completed matches strictly before the target fixture and takes the most recent N matches.

### 3. Form cache reused the wrong date snapshot
The monthly/season window reused one team-form object across multiple fixtures for the same team. Later fixtures could therefore use an earlier form snapshot. The cache key is now `(team, fixture date)` so each target fixture receives the correct pre-match form.

### 4. Detail lookups could erase enriched form
The TheSportsDB list path calculated recent form, but `fixture_by_id()` returned the raw event and could overwrite the enriched fixture in Streamlit/API detail paths. `fixture_by_id()` now reuses the season schedule enrichment so markets and AI explanations use the same recent-form information as the list view.

### 5. Full-text TheSportsDB statuses were not normalized
TheSportsDB can expose values such as `Match Finished` as well as `FT`, `AET`, and `PEN`. The adapter now normalizes both abbreviated and full-text soccer statuses. Current TheSportsDB forum guidance confirms the soccer status vocabulary and that the provider can expose different status formats.

### 6. Structured Sofascore lineups were being dropped by the composite router
Sofascore/EasySoccerData can return a structured dictionary for lineups, while the composite router assumed an iterable list of dictionaries. The router now preserves a dict as `{"provider": ..., "data": ...}`.

### 7. Streamlit reruns were defeating provider caching
Streamlit reruns the script on UI interaction. The provider was recreated on each rerun, which recreated HTTP clients and TTL caches and could waste free API quotas. The provider is now stored with `st.cache_resource`, so the same provider/cache survives reruns. The provider TTL cache is also protected by a lock for concurrent access.

### 8. Public fixture-range abuse
`GET /fixtures?days=` had no upper bound. It now accepts 0–31 days, matching the app's daily/weekly/monthly windows and preventing unexpectedly large public queries.

### 9. Documentation mismatch on Appwrite
The README previously described Appwrite as hooks/interfaces only even though the optional SDK-based mirror sync is implemented. The README is now corrected.

## Current provider facts checked

- API-Football currently advertises a Free plan with 100 requests/day and 10 requests/minute, with endpoints including fixtures, live scores, events, lineups, odds, statistics and predictions; free access is season-limited. Source: https://www.api-football.com/pricing and current API-Football documentation.
- football-data.org currently lists a free plan with 12 competitions, delayed scores/schedules, fixtures and tables, and 10 calls/minute. Live scores are on a paid plan. Source: https://www.football-data.org/pricing and current API documentation.
- TheSportsDB currently documents V1 as free with shared key `123` and a 30 requests/minute free limit; V2 and livescores are premium. Source: https://www.thesportsdb.com/documentation
- livescoreFootball currently advertises a no-key public API focused on verified England/Spain coverage and documents the exact routes used by this adapter. Source: https://github.com/rezarahiminia/livescoreFootball
- Groq currently lists `openai/gpt-oss-120b` as an available production model. Groq also records `llama-3.3-70b-versatile` as deprecated with an August 16, 2026 shutdown date and recommends GPT-OSS 120B or Qwen 3.6 27B. Sources: https://console.groq.com/docs/models and https://console.groq.com/docs/deprecations

## Remaining deployment risks (not code bugs)

1. Live end-to-end provider verification still needs to be done from the user's deployment environment because the audit sandbox cannot reach external APIs.
2. Render Free + local SQLite remains a data-persistence risk; production deployment should use persistent Postgres.
3. The in-memory rate limiter is per process. A multi-worker/multi-instance deployment needs Redis or another shared limiter.
4. Payment verification endpoints intentionally return pending/unsupported until real server-side merchant/blockchain verification is connected.
5. The betting model has not been calibrated against a large out-of-sample historical dataset; software correctness is not the same thing as predictive accuracy.
6. The current project archive still contains only the implemented adapters visible in `app/data_providers.py` (API-Football, football-data.org, TheSportsDB, livescoreFootball, Sofascore). Earlier notes claiming Sportmonks/OpenLigaDB/openfootball had already been added are not reflected in this archive and should not be treated as implemented.

## Engineering deployment assessment

**88/100 for beta deployment readiness after this audit.**

The core code paths are stable enough for a controlled beta/public test. The remaining points are primarily operational: live provider verification from the target host, shared rate limiting for scale, real payment verification, and model validation/calibration rather than syntax/runtime defects.
