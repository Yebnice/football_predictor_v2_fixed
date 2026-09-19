import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from pydantic import BaseModel

from .config import settings
from . import db as _db
from .data_providers import build_provider_from_settings
from .engine import FootballProbabilityEngine
from .corners_cards import CornersCardsEngine
from .slips import SlipGenerator
from .services.ai_groq import GroqExplainer
from .services.ai_gemini import GeminiExplainer
from .services.payments import PaymentService
from .store import Store
from .auth import AuthConfig
from .admin_board import build_admin_router, bootstrap_admin
from .appwrite_sync import AppwriteSync

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("football_predictor")

app = FastAPI(title=settings.app_name, version="2.6.3")

_cors_origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials="*" not in _cors_origins,  # browsers reject credentials+"*" anyway
    allow_methods=["*"],
    allow_headers=["*"],
)


class _InMemoryRateLimiter(BaseHTTPMiddleware):
    """Fixed-window rate limit keyed by client IP. Deliberately dependency-free
    (no Redis/slowapi) so it works in a single-process deployment out of the
    box; swap the in-memory store for a shared one before scaling to multiple
    workers/instances, since each process would otherwise count separately.

    /auth/* gets a much tighter limit (rate_limit_auth_per_minute) since that's
    the brute-forceable surface; everything else uses the default per-minute
    cap. Both are configurable via env and can be set very high to effectively
    disable this for trusted/internal deployments.
    """
    def __init__(self, app, default_per_minute: int, auth_per_minute: int):
        super().__init__(app)
        self.default_per_minute = default_per_minute
        self.auth_per_minute = auth_per_minute
        self._hits: dict[str, deque] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        raw_path = request.scope.get("path", "")
        limit = self.auth_per_minute if raw_path.startswith("/auth/") else self.default_per_minute
        if limit > 0:
            client_ip = request.client.host if request.client else "unknown"
            key = f"{client_ip}:{'auth' if request.scope.get('path', '').startswith('/auth/') else 'default'}"
            now = time.monotonic()
            window = self._hits[key]
            while window and now - window[0] > 60:
                window.popleft()
            if len(window) >= limit:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Please slow down and try again shortly."},
                )
            window.append(now)
        return await call_next(request)


app.add_middleware(
    _InMemoryRateLimiter,
    default_per_minute=settings.rate_limit_default_per_minute,
    auth_per_minute=settings.rate_limit_auth_per_minute,
)

provider = build_provider_from_settings(settings)
engine = FootballProbabilityEngine(settings.max_score_goals, rho=settings.dixon_coles_rho)
corners_cards_engine = CornersCardsEngine()
slipgen = SlipGenerator(engine, settings.min_selection_confidence, settings.rng_salt)
groq = GroqExplainer(settings.groq_api_key, settings.groq_model)
gemini = GeminiExplainer(settings.gemini_api_key, settings.gemini_model)
payments = PaymentService(settings.usdt_network, settings.usdt_receiving_address, settings.mtn_momo_enabled, settings.telecel_enabled)

_db.assert_safe_for_current_host(settings.db_path)
store = Store(settings.db_path)
auth_config = AuthConfig(jwt_secret=settings.auth_jwt_secret, jwt_expiry_hours=settings.auth_jwt_expiry_hours)
if settings.auth_jwt_secret in ["change-me-too", "change-me-to-secure-random-jwt-secret"] and settings.app_env.strip().lower() != "development":
    logger.warning("AUTH_JWT_SECRET is still the default placeholder outside development — set a real secret.")
bootstrap_admin(store, settings.admin_bootstrap_email, settings.admin_bootstrap_password)
appwrite_sync = AppwriteSync(
    endpoint=settings.appwrite_endpoint, project_id=settings.appwrite_project_id,
    api_key=settings.appwrite_api_key, database_id=settings.appwrite_database_id,
    profiles_collection_id=settings.appwrite_profiles_collection_id,
    tips_collection_id=settings.appwrite_tips_collection_id,
)
app.include_router(build_admin_router(store, auth_config, appwrite_sync))

@app.on_event("shutdown")
def _release_provider_resources():
    # SofascoreProvider holds a real browser process open; other providers
    # don't define close(), so this is a no-op for them.
    close = getattr(provider, "close", None)
    if callable(close):
        close()

class PaymentRequest(BaseModel):
    reference: str

@app.exception_handler(Exception)
def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.scope.get("path", ""))
    return JSONResponse(status_code=500, content={"detail": "Internal error. Please try again shortly."})

