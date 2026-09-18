# Launch checklist — local test → live → verified

Five phases, in order. Don't skip to deployment before Phase 1 passes — every
bug that's cheap to catch locally is expensive to catch in production.

## Phase 0 — Get it running locally with real football data

This project no longer includes synthetic fixtures. The default provider chain
uses real external sources, with TheSportsDB V1 available through its documented
free key.

```bash
python -m venv venv && source venv/bin/activate   # or your preferred env tool
pip install -r requirements.txt
cp .env.example .env
```

Leave the provider routing at `FOOTBALL_PROVIDER=auto`. By default, TheSportsDB V1
provides the no-paid-key real-data path; add optional provider keys in `.env` as
needed.

**Run the test suite first:**
```bash
python -m unittest discover tests -v
```

**Run both apps:**
```bash
# Terminal 1
python -m uvicorn app.api:app --reload --port 8000

# Terminal 2
streamlit run frontend/streamlit_app.py
```

Verify `/health`, `/providers` and `/fixtures` return real-provider data. The
TheSportsDB free V1 path is not a live-score source; the `/live` endpoint needs
a live-capable provider such as API-Football or the optional livescoreFootball
service in the active chain.

## Phase 1 — Swap in real credentials, still local

Now introduce the real pieces one at a time, testing after each:

1. **Football data.** Get an API-Football key (api-sports.io, free tier =
   100 req/day). Set `FOOTBALL_PROVIDER=api-football` and `API_FOOTBALL_KEY`
   in `.env`. Restart, re-run `curl localhost:8000/fixtures?...` — confirm
   you get real provider-backed fixtures. Watch your request count; the free
   tier disappears fast if you're testing in a loop.

2. **Groq (optional).** Set `GROQ_API_KEY` if you want AI match
   explanations. Test one `/match/{id}/explain` call.

3. **A real Postgres database**, even for local testing at this point,
   since you'll need it for deployment anyway and it's better to find
   connection issues now: get a free Supabase or Neon project, set
   `DB_PATH=postgresql://...` in `.env`, restart, confirm signup/login and
   the admin board still work against Postgres instead of local SQLite.
   *(Do NOT skip this — see Phase 2, this is the single most common
   deployment failure with this app.)*

4. **Generate real secrets** — don't deploy with the placeholder values:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   Run it twice, set `AUTH_JWT_SECRET` and `RNG_SALT` in `.env` to the two
   outputs.

## Phase 2 — Deploy

Full step-by-step is in `DEPLOY_RENDER.md` — the short version:

1. Push to GitHub.
2. Render dashboard → New → Blueprint → your repo (reads `render.yaml`
   automatically) → fill in the `sync: false` env vars (your Postgres URL,
   API key, etc.) when prompted.
3. Streamlit Community Cloud (share.streamlit.io) → New app → same repo →
   `frontend/streamlit_app.py` → paste the same env vars into its Secrets
   panel (TOML format, see `DEPLOY_RENDER.md` Step 3 for the exact block).
4. Once both have real URLs, go back to Render and set
   `CORS_ALLOWED_ORIGINS` to your Streamlit Cloud URL (it starts as `*` for
   convenience, which is fine only for this initial testing window).

**Do not reuse your local `.env` secrets in production.** Generate fresh
`AUTH_JWT_SECRET`/`RNG_SALT` for the live deployment (Render's blueprint
does this for you automatically via `generateValue: true`).

## Phase 3 — Verify the live deployment, not just that it deployed

A green "Deploy succeeded" checkmark means the process started, not that it
works. Actually check:

```bash
curl https://your-app.onrender.com/health
```
Then:
- `curl https://your-app.onrender.com/fixtures?...` — real data flowing through
- `curl https://your-app.onrender.com/slips/daily` — the full engine → shortlist
  → slip pipeline works against production config
- Open the Streamlit Cloud URL in a browser, sign up a real test account,
  confirm it persists (refresh the page, sign back in — if using Postgres
  correctly, your account survives; if `DB_PATH` was accidentally left as
  local SQLite, you'll notice data vanishing after Render's free tier spins
  the service down — that's your signal something's misconfigured, not a
  mystery bug)
- Generate a daily slip through the actual UI, not just the API directly
- If you enabled `GROQ_API_KEY`, test one AI explanation end-to-end in the UI

**First request after idle will be slow** (~30-60s) on both Render and
Streamlit Cloud free tiers — that's the free-tier spin-down/wake-up, not a
bug. Don't mistake it for a broken deployment.

## Phase 4 — Ongoing / before real users touch it

- [ ] `CORS_ALLOWED_ORIGINS` is your real frontend URL, not `*`
- [ ] `AUTH_JWT_SECRET` and `RNG_SALT` are freshly generated, not copied from
      `.env.example` or your local dev `.env`
- [ ] `ADMIN_BOOTSTRAP_EMAIL`/`ADMIN_BOOTSTRAP_PASSWORD` are set once to
      create your first real admin account, then you can leave them (the
      bootstrap only runs while no admin exists yet — safe either way)
- [ ] You've watched your API-Football usage against the free 100/day cap —
      `API_FOOTBALL_ENRICH_LISTS`/`API_FOOTBALL_FETCH_DISCIPLINE` are both
      off by default specifically because they burn through this fast; only
      turn them on once you're on a paid plan or have confirmed your traffic
      is low
- [ ] `RATE_LIMIT_AUTH_PER_MINUTE`/`RATE_LIMIT_DEFAULT_PER_MINUTE` are set to
      values you've actually thought about, not just left at the defaults —
      and remember (see `DEPLOY_RENDER.md`) this in-memory limiter doesn't
      give you a hard guarantee if Render ever scales you past one instance
- [ ] Run `python -m unittest discover tests -v` one more time against the
      exact commit you're deploying, right before you deploy it

## If something breaks

Check, in this order: (1) Render/Streamlit Cloud's own logs for the actual
stack trace — don't guess, (2) `/health` to confirm the process is even up,
(3) whether `DB_PATH` is actually a `postgresql://` URL in production (the
single most common misconfiguration — see `app/db.py`'s warning in the logs
if it's not), (4) whether your API-Football quota is exhausted (check
api-sports.io's dashboard), (5) `CORS_ALLOWED_ORIGINS` if the frontend can't
reach the API from a browser (irrelevant if Streamlit is calling it
server-side, but relevant for any future browser-based client).
