# Free API setup

## Zero-cost start

Use the app's automatic provider router:

```env
FOOTBALL_PROVIDER=auto
FOOTBALL_PROVIDER_CHAIN=thesportsdb,api-football,football-data,livescorefootball,sofascore
FOOTBALL_PROVIDER_MODE=fallback
THESPORTSDB_API_KEY=123
THESPORTSDB_LEAGUE_ID=4328
```

This activates TheSportsDB V1 as the first real source when the keyed providers are not configured. The shared key `123` is documented by TheSportsDB as its free V1 key.

## Add richer data later

### API-Football

Create a free API-Football account and put its key in:

```env
API_FOOTBALL_KEY=your_key
```

The auto chain will then try API-Football after TheSportsDB. Its current free plan is 100 requests/day. Use the existing cache and keep list enrichment/discipline enrichment off until you need them, because those settings consume additional requests.

### football-data.org

Create a free token and put it in:

```env
FOOTBALL_DATA_API_KEY=your_token
FOOTBALL_DATA_COMPETITION=PL
```

The current free plan is 10 calls/min and has delayed scores/schedules. It becomes the next fallback automatically when configured.

## Adding another provider

Implement the existing `FootballProvider` interface in `app/data_providers.py` (or a separate provider module), normalize its data into `Fixture`, register a short provider name in `build_provider()`, and add that name to `FOOTBALL_PROVIDER_CHAIN`. The rest of the application can remain unchanged.

## Provider mode

`fallback` is recommended for free quotas: the router stops at the first provider that returns useful data. `merge` queries every configured provider and de-duplicates the same fixture by date/competition/home/away, preserving the earlier provider's record when sources overlap.

## API diagnostics

The backend exposes:

```text
GET /health
GET /providers
```

`/providers` reports the active chain and non-secret notes; it never returns API keys.