def _provider_fixtures(*args, **kwargs):
    """Wraps provider.fixtures so upstream provider failures (timeouts, rate
    limits, bad credentials) surface as a clean 502 instead of a bare 500.

    Also catches ValueError, which some providers raise for a *caller-fixable*
    request problem rather than a transient failure — e.g. SofascoreProvider
    rejects date ranges wider than its 14-day cap, and LivescoreFootballProvider
    requires a league slug. Previously only httpx.HTTPError/RuntimeError were
    caught here, so those ValueErrors (hit routinely by /slips/monthly's 31-day
    window on Sofascore) fell through to the generic 500 handler instead of a
    descriptive 400."""
    try:
        return provider.fixtures(*args, **kwargs)
    except (httpx.HTTPError, RuntimeError) as exc:
        logger.warning("Provider fixtures() failed: %s", exc)
        raise HTTPException(502, f"Football data provider error: {exc}")
    except ValueError as exc:
        logger.info("Provider fixtures() rejected the request: %s", exc)
        raise HTTPException(400, str(exc))

@app.get("/health")
def health():
    provider_names = getattr(provider, "provider_names", [settings.football_provider])
    return {"status": "ok", "provider": settings.football_provider, "providers": provider_names,
            "provider_mode": getattr(provider, "mode", settings.football_provider_mode),
            "groq_configured": bool(settings.groq_api_key),
            "gemini_configured": bool(settings.gemini_api_key),
            "appwrite_sync_configured": appwrite_sync.is_configured()}

@app.get("/providers")
def providers():
    """Return the active provider chain without exposing API keys or secrets."""
    names = getattr(provider, "provider_names", [settings.football_provider])
    return {
        "mode": getattr(provider, "mode", "single"),
        "active": names,
        "configured_chain": [x.strip() for x in settings.football_provider_chain.split(",") if x.strip()],
        "notes": {
            "bsd": {"requires_key": True, "live_capable": True, "summary": "BSD free football API: fixtures, live scores, xG/stats, lineups, predictions and consensus odds; 7,500 requests/day on the free tier. Per-bookmaker odds require Football Unlimited."},
            "openfootball": {"requires_key": False, "live_capable": False, "summary": "Free public-domain fixtures/results datasets; latest-season files are published by league code and used here for fixtures plus season-to-date form."},
            "api-football": {"requires_key": True, "live_capable": True, "summary": "Free plan currently 100 requests/day; richer odds/events/lineups when a key is configured."},
            "football-data": {"requires_key": True, "live_capable": False, "summary": "Free registered plan currently 10 requests/min and delayed scores/schedules."},
            "thesportsdb": {"requires_key": False, "live_capable": False, "summary": "Free V1 shared key works without a paid account; current documented limit is 30 requests/min."},
            "sofascore": {"requires_key": False, "live_capable": True, "summary": "Optional browser-based fallback; not a sanctioned REST API integration."},
            "livescorefootball": {"requires_key": False, "live_capable": True, "summary": "Optional no-key community service for selected leagues; response/availability can change."},
        },
    }

@app.get("/fixtures")
def fixtures(days: int = Query(default=1, ge=0, le=31), live: bool = False, league: int | None = None, season: int | None = None):
    """Return fixtures for a calendar-day window. ``days=0`` means today, not
    a zero-length instant; this avoids surprising empty responses when callers
    request the current day's fixtures explicitly."""
    now = datetime.now(timezone.utc)
    if days == 0:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    else:
        start = now
        end = now + timedelta(days=days)
    return [f.__dict__ for f in _provider_fixtures(start, end, live=live, league=league, season=season)]

@app.get("/match/{fixture_id}/markets")
def match_markets(fixture_id: str):
    try:
        fx = provider.fixture_by_id(fixture_id)
    except (httpx.HTTPError, RuntimeError) as exc:
        logger.warning("Provider fixture_by_id() failed for %s: %s", fixture_id, exc)
        raise HTTPException(502, f"Football data provider error: {exc}")
    if not fx:
        raise HTTPException(404, "Fixture not found")
    markets = engine.markets(fx) + corners_cards_engine.markets(fx)
    return {"fixture": fx.__dict__, "markets": [m.__dict__ for m in markets]}

