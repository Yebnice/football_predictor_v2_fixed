# Deployment Fact-Check — v2.6.3

## Verification date
2026-09-18

## Result
- Project tests: 69 passed, 14 skipped, 0 failed.
- Python compile check: passed.
- FastAPI smoke endpoints `/health` and `/providers`: HTTP 200.
- Parameter validation smoke checks: invalid `days=32`, `min_edge=-1`, and `top_n=0` return HTTP 422.
- Real upstream end-to-end API calls were not performed from the audit container because outbound DNS/network access is unavailable there.

## Confirmed fixes in this audit
1. API-Football fixture IDs are prefixed (`api-football-...`) to prevent cross-provider ID collisions.
2. API-Football historical form excludes matches on/after the target fixture date and uses a larger history window so the prior five matches can be recovered without future-result leakage.
3. API-Football list enrichment is keyed by team + target fixture date rather than one form snapshot per team.
4. Generic REST fixture IDs are provider-prefixed (`generic-...`) to preserve the same namespace rule.
5. API-Football fixture lists are locally constrained to the requested date window.
6. `APP_ENV=Production` is treated case-insensitively for production secret validation.
7. The raw ASGI path is used for rate-limit classification instead of `request.url.path`.
8. `days=0` now means the UTC calendar day, matching the endpoint documentation.
9. The current livescoreFootball public limit is documented as 1000 requests/IP/60s instead of the stale 120/min text.
10. Free-provider package retrieval can continue across configured providers until the caller's minimum fixture count is reached instead of stopping after the first under-filled source.

## Known product/data limitations (not hidden bugs)
- TheSportsDB free V1 has method-specific limits; its season schedule is limited to 15 results on the free tier. It cannot by itself guarantee the project's weekly/monthly fixture pool requirements.
- football-data.org free has delayed scores/schedules and 10 requests/minute.
- API-Football free has 100 requests/day and a 10/minute rate limit.
- livescoreFootball is a community/public service whose no-key availability and response behavior can change; it is not treated as a contractual production dependency.
- Sofascore integration is browser-based via EasySoccerData/Playwright and is intentionally optional.
- Payment verification remains incomplete until real merchant/blockchain verification is connected; the API does not auto-grant paid access from a mere pending reference.
- The model's ELO fields remain neutral unless a real ELO pipeline populates them; this is a model-quality limitation, not an application crash.

## Dependency security
The project pins:
- FastAPI 0.141.1
- Streamlit 1.64.0
- PyJWT 2.14.0

These are above the patched versions associated with the current Streamlit cache-hashing advisory and PyJWT advisories checked during this audit. Starlette is resolved transitively by the FastAPI pin and the application's rate limiter no longer relies on the affected `request.url.path` behavior.