@app.get("/match/{fixture_id}/value-bets")
def match_value_bets(fixture_id: str, min_edge: float = Query(default=0.05, ge=0.0, le=10.0)):
    """Markets where the model's fair price beats the bookmaker's price by at
    least `min_edge` (e.g. 0.05 = a 5% expected edge). Only 1X2 selections carry
    market_odds today, since that's the only market the providers supply prices
    for; edge is null (and excluded) for every other market."""
    try:
        fx = provider.fixture_by_id(fixture_id)
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(502, f"Football data provider error: {exc}")
    if not fx:
        raise HTTPException(404, "Fixture not found")
    markets = engine.markets(fx)
    value = [m for m in markets if m.edge is not None and m.edge >= min_edge]
    value.sort(key=lambda m: m.edge, reverse=True)
    return {"fixture": fx.__dict__, "min_edge": min_edge, "value_bets": [m.__dict__ for m in value]}

@app.get("/match/{fixture_id}/explain")
def match_explain(
    fixture_id: str,
    top_n: int = Query(default=5, ge=1, le=20),
    ai: str = Query(default="gemini", pattern="^(gemini|groq|both)$"),
):
    """Explain a model-backed match using Gemini Flash, Groq, or both."""
    try:
        fx = provider.fixture_by_id(fixture_id)
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(502, f"Football data provider error: {exc}")
    if not fx:
        raise HTTPException(404, "Fixture not found")
    shortlist = engine.shortlist(fx, settings.min_selection_confidence, top_n)
    market_payload = [m.__dict__ for m in shortlist]
    results = {}

    if ai in {"gemini", "both"}:
        if not settings.gemini_api_key:
            raise HTTPException(503, "Gemini AI is not configured. Set GEMINI_API_KEY.")
        try:
            results["gemini"] = gemini.explain(fx.__dict__, market_payload)
        except Exception as exc:
            logger.warning("Gemini explanation failed for %s: %s", fixture_id, exc)
            raise HTTPException(502, "Gemini explanation provider error. Check GEMINI_API_KEY and GEMINI_MODEL.")

    if ai in {"groq", "both"}:
        if not settings.groq_api_key:
            raise HTTPException(503, "Groq AI is not configured. Set GROQ_API_KEY.")
        try:
            results["groq"] = groq.explain(fx.__dict__, market_payload)
        except Exception as exc:
            logger.warning("Groq explanation failed for %s: %s", fixture_id, exc)
            raise HTTPException(502, "Groq explanation provider error. Check GROQ_API_KEY and GROQ_MODEL.")

    return {"fixture_id": fixture_id, "ai": ai, "explanations": results}

@app.get("/slips/daily")
def daily_slip():
    now = datetime.now(timezone.utc)
    fx = _provider_fixtures(now, now + timedelta(days=1), minimum=5)
    try:
        return slipgen.daily(fx).__dict__
    except ValueError as exc:
        raise HTTPException(400, str(exc))

@app.get("/slips/weekly")
def weekly_slips():
    now = datetime.now(timezone.utc)
    fx = _provider_fixtures(now, now + timedelta(days=7), minimum=20)
    try:
        return [s.__dict__ for s in slipgen.weekly(fx)]
    except ValueError as exc:
        raise HTTPException(400, str(exc))

@app.get("/slips/monthly")
def monthly_slips():
    now = datetime.now(timezone.utc)
    fx = _provider_fixtures(now, now + timedelta(days=31), minimum=35)
    try:
        return [s.__dict__ for s in slipgen.monthly(fx)]
    except ValueError as exc:
        raise HTTPException(400, str(exc))

@app.get("/live")
def live_matches():
    now = datetime.now(timezone.utc)
    return [f.__dict__ for f in _provider_fixtures(now - timedelta(hours=6), now + timedelta(hours=1), live=True)]

@app.get("/match/{fixture_id}/events")
def match_events(fixture_id: str):
    try:
        return provider.events(fixture_id)
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(502, f"Football data provider error: {exc}")

@app.get("/match/{fixture_id}/lineups")
def match_lineups(fixture_id: str):
    try:
        return provider.lineups(fixture_id)
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(502, f"Football data provider error: {exc}")

@app.get("/match/{fixture_id}/odds")
def match_odds(fixture_id: str):
    try:
        return provider.odds(fixture_id)
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(502, f"Football data provider error: {exc}")

@app.post("/payment/usdt/verify")
def verify_usdt(req: PaymentRequest):
    return payments.verify_usdt(req.reference).__dict__

@app.post("/payment/momo/verify")
def verify_momo(req: PaymentRequest):
    return payments.verify_momo(req.reference).__dict__

@app.post("/payment/telecel/verify")
def verify_telecel(req: PaymentRequest):
    return payments.verify_telecel(req.reference).__dict__
