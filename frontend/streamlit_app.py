from datetime import datetime, timedelta, timezone
import html
import json
import sys
import textwrap
from pathlib import Path

# Streamlit Cloud executes a script inside the frontend/ directory, so the
# repository root is not guaranteed to be on sys.path. Add it explicitly so
# imports such as `from app.config import settings` work in cloud deployment.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from app.config import settings
from app.leagues import MAJOR_LEAGUES
from app.data_providers import build_provider_from_settings
from app.engine import FootballProbabilityEngine
from app.schemas import TeamForm
from app.corners_cards import CornersCardsEngine
from app.slips import SlipGenerator
from app.services.ai_groq import GroqExplainer
from app.services.ai_gemini import GeminiExplainer
from app.store import Store
from app.auth import AuthConfig, hash_password, verify_password
from app.admin_board import bootstrap_admin, serialize_tip


def _streamlit_secret(name: str, fallback: str = "") -> str:
    """Read a Streamlit Cloud secret, supporting flat or nested TOML forms."""
    try:
        secrets = st.secrets
        value = secrets.get(name) or secrets.get(name.lower())
        if value in (None, ""):
            section_map = {
                "GROQ_API_KEY": ("groq", "api_key"),
                "GEMINI_API_KEY": ("gemini", "api_key"),
                "API_FOOTBALL_KEY": ("api_football", "api_key"),
                "FOOTBALL_DATA_API_KEY": ("football_data", "api_key"),
                "BSD_API_KEY": ("bsd", "api_key"),
                "DB_PATH": ("database", "url"),
                "DATABASE_URL": ("database", "url"),
            }
            section_name, field_name = section_map.get(name.upper(), (None, None))
            if section_name:
                section = secrets.get(section_name)
                if section is not None:
                    try:
                        value = section.get(field_name) or section.get(name)
                    except AttributeError:
                        pass
        if value in (None, ""):
            value = fallback
    except Exception:
        value = fallback
    return str(value or "").strip()


# Streamlit Cloud secrets are the authoritative runtime source for AI config.
# This intentionally happens before the status panel and GroqExplainer are
# created, so the UI and actual API client always use the same credentials.
# Runtime secrets: Streamlit Cloud is the source of truth for deployed
# credentials. This keeps the setup simple: add the keys once in Manage app →
# Settings → Secrets, reboot, and the same credentials are used by both the
# data providers and Groq.
api_football_key = _streamlit_secret(
    "API_FOOTBALL_KEY",
    getattr(settings, "api_football_key", "") or getattr(settings, "football_api_key", ""),
)
football_data_key = _streamlit_secret(
    "FOOTBALL_DATA_API_KEY",
    getattr(settings, "football_data_api_key", ""),
)
bigballsdata_api_key = _streamlit_secret("BIGBALLSDATA_API_KEY", getattr(settings, "bigballsdata_api_key", ""))
bsd_api_key = _streamlit_secret("BSD_API_KEY", getattr(settings, "bsd_api_key", ""))
provider_name_secret = _streamlit_secret("FOOTBALL_PROVIDER", getattr(settings, "football_provider", "auto"))
provider_chain_secret = _streamlit_secret(
    "FOOTBALL_PROVIDER_CHAIN",
    getattr(settings, "football_provider_chain", ""),
)
allsportsapi_key = _streamlit_secret("ALLSPORTSAPI_API_KEY", getattr(settings, "allsportsapi_key", ""))
isports_api_key = _streamlit_secret("ISPORTS_API_KEY", getattr(settings, "isports_api_key", ""))
groq_api_key = _streamlit_secret("GROQ_API_KEY", getattr(settings, "groq_api_key", ""))
groq_model = _streamlit_secret("GROQ_MODEL", getattr(settings, "groq_model", "openai/gpt-oss-120b"))
gemini_api_key = _streamlit_secret("GEMINI_API_KEY", getattr(settings, "gemini_api_key", ""))
gemini_model = _streamlit_secret("GEMINI_MODEL", getattr(settings, "gemini_model", "gemini-3.8-flash"))
database_url = (
    _streamlit_secret("DATABASE_URL", "")
    or _streamlit_secret("DB_PATH", "")
)

# Pydantic settings are initialized before Streamlit secrets are available to
# this deployment path. Mirror the runtime secrets into the shared settings
# object before the cached provider is built.
if api_football_key:
    settings.api_football_key = api_football_key
    settings.football_api_key = api_football_key
if football_data_key:
    settings.football_data_api_key = football_data_key
if bigballsdata_api_key:
    settings.bigballsdata_api_key = bigballsdata_api_key
if bsd_api_key:
    settings.bsd_api_key = bsd_api_key
if provider_name_secret:
    settings.football_provider = provider_name_secret
if provider_chain_secret:
    settings.football_provider_chain = provider_chain_secret
if allsportsapi_key:
    settings.allsportsapi_api_key = allsportsapi_key
if isports_api_key:
    settings.isports_api_key = isports_api_key
if database_url:
    settings.db_path = database_url
# Do not mutate the Pydantic Settings model with dynamically-added fields.
# Streamlit Cloud can briefly run a mixed cached module set during a deploy;
# runtime AI credentials are therefore kept in plain local variables instead.



_RAW_MARKDOWN = st.markdown


def render_markdown(body, **kwargs):
    """Render Markdown/HTML blocks without treating Python indentation as a code block."""
    cleaned = "\n".join(line.lstrip() for line in str(body).splitlines())
    return _RAW_MARKDOWN(cleaned.strip("\n"), **kwargs)

def esc(value) -> str:
    """Escape a value before interpolating it into an unsafe_allow_html
    render_markdown() block. Provider team/league names, admin-authored tip text,
    and Groq's generated explanation are all attacker-influenceable strings
    that were previously inserted into raw HTML with no escaping — this closes
    that XSS path without touching the templates' own static markup/CSS."""
    return html.escape(str(value), quote=True)


# Modern UI Configuration
st.set_page_config(
    page_title=settings.app_name,
    layout="wide",
    page_icon="⚽",
    initial_sidebar_state="expanded"
)

# Custom CSS for a warm, calm, Claude-inspired look — flat cream surfaces,
# a single terracotta accent used sparingly for primary actions and
# high-confidence states, soft hairline borders instead of heavy drop
# shadows, and grouped, plainly-labeled sidebar sections.
render_markdown("""
<style>
    /* Main theme colors and typography */
    :root {
        --primary-color: #D97757;
        --secondary-color: #BD5B3A;
        --accent-color: #D97757;
        --success-color: #3D8B5F;
        --warning-color: #C17F2E;
        --danger-color: #C1503D;
        --background-dark: #F5F4ED;
        --background-card: #FFFFFF;
        --background-card-alt: #F0EEE5;
        --text-primary: #1F1E1D;
        --text-secondary: #6B6862;
        --border-color: #E5E2D6;
    }

    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
    }

    /* Global styles */
    .stApp {
        background: var(--background-dark);
    }

    /* Custom card styling */
    .prediction-card {
        background: var(--background-card);
        border: 1px solid var(--border-color);
        border-radius: 14px;
        padding: 1.5rem;
        margin: 1rem 0;
        box-shadow: 0 1px 2px rgba(31, 30, 29, 0.04);
        transition: border-color 0.2s, box-shadow 0.2s;
    }

    .prediction-card:hover {
        border-color: var(--accent-color);
        box-shadow: 0 2px 8px rgba(31, 30, 29, 0.06);
    }

    /* Progress bar styling */
    .probability-bar {
        height: 8px;
        border-radius: 4px;
        background: linear-gradient(90deg, var(--primary-color), var(--secondary-color));
        transition: width 0.3s ease;
    }

    /* Team logo placeholder */
    .team-logo {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        background: var(--primary-color);
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: bold;
        color: white;
    }

    /* Status badges */
    .status-badge {
        padding: 0.25rem 0.75rem;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 600;
    }

    .status-high { background: var(--success-color); color: white; }
    .status-medium { background: var(--warning-color); color: white; }
    .status-low { background: var(--danger-color); color: white; }

    /* Animated counter */
    @keyframes countUp {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }

    .animated-value {
        animation: countUp 0.3s ease-out;
    }

    /* Mobile responsiveness */
    @media (max-width: 768px) {
        .prediction-card {
            padding: 1rem;
            margin: 0.5rem 0;
        }
    }

    /* Custom button styling */
    .stButton > button {
        background: linear-gradient(135deg, var(--primary-color), var(--secondary-color));
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.5rem 1.5rem;
        font-weight: 600;
        transition: all 0.2s;
    }

    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(217, 119, 87, 0.35);
    }

    /* Custom selectbox styling */
    .stSelectbox > div > div {
        background: var(--background-card);
        border: 1px solid var(--border-color);
        border-radius: 8px;
    }

    /* Data table styling */
    .stDataFrame {
        background: var(--background-card);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        overflow: hidden;
    }

    /* Sidebar styling — stable data-testid selector, not a hashed class
       name (those change on every Streamlit release and stop matching). */
    [data-testid="stSidebar"] {
        background: var(--background-card-alt);
        border-right: 1px solid var(--border-color);
    }

    /* Headers */
    h1, h2, h3 {
        color: var(--text-primary);
        font-weight: 600;
    }

    /* Captions and text */
    .stCaption {
        color: var(--text-secondary);
    }

    /* Small sentence-case section labels used in the sidebar/settings
       groups, in place of ALL-CAPS eyebrow labels. */
    .settings-group-label {
        color: var(--text-secondary);
        font-size: 0.8rem;
        font-weight: 500;
        margin: 1.25rem 0 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

# Initialize components
# Streamlit reruns this script on widget interactions. Cache the provider as a
# resource so HTTP clients and provider TTL caches survive reruns; otherwise a
# simple click could recreate the provider and burn through free API quotas.
@st.cache_resource(show_spinner=False)
def _get_cached_provider():
    return build_provider_from_settings(settings)

provider = _get_cached_provider()

def _football_season_for(dt: datetime) -> int:
    """Return the football season's starting year for API-Football requests."""
    return dt.year if dt.month >= 7 else dt.year - 1


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_all_leagues_with_majors(start_dt, end_dt, season, minimum, priority_ids=()):
    """Search the broad provider universe, then backfill core major leagues.

    The public selector is no longer a hard league filter. The application
    searches all leagues available from the configured providers and then
    explicitly backfills the core European competitions when a broad feed
    does not contain them.
    """
    core_major_ids = ("39", "140", "78", "135", "61", "144", "88", "94")
    requested_priority = [str(x).strip() for x in priority_ids if str(x).strip()]
    major_ids = list(dict.fromkeys([*core_major_ids, *requested_priority]))

    def _provider_fetch(league=None):
        if hasattr(_provider_local := provider, "providers"):
            return _provider_local.fixtures(
                start_dt,
                end_dt,
                league=league,
                season=season,
                minimum=minimum if league is None else 0,
            )
        return provider.fixtures(
            start_dt,
            end_dt,
            league=league,
            season=season,
        )

    rows = list(_provider_fetch(None) or [])

    def _league_text(fx):
        return " ".join(str(getattr(fx, "league", "") or "").casefold().replace("-", " ").split())

    major_aliases = {
        "39": ("premier league",),
        "140": ("laliga", "la liga"),
        "78": ("bundesliga",),
        "135": ("serie a",),
        "61": ("ligue 1",),
        "144": ("jupiler", "jupiler pro league"),
        "88": ("eredivisie",),
        "94": ("primeira liga",),
    }

    # Fast-path the European core through OpenFootball. Its provider supports
    # multiple league codes in a single fixtures() call, avoiding a fallback
    # cascade once per league.
    composite_providers = getattr(provider, "providers", [])
    openfootball = next(
        (p for name, p in composite_providers if name in {"openfootball", "open-football", "football-json"}),
        None,
    )
    if openfootball is not None:
        openfootball_codes = "en.1,es.1,de.1,it.1,fr.1,nl.1,pt.1"
        try:
            rows.extend(
                list(
                    openfootball.fixtures(
                        start_dt,
                        end_dt,
                        league=openfootball_codes,
                        season=season,
                    )
                    or []
                )
            )
        except Exception:
            pass

    # Belgium is not part of the OpenFootball mapping used by this app, so
    # query BSD directly using its resolved API-Football -> BSD mapping.
    bsd = next(
        (p for name, p in composite_providers if name in {"bsd", "bzzoiro", "bzzoiro-sports-data"}),
        None,
    )
    if bsd is not None:
        try:
            rows.extend(
                list(
                    bsd.fixtures(
                        start_dt,
                        end_dt,
                        league="144",
                        season=season,
                    )
                    or []
                )
            )
        except Exception:
            pass


    # Preserve the user's chosen leagues as additional priorities, without
    # excluding any other competitions from the broad search.
    for league_id in requested_priority:
        if league_id in core_major_ids:
            continue
        try:
            rows.extend(list(_provider_fetch(league_id) or []))
        except Exception:
            continue

    seen = set()
    merged = []
    for fx in rows:
        try:
            key = (
                fx.date.astimezone(timezone.utc).isoformat() if fx.date.tzinfo else fx.date.isoformat(),
                str(fx.home_team).strip().casefold(),
                str(fx.away_team).strip().casefold(),
                str(fx.league).strip().casefold(),
            )
        except Exception:
            continue
        if key in seen:
            continue
        seen.add(key)
        merged.append(fx)

    return [
        fx for fx in merged
        if start_dt <= fx.date <= end_dt
        and str(getattr(fx, "home_team", "") or "").strip().casefold() not in {"", "unknown"}
        and str(getattr(fx, "away_team", "") or "").strip().casefold() not in {"", "unknown"}
    ]


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_package_fixtures_cached(
    pool_start_iso: str,
    pool_end_iso: str,
    required_count: int,
    selected_league_ids: tuple[str, ...],
    season: int,
    _provider,
):
    pool_start = datetime.fromisoformat(pool_start_iso)
    pool_end = datetime.fromisoformat(pool_end_iso)
    raw_target = {5: 20, 20: 60, 35: 120}.get(required_count, required_count)
    rows = _fetch_all_leagues_with_majors(
        pool_start,
        pool_end,
        season,
        raw_target,
        selected_league_ids,
    )
    return rows
def _enrich_bigballs_forms(fixtures, selected_league_ids):
    """Inject real season-to-date team form when Big Balls supplied the fixtures."""
    provider_list = getattr(provider, "providers", [])
    bigballs = next(
        (p for name, p in provider_list if name in {"bigballsdata", "big-balls-data", "bigballs"}),
        None,
    )
    if bigballs is None or not fixtures:
        return fixtures

    league_map = {
        "39": "epl",
        "140": "laliga",
        "78": "bundesliga",
        "135": "serie-a",
        "61": "ligue-1",
        "94": "primeira-liga",
        "253": "mls",
        "71": "brazilian-serie-a",
    }
    slugs = list(dict.fromkeys(league_map.get(str(x), str(x)) for x in selected_league_ids))
    for slug in slugs:
        try:
            payload = bigballs._get("standings", {"sport": "football", "league": slug})
            tables = ((payload.get("data") or {}).get("standings") or [])
            rows = {}
            for table in tables:
                if not isinstance(table, dict):
                    continue
                for row in table.get("rows") or []:
                    if not isinstance(row, dict):
                        continue
                    name = str(row.get("team_name") or "").strip().casefold()
                    played = int(row.get("games_played") or 0)
                    if name and played:
                        rows[name] = TeamForm(
                            matches=played,
                            wins=int(row.get("wins") or 0),
                            draws=int(row.get("ties") or 0),
                            losses=int(row.get("losses") or 0),
                            goals_for=float(row.get("points_for") or 0),
                            goals_against=float(row.get("points_against") or 0),
                        )
            for fx in fixtures:
                hf = rows.get(fx.home_team.casefold())
                af = rows.get(fx.away_team.casefold())
                if hf:
                    fx.home_form = hf
                if af:
                    fx.away_form = af
        except Exception:
            continue
    return fixtures


def fetch_slip_fixtures(start, end, period):
    """Fetch all available leagues and backfill the core major competitions."""
    targets = {
        "Daily": 75,
        "Weekly": 150,
        "Monthly": 300,
    }
    target = targets.get(period)
    if target is None:
        return []
    pool_start = start.astimezone(timezone.utc)
    pool_end = end.astimezone(timezone.utc)
    season = _football_season_for(pool_start)
    # Slip packages are intentionally independent of the sidebar league
    # selection: broad league discovery is required, with core majors included.
    return _fetch_all_leagues_with_majors(
        pool_start,
        pool_end,
        season,
        target,
        (),
    )


def fetch_package_fixtures(start, end, required_count, selected_league_ids):
    # Cache the complete 31-day pool for five minutes so changing unrelated
    # widgets does not repeat dozens of provider calls and consume quota.
    pool_start = start.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    pool_end = pool_start + timedelta(days=31, hours=23, minutes=59, seconds=59)
    rows = _fetch_package_fixtures_cached(
        pool_start.isoformat(),
        pool_end.isoformat(),
        required_count,
        tuple(selected_league_ids),
        _football_season_for(pool_start),
        provider,
    )
    rows = _enrich_bigballs_forms(rows, selected_league_ids)
    return [fx for fx in rows if start <= fx.date <= end]
engine = FootballProbabilityEngine(settings.max_score_goals, rho=settings.dixon_coles_rho)
corners_cards_engine = CornersCardsEngine()
slips = SlipGenerator(engine, settings.min_selection_confidence, settings.rng_salt)
explainer = GroqExplainer(groq_api_key, groq_model)
gemini_explainer = GeminiExplainer(gemini_api_key, gemini_model)

# Modern Header
render_markdown("""
<div style="text-align: center; padding: 2rem 0;">
    <h1 style="font-size: 2.5rem; margin-bottom: 0.5rem;">⚽ Global AI Football Predictor</h1>
    <p style="color: var(--text-secondary); font-size: 1.1rem;">
        Probability-first football analytics • Multi-market predictions • AI-powered insights
    </p>
</div>
""", unsafe_allow_html=True)

# Sidebar with modern styling
with st.sidebar:
    render_markdown(f"""
    <div style="display: flex; align-items: center; gap: 0.6rem; padding: 0.25rem 0 1.25rem 0;">
        <div style="width: 32px; height: 32px; border-radius: 9px; background: var(--accent-color); display: flex; align-items: center; justify-content: center; font-size: 1rem;">⚽</div>
        <div style="font-weight: 600; color: var(--text-primary); font-size: 1.05rem;">{esc(settings.app_name)}</div>
    </div>
    """, unsafe_allow_html=True)

    render_markdown('<div class="settings-group-label">Prediction window</div>', unsafe_allow_html=True)
    pkg = st.selectbox(
        "Select Time Window",
        ["Daily", "Weekly", "Monthly", "Live"],
        label_visibility="collapsed",
        key="prediction_package"
    )
    league_options = [f"{league_id} — {name}" for league_id, name in MAJOR_LEAGUES.items()]
    api_football_leagues = getattr(settings, "api_football_leagues", "39,140,78,135") or "39,140,78,135"
    default_active_ids = [x.strip() for x in api_football_leagues.split(",") if x.strip()]
    default_active_labels = [label for label in league_options if label.split(" — ", 1)[0] in default_active_ids]
    selected_league_labels = st.multiselect(
        "Priority leagues (optional)",
        league_options,
        default=default_active_labels,
        help="The app searches all leagues available from the configured providers. These selections are additional priorities; they do not exclude other leagues. Core major leagues are always backfilled when fixtures are available.",
    )
    selected_league_ids = [label.split(" — ", 1)[0] for label in selected_league_labels]

    st.caption("🌍 All-league search is active. Core majors are explicitly included when available.")

    render_markdown('<div class="settings-group-label">Status</div>', unsafe_allow_html=True)
    active_provider_names = getattr(provider, "provider_names", [settings.football_provider])
    provider_ok = bool(active_provider_names)
    provider_status = ", ".join(active_provider_names) if active_provider_names else "Unavailable"
    data_ok = bool(api_football_key)
    data_status = "Configured" if data_ok else "Key missing"
    groq_ok = bool(groq_api_key)
    groq_status = "Configured" if groq_ok else "Key missing"
    gemini_ok = bool(gemini_api_key)
    gemini_status = "Configured" if gemini_ok else "Key missing"
    db_ok = bool(database_url)
    db_status = "Persistent DB configured" if db_ok else "Local DB (may reset)"

    def _status_row(label: str, value: str, ok: bool) -> str:
        dot_color = "var(--success-color)" if ok else "var(--text-secondary)"
        return f"""
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.35rem 0;">
            <span style="color: var(--text-secondary); font-size: 0.9rem;">{esc(label)}</span>
            <span style="display: flex; align-items: center; gap: 0.4rem; color: var(--text-primary); font-weight: 500; font-size: 0.9rem;">
                <span style="width: 6px; height: 6px; border-radius: 50%; background: {dot_color};"></span>
                {esc(value)}
            </span>
        </div>"""

    render_markdown(f"""
    <div style="background: var(--background-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 0.5rem 0.85rem;">
        {_status_row("Data provider", f"{settings.football_provider} · {provider_status}", provider_ok)}
        {_status_row("iSports API", "Configured" if bool(isports_api_key) else "Key missing", bool(isports_api_key))}
        {_status_row("AllSportsAPI", "Configured" if bool(allsportsapi_key) else "Key missing", bool(allsportsapi_key))}
        {_status_row("Big Balls Data", "Configured" if bool(bigballsdata_api_key) else "Key missing", bool(bigballsdata_api_key))}
        {_status_row("BSD Football Data", "Configured" if bool(bsd_api_key) else "Key missing", bool(bsd_api_key))}
        {_status_row("football-data.org", "Configured" if bool(football_data_key) else "Key missing", bool(football_data_key))}
        {_status_row("API-Football", data_status, data_ok)}
        {_status_row("API-Football season", str(_football_season_for(datetime.now(timezone.utc))), True)}
        {_status_row("Groq AI", groq_status, groq_ok)}
        {_status_row("Gemini Flash", gemini_status, gemini_ok)}
        {_status_row("Database", db_status, db_ok)}
    </div>
    """, unsafe_allow_html=True)

    render_markdown('<div class="settings-group-label">Security</div>', unsafe_allow_html=True)
    render_markdown("""
    <div style="background: var(--background-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 0.85rem; font-size: 0.85rem; color: var(--text-secondary); line-height: 1.5;">
        VIP, Appwrite, USDT, MTN MoMo and Telecel connectors are backend integration boundaries. Secrets are never exposed in the browser.
    </div>
    """, unsafe_allow_html=True)



# Calculate date range
now = datetime.now(timezone.utc)
if pkg == "Daily":
    start, end = now, now + timedelta(days=1)
    time_range = "Next 24 Hours"
elif pkg == "Weekly":
    start, end = now, now + timedelta(days=7)
    time_range = "Next 7 Days"
elif pkg == "Monthly":
    start, end = now, now + timedelta(days=31)
    time_range = "Next 31 Days"
else:
    start, end = now, now + timedelta(days=1)
    time_range = "Live Matches"

# Fetch fixtures
try:
    initial_required = {"Daily": 10, "Weekly": 40, "Monthly": 70}.get(pkg, 0)
    fixtures = (
        fetch_package_fixtures(start, end, initial_required, selected_league_ids)
        if initial_required
        else provider.fixtures(
            start,
            end,
            live=(pkg == "Live"),
            league=",".join(selected_league_ids) if selected_league_ids else None,
            season=_football_season_for(start),
        )
    )
except Exception as e:
    st.error(f"Failed to fetch fixtures: {str(e)}")
    fixtures = []

# Modern fixtures header
render_markdown(f"""
<div style="display: flex; justify-content: space-between; align-items: center; margin: 2rem 0 1rem 0;">
    <div>
        <h2 style="margin: 0;">📅 {pkg} Predictions</h2>
        <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0;">{time_range} • {len(fixtures)} fixtures available</p>
    </div>
</div>
""", unsafe_allow_html=True)

if not fixtures:
    render_markdown("""
    <div style="text-align: center; padding: 3rem; background: var(--background-card); border-radius: 12px; border: 1px dashed var(--border-color);">
        <div style="font-size: 3rem; margin-bottom: 1rem;">📭</div>
        <h3 style="color: var(--text-secondary);">No Fixtures Available</h3>
        <p style="color: var(--text-secondary);">Try adjusting the time window or check your data provider configuration.</p>
    </div>
    """, unsafe_allow_html=True)
else:
    # Modern card-based fixture display
    render_markdown('<div class="fixtures-grid">', unsafe_allow_html=True)

    max_cards = min(50, len(fixtures))
    show_cards = st.slider(
        "Matches shown",
        min_value=min(10, max_cards),
        max_value=max_cards,
        value=min(20, max_cards),
        step=5 if max_cards >= 15 else 1,
        help="Shows more of the match pool without requesting additional data from the providers."
    ) if max_cards > 10 else max_cards

    # BSD provides real total-corners consensus markets. Enrich only the cards
    # actually displayed, and only for BSD-origin fixtures, so hidden monthly
    # fixtures do not create a large odds-request fan-out.
    for fx in fixtures[:show_cards]:
        if not str(fx.fixture_id).startswith("bsd-"):
            continue
        if any(str(k).startswith("corner_over_") for k in (fx.odds or {})):
            continue
        try:
            detailed = provider.fixture_by_id(fx.fixture_id)
            if detailed:
                fx.odds = detailed.odds or fx.odds
                fx.home_form = detailed.home_form
                fx.away_form = detailed.away_form
                fx.home_xg = detailed.home_xg if detailed.home_xg is not None else fx.home_xg
                fx.away_xg = detailed.away_xg if detailed.away_xg is not None else fx.away_xg
        except Exception:
            pass

    for i, fx in enumerate(fixtures[:show_cards]):
        # Keep the publishable "tip" shortlist separate from the full outcome
        # probabilities. A high-probability outcome can be valid model output
        # even when it is intentionally excluded from the tip band (>75%).
        best = engine.shortlist(fx, settings.min_selection_confidence, 3)
        all_markets = engine.markets(fx)
        outcome_markets = {
            m.selection: m for m in all_markets if m.market == "1X2"
        }
        double_chance = {
            m.selection: m for m in all_markets if m.market == "Double Chance"
        }

        corner_markets = corners_cards_engine.markets(fx)
        total_corner_markets = [
            m for m in corner_markets
            if m.market == "Total Corners"
        ]

        primary = best[0] if best else (outcome_markets.get("Home Win") or outcome_markets.get("Draw") or outcome_markets.get("Away Win"))
        primary_probability = primary.probability if primary else 0.0

        # Determine confidence level without hiding the fixture when no
        # publishable shortlist item exists.
        if primary_probability >= 0.75:
            confidence_class = "status-high"
            confidence_label = "HIGH"
        elif primary_probability >= 0.65:
            confidence_class = "status-medium"
            confidence_label = "MEDIUM"
        else:
            confidence_class = "status-low"
            confidence_label = "LOW"

        def _outcome_card(label: str) -> str:
            item = outcome_markets.get(label)
            probability = f"{item.probability:.1%}" if item else "—"
            return (
                '<div style="flex:1;text-align:center;padding:0.65rem 0.4rem;'
                'background:var(--background-card-alt);border-radius:8px;">'
                f'<div style="color:var(--text-secondary);font-size:0.78rem;">{esc(label)}</div>'
                f'<div style="color:var(--text-primary);font-size:1.05rem;font-weight:700;">{probability}</div>'
                '</div>'
            )

        outcome_html = "".join(
            _outcome_card(label)
            for label in ["Home Win", "Draw", "Away Win"]
        )

        double_chance_html = "".join(
            f'<div style="flex:1;text-align:center;padding:0.55rem 0.4rem;border:1px solid var(--border-color);border-radius:8px;">'
            f'<div style="color:var(--text-secondary);font-size:0.75rem;">{esc(label)}</div>'
            f'<div style="color:var(--text-primary);font-weight:700;">{double_chance[label].probability:.1%}</div>'
            f'</div>'
            for label in ["1X", "X2", "12"] if label in double_chance
        )

        has_real_corner_market = any(
            not bool(item.metadata.get("estimated", True))
            for item in total_corner_markets
        )
        corner_source_label = (
            "Corner probabilities — BSD consensus (market-implied)"
            if has_real_corner_market
            else "Corner probabilities — model estimates"
        )
        corner_html = "".join(
            f'<div style="display:flex;justify-content:space-between;margin:0.3rem 0;">'
            f'<span style="color:var(--text-secondary);font-size:0.86rem;">{esc(item.selection)}</span>'
            f'<span style="color:var(--text-primary);font-weight:700;">'
            f'{item.probability:.1%}'
            f'{f" · odds {item.market_odds:.2f}" if item.market_odds else ""}'
            f'</span>'
            f'</div>'
            for item in total_corner_markets
        )

        top_html = (
            "".join(
                f'<div style="display:flex;justify-content:space-between;margin:0.3rem 0;">'
                f'<span style="color:var(--text-secondary);font-size:0.86rem;">{esc(item.market)} — {esc(item.selection)}</span>'
                f'<span style="color:var(--text-primary);font-weight:700;">{item.probability:.1%}</span>'
                f'</div>'
                for item in best
            )
            if best else
            '<div style="color:var(--text-secondary);font-size:0.85rem;">No selection currently meets the configured tip threshold. Full model probabilities remain available above.</div>'
        )

        fair_odds_text = f"{primary.fair_odds:.2f}" if primary and primary.fair_odds else "—"

        render_markdown(f"""
        <div class="prediction-card">
            <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 1rem;">
                <div>
                    <h3 style="margin: 0; font-size: 1.25rem;">{esc(fx.home_team)} vs {esc(fx.away_team)}</h3>
                    <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0; font-size: 0.9rem;">{esc(fx.league)}</p>
                </div>
                <span class="status-badge {confidence_class}">{confidence_label}</span>
            </div>

            <div style="margin-bottom: 1rem;">
                <div style="margin-bottom: 0.5rem; color: var(--text-secondary); font-size: 0.8rem; font-weight: 600;">Match outcome probabilities</div>
                <div style="display:flex;gap:0.5rem;">{outcome_html}</div>
                <div style="display:flex;gap:0.5rem;margin-top:0.5rem;">{double_chance_html}</div>
            </div>

            <div style="margin-bottom: 1rem;">
                <div style="margin-bottom: 0.5rem; color: var(--text-secondary); font-size: 0.8rem; font-weight: 600;">{corner_source_label}</div>
                {corner_html}
            </div>

            <div style="margin-bottom: 1rem;">
                <div style="margin-bottom: 0.5rem; color: var(--text-secondary); font-size: 0.8rem; font-weight: 600;">Top publishable markets</div>
                {top_html}
            </div>

            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <span style="color: var(--text-secondary); font-size: 0.85rem;">Primary fair odds:</span>
                    <span style="color: var(--text-primary); font-weight: 600; margin-left: 0.5rem;">{fair_odds_text}</span>
                </div>
                <div style="font-size: 0.85rem; color: var(--text-secondary);">
                    {fx.date.strftime('%Y-%m-%d %H:%M')} UTC
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    render_markdown('</div>', unsafe_allow_html=True)

    # Match-data overview: derived only from the already-fetched fixture pool,
    # so this adds useful information without spending more API quota.
    overview_rows = []
    for fx in fixtures:
        best_market = engine.shortlist(fx, settings.min_selection_confidence, 1)
        row = {
            "Kick-off (UTC)": fx.date.strftime("%Y-%m-%d %H:%M"),
            "League": fx.league,
            "Match": f"{fx.home_team} vs {fx.away_team}",
            "Home Form": f"{fx.home_form.wins}W-{fx.home_form.draws}D-{fx.home_form.losses}L",
            "Away Form": f"{fx.away_form.wins}W-{fx.away_form.draws}D-{fx.away_form.losses}L",
            "Home GPG": f"{fx.home_form.goals_for_per_game:.2f}",
            "Away GPG": f"{fx.away_form.goals_for_per_game:.2f}",
            "Top Model Market": f"{best_market[0].market}: {best_market[0].selection}" if best_market else "—",
            "Probability": f"{best_market[0].probability:.1%}" if best_market else "—",
        }
        overview_rows.append(row)

    if overview_rows:
        render_markdown("""
        <div style="background: var(--background-card); border-radius: 12px; padding: 1.25rem; margin: 1rem 0; border: 1px solid var(--border-color);">
            <h3 style="margin: 0 0 0.5rem 0;">📊 Match Data Overview</h3>
            <p style="color: var(--text-secondary); margin: 0;">Form, scoring rates and model markets from the current fixture pool. No extra provider calls are made for this table.</p>
        </div>
        """, unsafe_allow_html=True)
        st.dataframe(pd.DataFrame(overview_rows), use_container_width=True, hide_index=True)

    # Goals markets: show total-match Over/Under probabilities.
    render_markdown("---")
    render_markdown("""
    <div style="margin: 2rem 0 1rem 0;">
        <h2 style="margin: 0;">⚽ Goals Over / Under</h2>
        <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0;">
            Model probabilities for total match goals at the 1.5, 2.5 and 3.5 lines.
        </p>
    </div>
    """, unsafe_allow_html=True)

    goals_rows = []
    for fx in fixtures:
        total_goals = [m for m in engine.markets(fx)
                       if m.market == "Total Goals" and m.selection in
                       {"Over 1.5", "Under 1.5", "Over 2.5", "Under 2.5", "Over 3.5", "Under 3.5"}]
        by_selection = {m.selection: m for m in total_goals}
        if len(by_selection) == 6:
            goals_rows.append({
                "Match": f"{fx.home_team} vs {fx.away_team}",
                "Over 1.5": f"{by_selection['Over 1.5'].probability:.1%}",
                "Under 1.5": f"{by_selection['Under 1.5'].probability:.1%}",
                "Over 2.5": f"{by_selection['Over 2.5'].probability:.1%}",
                "Under 2.5": f"{by_selection['Under 2.5'].probability:.1%}",
                "Over 3.5": f"{by_selection['Over 3.5'].probability:.1%}",
                "Under 3.5": f"{by_selection['Under 3.5'].probability:.1%}",
            })

    if goals_rows:
        st.dataframe(pd.DataFrame(goals_rows), use_container_width=True, hide_index=True)
    # Generate package button with modern styling
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🎯 Generate Prediction Package", type="primary", use_container_width=True):
            try:
                with st.spinner("Generating predictions..."):
                    if pkg in {"Daily", "Weekly", "Monthly"}:
                        package_fixtures = fetch_slip_fixtures(start, end, pkg)
                    else:
                        package_fixtures = []

                    if pkg == "Daily":
                        generated = slips.daily(package_fixtures)
                    elif pkg == "Weekly":
                        generated = slips.weekly(package_fixtures)
                    elif pkg == "Monthly":
                        generated = slips.monthly(package_fixtures)
                    else:
                        generated = []

                if generated:
                    render_markdown(f"""
                    <div style="background: var(--background-card-alt); border: 1px solid var(--border-color); border-radius: 10px; padding: 1rem; margin: 1rem 0;">
                        <strong>{pkg} package: {len(generated)} slips generated</strong>
                        <span style="color: var(--text-secondary); margin-left: 0.5rem;">
                            All available leagues • diversified fixtures/outcomes
                        </span>
                    </div>
                    """, unsafe_allow_html=True)

                    combined_payload = {
                        "period": pkg.lower(),
                        "generated_at": generated[0].generated_at.isoformat(),
                        "slips": [s.__dict__ for s in generated],
                    }
                    st.download_button(
                        "📦 Download Full 5-Slip Package JSON",
                        json.dumps(combined_payload, default=str, indent=2),
                        file_name=f"{pkg.lower()}_5_slip_package.json",
                        mime="application/json",
                        use_container_width=True,
                        key=f"download-{pkg.lower()}-full-package",
                    )

                for s in generated:
                    render_markdown(f"""
                    <div style="background: var(--background-card); border-radius: 12px; padding: 1.5rem; margin: 1rem 0; border: 1px solid var(--primary-color);">
                        <h3 style="margin: 0 0 1rem 0;">📊 {s.period.title()} Slip #{s.slip_number}</h3>
                        <p style="color: var(--text-secondary); margin: 0 0 1rem 0;">{len(s.selections)} high-confidence selections</p>
                    </div>
                    """, unsafe_allow_html=True)

                    st.dataframe(s.selections, use_container_width=True, hide_index=True)

                    st.download_button(
                        "📥 Download Package JSON",
                        json.dumps(s.__dict__, default=str),
                        file_name=f"{s.period}_slip_{s.slip_number}.json",
                        mime="application/json",
                        use_container_width=True
                    )
            except Exception as exc:
                st.error(f"❌ Failed to generate package: {str(exc)}")

    # Saved-slip reader: JSON is the package interchange format. This lets
    # the same Streamlit app open a downloaded individual slip or the combined
    # five-slip package without requiring a separate JSON viewer.
    with st.expander("📂 Read a saved slip JSON", expanded=False):
        uploaded_slip = st.file_uploader(
            "Upload an individual slip or a full 5-slip package",
            type=["json"],
            key="saved_slip_json",
        )
        if uploaded_slip is not None:
            try:
                saved_payload = json.load(uploaded_slip)
                saved_slips = saved_payload.get("slips") if isinstance(saved_payload, dict) else None
                if isinstance(saved_slips, list):
                    st.success(f"Loaded {len(saved_slips)} slip(s).")
                    for saved in saved_slips:
                        if not isinstance(saved, dict):
                            continue
                        selections = saved.get("selections") or []
                        st.markdown(
                            f"**{str(saved.get('period', 'Slip')).title()} Slip #{saved.get('slip_number', '—')}** "
                            f"— {len(selections)} selections"
                        )
                        if selections:
                            st.dataframe(pd.DataFrame(selections), use_container_width=True, hide_index=True)
                elif isinstance(saved_payload, dict) and isinstance(saved_payload.get("selections"), list):
                    st.success(
                        f"Loaded {str(saved_payload.get('period', 'slip')).title()} Slip "
                        f"#{saved_payload.get('slip_number', '—')} with "
                        f"{len(saved_payload['selections'])} selections."
                    )
                    st.dataframe(
                        pd.DataFrame(saved_payload["selections"]),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.error("The uploaded JSON is not a recognized football-prediction slip format.")
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                st.error(f"Could not read the JSON file: {exc}")

    # Match explanation section
    render_markdown("---")
    render_markdown("""
    <div style="margin: 2rem 0 1rem 0;">
        <h2 style="margin: 0;">🤖 AI Match Analysis</h2>
        <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0;">
            Choose Gemini Flash, Groq, or both for the explanation layer. The statistical model remains the source of the probabilities.
        </p>
    </div>
    """, unsafe_allow_html=True)

    ai_engine = st.selectbox(
        "AI analysis engine",
        ["Gemini Flash", "Groq", "Both"],
        index=0,
        key="ai_analysis_engine",
        help="Gemini Flash uses Google's current stable Flash model. Both runs the two explainers independently so you can compare their explanations."
    )

    render_markdown("""
    <div style="display:flex;align-items:center;gap:8px;margin:0.4rem 0 1rem 0;">
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--success-color);"></span>
        <strong>LIVE AI MODE</strong>
        <span style="color:var(--text-secondary);">Gemini and Groq use real selected-match data when invoked below.</span>
    </div>
    """, unsafe_allow_html=True)

    fixture_options = [f"{fx.home_team} vs {fx.away_team} ({fx.fixture_id})" for fx in fixtures]
    selected_match = st.selectbox("Select match to analyze", fixture_options, key="match_explanation")

    if selected_match:
        fixture_id = selected_match.split(" (")[1].rstrip(")")
        fx = next((f for f in fixtures if f.fixture_id == fixture_id), None)

        if fx:
            detail_state_key = f"detailed_fixture_{fixture_id}"
            detailed_fx = st.session_state.get(detail_state_key)

            st.caption(
                "Detailed data is loaded only when requested, following API-Football's quota-saving guidance. "
                "The list view above uses the fixture pool already fetched."
            )

            if st.button("📚 Load full match data", key=f"load_detail_{fixture_id}", use_container_width=True):
                with st.spinner("Loading form, odds and match details..."):
                    try:
                        detailed_fx = provider.fixture_by_id(fixture_id) or fx
                        h2h_state_key = f"h2h_{fixture_id}"
                        home_id = (detailed_fx.stats or {}).get("home_team_id")
                        away_id = (detailed_fx.stats or {}).get("away_team_id")
                        if home_id and away_id and hasattr(provider, "head_to_head"):
                            st.session_state[h2h_state_key] = provider.head_to_head(home_id, away_id, limit=5)
                        st.session_state[detail_state_key] = detailed_fx
                    except Exception as exc:
                        st.error(f"❌ Could not load detailed match data: {exc}")
                        detailed_fx = fx

            if detailed_fx:
                ms = engine.shortlist(detailed_fx, settings.min_selection_confidence, 10)

                stats = detailed_fx.stats or {}
                hform, aform = detailed_fx.home_form, detailed_fx.away_form
                detail_cols = st.columns(4)
                detail_cols[0].metric("Home form", f"{hform.wins}W {hform.draws}D {hform.losses}L")
                detail_cols[1].metric("Away form", f"{aform.wins}W {aform.draws}D {aform.losses}L")
                detail_cols[2].metric("1X2 home odds", f"{detailed_fx.odds.get('home'):.2f}" if detailed_fx.odds.get("home") else "—")
                detail_cols[3].metric("1X2 away odds", f"{detailed_fx.odds.get('away'):.2f}" if detailed_fx.odds.get("away") else "—")

                facts = [{
                    "Field": "League",
                    "Value": detailed_fx.league,
                }, {
                    "Field": "Season",
                    "Value": detailed_fx.season,
                }, {
                    "Field": "Kick-off (UTC)",
                    "Value": detailed_fx.date.strftime("%Y-%m-%d %H:%M"),
                }, {
                    "Field": "Status",
                    "Value": detailed_fx.status,
                }, {
                    "Field": "Venue",
                    "Value": stats.get("venue") or "—",
                }, {
                    "Field": "Venue city",
                    "Value": stats.get("venue_city") or "—",
                }, {
                    "Field": "Referee",
                    "Value": stats.get("referee") or "—",
                }, {
                    "Field": "Home scoring rate",
                    "Value": f"{hform.goals_for_per_game:.2f} goals/game",
                }, {
                    "Field": "Away scoring rate",
                    "Value": f"{aform.goals_for_per_game:.2f} goals/game",
                }]
                st.dataframe(pd.DataFrame(facts), use_container_width=True, hide_index=True)

                # Optional historical context: last five meetings, loaded only
                # after the user requests detailed match data.
                h2h_rows = []
                for row in st.session_state.get(f"h2h_{fixture_id}", []):
                    teams = row.get("teams") or {}
                    goals = row.get("goals") or {}
                    league = row.get("league") or {}
                    fixture = row.get("fixture") or {}
                    home_name = (teams.get("home") or {}).get("name", "Home")
                    away_name = (teams.get("away") or {}).get("name", "Away")
                    hs = goals.get("home")
                    aw = goals.get("away")
                    h2h_rows.append({
                        "Date": str(fixture.get("date", ""))[:10] or "—",
                        "Competition": league.get("name", "—"),
                        "Match": f"{home_name} vs {away_name}",
                        "Score": f"{hs}-{aw}" if hs is not None and aw is not None else "—",
                        "Status": (fixture.get("status") or {}).get("short", "—"),
                    })
                if h2h_rows:
                    render_markdown("#### 🔁 Last 5 head-to-head meetings", unsafe_allow_html=False)
                    st.dataframe(pd.DataFrame(h2h_rows), use_container_width=True, hide_index=True)
                elif home_id and away_id:
                    st.caption("Head-to-head history is not available from the configured data provider for this fixture.")

                render_markdown("#### 🟢 Live AI controls", unsafe_allow_html=False)
                live_c1, live_c2 = st.columns(2)
                if live_c1.button("🟢 Run Live Gemini", key=f"live_gemini_{fixture_id}", use_container_width=True):
                    if not gemini_ok:
                        st.error("Gemini is not configured. Add GEMINI_API_KEY in Streamlit Cloud Secrets.")
                    else:
                        with st.spinner("Gemini is analyzing the selected match..."):
                            try:
                                live_text = gemini_explainer.explain(detailed_fx.__dict__, [m.__dict__ for m in ms[:10]])
                                st.success("Gemini live analysis completed.")
                                st.markdown(live_text)
                            except Exception as exc:
                                st.error(f"Gemini live analysis failed: {exc}")

                if live_c2.button("🟢 Run Live Groq", key=f"live_groq_{fixture_id}", use_container_width=True):
                    if not groq_ok:
                        st.error("Groq is not configured. Add GROQ_API_KEY in Streamlit Cloud Secrets.")
                    else:
                        with st.spinner("Groq is analyzing the selected match..."):
                            try:
                                live_text = explainer.explain(detailed_fx.__dict__, [m.__dict__ for m in ms[:10]])
                                st.success("Groq live analysis completed.")
                                st.markdown(live_text)
                            except Exception as exc:
                                st.error(f"Groq live analysis failed: {exc}")

                render_markdown("#### 📈 Top model markets", unsafe_allow_html=False)
                market_rows = [{
                    "Market": m.market,
                    "Selection": m.selection,
                    "Probability": f"{m.probability:.1%}",
                    "Fair Odds": f"{m.fair_odds:.2f}" if m.fair_odds else "—",
                    "Book Odds": f"{m.market_odds:.2f}" if m.market_odds else "—",
                } for m in ms[:10]]
                st.dataframe(pd.DataFrame(market_rows), use_container_width=True, hide_index=True)

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("🔍 Generate AI Analysis", key=f"explain_{fixture_id}", use_container_width=True):
                        if (ai_engine == "Gemini Flash" and not gemini_ok) or (ai_engine == "Groq" and not groq_ok) or (ai_engine == "Both" and not (gemini_ok or groq_ok)):
                            st.error("The selected AI engine is not configured. Add the corresponding API key in Streamlit Cloud → Manage app → Settings → Secrets.")
                        else:
                            with st.spinner("Analyzing match data..."):
                                ai_results = []
                                market_payload = [m.__dict__ for m in ms]
                                try:
                                    if ai_engine in {"Gemini Flash", "Both"} and gemini_ok:
                                        ai_results.append(("Gemini Flash", gemini_explainer.explain(detailed_fx.__dict__, market_payload)))
                                    if ai_engine in {"Groq", "Both"} and groq_ok:
                                        ai_results.append(("Groq", explainer.explain(detailed_fx.__dict__, market_payload)))

                                    for provider_label, analysis_text in ai_results:
                                        render_markdown(f"""
                                        <div style="background: var(--background-card); border-radius: 12px; padding: 1.5rem; margin: 1rem 0; border-left: 4px solid var(--accent-color);">
                                            <h4 style="margin: 0 0 1rem 0;">📝 {esc(provider_label)} Analysis</h4>
                                            <div style="color: var(--text-primary); line-height: 1.6;">
                                                {esc(analysis_text).replace(chr(10), '<br>')}
                                            </div>
                                        </div>
                                        """, unsafe_allow_html=True)
                                except Exception as exc:
                                    st.error(f"❌ AI analysis failed: {exc}")

                with c2:
                    if st.button("🔄 Refresh detailed data", key=f"refresh_detail_{fixture_id}", use_container_width=True):
                        st.session_state.pop(detail_state_key, None)
                        st.session_state.pop(f"h2h_{fixture_id}", None)
                        st.rerun()

    # Corners & cards section
    render_markdown("---")
    if fixtures:
        first_fixture = fixtures[0]
        detailed_first = provider.fixture_by_id(first_fixture.fixture_id) or first_fixture

        render_markdown(f"""
        <div style="margin: 2rem 0 1rem 0;">
            <h2 style="margin: 0;">📈 Corners & Cards Analysis</h2>
            <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0;">Model estimates from team/league averages — {esc(detailed_first.home_team)} vs {esc(detailed_first.away_team)}</p>
        </div>
        """, unsafe_allow_html=True)

        with st.expander("View detailed corners & cards predictions", expanded=False):
            st.caption("⚠️ These are model estimates from team/league corner and card averages, not scraped live match stats.")

            cc_predictions = corners_cards_engine.markets(detailed_first)

            # Group by market type
            corners_markets = [m for m in cc_predictions if "Corner" in m.market]
            cards_markets = [m for m in cc_predictions if "Card" in m.market]

            if corners_markets:
                render_markdown("### 🎯 Total Corners")
                for m in corners_markets[:6]:  # Show top 6
                    render_markdown(f"""
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.75rem; background: var(--background-card); border-radius: 8px; margin-bottom: 0.5rem;">
                        <div>
                            <span style="color: var(--text-primary); font-weight: 600;">{esc(m.selection)}</span>
                            <span style="color: var(--text-secondary); font-size: 0.85rem; margin-left: 0.5rem;">{esc(m.market)}</span>
                        </div>
                        <div style="text-align: right;">
                            <span style="color: var(--text-primary); font-weight: 700;">{m.probability:.1%}</span>
                            <span style="color: var(--text-secondary); font-size: 0.85rem; margin-left: 0.5rem;">@ {m.fair_odds:.2f}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

            if cards_markets:
                render_markdown("### 🟨 Total Cards")
                for m in cards_markets[:4]:  # Show top 4
                    render_markdown(f"""
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.75rem; background: var(--background-card); border-radius: 8px; margin-bottom: 0.5rem;">
                        <div>
                            <span style="color: var(--text-primary); font-weight: 600;">{esc(m.selection)}</span>
                            <span style="color: var(--text-secondary); font-size: 0.85rem; margin-left: 0.5rem;">{esc(m.market)}</span>
                        </div>
                        <div style="text-align: right;">
                            <span style="color: var(--text-primary); font-weight: 700;">{m.probability:.1%}</span>
                            <span style="color: var(--text-secondary); font-size: 0.85rem; margin-left: 0.5rem;">@ {m.fair_odds:.2f}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

# Analytics Dashboard Section
render_markdown("---")
render_markdown("""
<div style="margin: 2rem 0 1rem 0;">
    <h2 style="margin: 0;">📊 Analytics Dashboard</h2>
    <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0;">Visual insights and trend analysis</p>
</div>
""", unsafe_allow_html=True)

if fixtures:
    # Prepare data for visualizations
    fixture_data = []
    for fx in fixtures[:15]:  # Analyze first 15 fixtures
        best = engine.shortlist(fx, settings.min_selection_confidence, 1)
        if best:
            p = best[0]
            fixture_data.append({
                "Match": f"{fx.home_team} vs {fx.away_team}",
                "League": fx.league,
                "Market": p.market,
                "Selection": p.selection,
                "Probability": p.probability,
                "Fair Odds": p.fair_odds,
                "Date": fx.date
            })

    if fixture_data:
        df = pd.DataFrame(fixture_data)

        # Probability Distribution Chart
        col1, col2 = st.columns(2)

        with col1:
            render_markdown("""
            <div style="background: var(--background-card); border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; border: 1px solid var(--border-color);">
                <h4 style="margin: 0 0 1rem 0; color: var(--text-primary);">Probability Distribution</h4>
            </div>
            """, unsafe_allow_html=True)

            fig_prob = px.histogram(
                df,
                x="Probability",
                nbins=10,
                title="Distribution of Prediction Probabilities",
                color_discrete_sequence=["#D97757"]
            )
            fig_prob.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#1F1E1D"),
                xaxis=dict(gridcolor="rgba(31,30,29,0.08)"),
                yaxis=dict(gridcolor="rgba(31,30,29,0.08)")
            )
            st.plotly_chart(fig_prob, use_container_width=True, theme="streamlit")

        with col2:
            render_markdown("""
            <div style="background: var(--background-card); border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; border: 1px solid var(--border-color);">
                <h4 style="margin: 0 0 1rem 0; color: var(--text-primary);">Market Types Analysis</h4>
            </div>
            """, unsafe_allow_html=True)

            market_counts = df["Market"].value_counts()
            fig_market = px.pie(
                values=market_counts.values,
                names=market_counts.index,
                title="Prediction Market Distribution",
                color_discrete_sequence=px.colors.sequential.Oranges_r
            )
            fig_market.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#1F1E1D")
            )
            st.plotly_chart(fig_market, use_container_width=True, theme="streamlit")

        # Top Predictions Table with Visual Indicators
        render_markdown("""
        <div style="background: var(--background-card); border-radius: 12px; padding: 1.5rem; margin: 1rem 0; border: 1px solid var(--border-color);">
            <h4 style="margin: 0 0 1rem 0; color: var(--text-primary);">🏆 Top High-Confidence Predictions</h4>
        </div>
        """, unsafe_allow_html=True)

        top_predictions = df.nlargest(5, "Probability")

        for _, row in top_predictions.iterrows():
            confidence_color = "#3D8B5F" if row["Probability"] >= 0.75 else "#C17F2E" if row["Probability"] >= 0.65 else "#C1503D"

            render_markdown(f"""
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 1rem; background: var(--background-card-alt); border-radius: 8px; margin-bottom: 0.5rem; border-left: 4px solid {confidence_color};">
                <div>
                    <div style="color: var(--text-primary); font-weight: 600;">{esc(row['Match'])}</div>
                    <div style="color: var(--text-secondary); font-size: 0.85rem;">{esc(row['Market'])} - {esc(row['Selection'])}</div>
                </div>
                <div style="text-align: right;">
                    <div style="color: {confidence_color}; font-weight: 700; font-size: 1.1rem;">{row['Probability']:.1%}</div>
                    <div style="color: var(--text-secondary); font-size: 0.85rem;">@ {row['Fair Odds']:.2f}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        # Probability vs Odds Scatter Plot
        render_markdown("""
        <div style="background: var(--background-card); border-radius: 12px; padding: 1.5rem; margin: 1rem 0; border: 1px solid var(--border-color);">
            <h4 style="margin: 0 0 1rem 0; color: var(--text-primary);">📈 Probability vs Fair Odds Analysis</h4>
        </div>
        """, unsafe_allow_html=True)

        fig_scatter = px.scatter(
            df,
            x="Probability",
            y="Fair Odds",
            color="Market",
            size="Probability",
            hover_data=["Match", "Selection"],
            title="Probability vs Fair Odds Relationship",
            color_discrete_sequence=px.colors.qualitative.Bold
        )
        fig_scatter.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#1F1E1D"),
            xaxis=dict(gridcolor="rgba(31,30,29,0.08)", title="Probability"),
            yaxis=dict(gridcolor="rgba(31,30,29,0.08)", title="Fair Odds")
        )
        st.plotly_chart(fig_scatter, use_container_width=True, theme="streamlit")

else:
    st.info("📊 No fixture data available for analytics. Generate predictions first to see visualizations.")

# Architecture section with modern styling
render_markdown("---")
render_markdown("""
<div style="background: var(--background-card); border-radius: 12px; padding: 2rem; margin: 2rem 0; border: 1px solid var(--border-color);">
    <h3 style="margin: 0 0 1rem 0;">🏗️ System Architecture</h3>
    <div style="color: var(--text-secondary); line-height: 1.8; font-family: monospace;">
        Football APIs → Normalization → Feature/Model Layer → Score Distribution → All Markets → Value/Risk → Randomized Slips → VIP/Auth/Payments
    </div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Tips board: public Free/VVIP feed + a private Admin board for authoring tips.
# Runs against the same SQLite-backed Store the FastAPI backend uses (see
# app/store.py, app/admin_board.py) — this in-process Streamlit UI is a
# convenience for local/solo operation, not a substitute for the API's own
# auth for a real multi-user deployment (the API enforces the same role
# checks server-side regardless of which UI is used).
# ---------------------------------------------------------------------------
store = Store(settings.db_path)
auth_config = AuthConfig(jwt_secret=settings.auth_jwt_secret, jwt_expiry_hours=settings.auth_jwt_expiry_hours)
bootstrap_admin(store, settings.admin_bootstrap_email, settings.admin_bootstrap_password)

render_markdown("---")
render_markdown("""
<div style="margin: 2rem 0 1rem 0;">
    <h2 style="margin: 0;">🔒 VVIP Tips Board</h2>
    <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0;">Exclusive predictions and expert tips</p>
</div>
""", unsafe_allow_html=True)

# Modern authentication sidebar
with st.sidebar:
    render_markdown('<div class="settings-group-label" style="margin-top: 0;">Account</div>', unsafe_allow_html=True)

    if "user_id" not in st.session_state:
        st.session_state.user_id = None

    if st.session_state.user_id:
        profile = store.get_profile(st.session_state.user_id)
        if not profile:
            # A Streamlit session can outlive a database reset/redeploy. Clear
            # the stale session instead of dereferencing None and crashing the
            # whole dashboard.
            st.session_state.user_id = None
            st.rerun()
        roles = store.roles_for(st.session_state.user_id)

        render_markdown(f"""
        <div style="background: var(--background-card); border-radius: 10px; padding: 1rem; margin-bottom: 1rem; border: 1px solid var(--border-color);">
            <div style="color: var(--text-primary); font-weight: 600; margin-bottom: 0.5rem;">{esc(profile['email'])}</div>
            <div style="color: var(--text-secondary); font-size: 0.85rem;">{esc(', '.join(roles) or 'member')}</div>
        </div>
        """, unsafe_allow_html=True)

        if st.button("🚪 Sign Out", use_container_width=True):
            st.session_state.user_id = None
            st.rerun()
    else:
        tab_login, tab_signup = st.tabs(["🔐 Sign In", "📝 Sign Up"])

        with tab_login:
            email = st.text_input("Email", key="login_email", placeholder="your@email.com")
            password = st.text_input("Password", type="password", key="login_password", placeholder="••••••••")

            if st.button("Sign In", use_container_width=True, key="login_button"):
                profile = store.get_profile_by_email(email)
                if profile and verify_password(password, profile["password_hash"], profile["password_salt"]):
                    st.session_state.user_id = profile["user_id"]
                    st.success("✅ Successfully signed in!")
                    st.rerun()
                else:
                    st.error("❌ Invalid email or password.")

        with tab_signup:
            new_email = st.text_input("Email", key="signup_email", placeholder="your@email.com")
            new_password = st.text_input("Password (8+ characters)", type="password", key="signup_password", placeholder="••••••••")

            if st.button("Create Account", use_container_width=True, key="signup_button"):
                if store.get_profile_by_email(new_email):
                    st.error("❌ An account with that email already exists.")
                elif len(new_password) < 8:
                    st.error("❌ Password must be at least 8 characters.")
                else:
                    h, s = hash_password(new_password)
                    st.session_state.user_id = store.create_profile(new_email, h, s)
                    st.success("✅ Account created successfully!")
                    st.rerun()

current_user_id = st.session_state.get("user_id")
is_admin = bool(current_user_id and store.has_role(current_user_id, "admin"))
can_see_vvip = bool(current_user_id and (is_admin or store.has_role(current_user_id, "vvip")))

# Performance stats
tips = [serialize_tip(t, can_see_vvip) for t in store.list_tips()]
record = None
_since = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
_settled = store.settled_tips_since(_since)
_won = sum(1 for t in _settled if t["status"] == "won")
_lost = sum(1 for t in _settled if t["status"] == "lost")

render_markdown(f"""
<div style="background: var(--background-card); border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; border: 1px solid var(--border-color);">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <div>
            <h4 style="margin: 0; color: var(--text-primary);">Last 30 Days Performance</h4>
            <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0; font-size: 0.9rem;">Settled tips record</p>
        </div>
        <div style="text-align: right;">
            <div style="font-size: 1.5rem; font-weight: 700; color: var(--success-color);">{_won}W – {_lost}L</div>
            <div style="color: var(--text-secondary); font-size: 0.9rem;">
                {f"{_won/(_won+_lost):.0%} hit rate" if _won + _lost else "No settled tips"}
            </div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

if not tips:
    render_markdown("""
    <div style="text-align: center; padding: 2rem; background: var(--background-card); border-radius: 12px; border: 1px dashed var(--border-color);">
        <div style="font-size: 2rem; margin-bottom: 0.5rem;">📭</div>
        <p style="color: var(--text-secondary);">No tips posted yet. Check back soon!</p>
    </div>
    """, unsafe_allow_html=True)
else:
    render_markdown('<div class="tips-grid">', unsafe_allow_html=True)

    for t in tips:
        status_emoji = {"won": "✅", "lost": "❌", "void": "➖", "pending": "⏳"}.get(t["status"], "")
        status_color = {"won": "var(--success-color)", "lost": "var(--danger-color)", "void": "var(--text-secondary)", "pending": "var(--warning-color)"}.get(t["status"], "var(--text-secondary)")

        if t.get("locked"):
            render_markdown(f"""
            <div class="prediction-card" style="border-left: 4px solid var(--warning-color);">
                <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 0.75rem;">
                    <div>
                        <h4 style="margin: 0; font-size: 1.1rem;">{esc(t['match'])}</h4>
                        <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0; font-size: 0.85rem;">{esc(t['kickoff_time'])} • {esc(t['market'])}</p>
                    </div>
                    <span style="background: var(--warning-color); color: white; padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600;">🔒 VVIP</span>
                </div>
                <p style="color: var(--text-secondary); font-style: italic;">{esc(t['teaser'])}</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            render_markdown(f"""
            <div class="prediction-card" style="border-left: 4px solid {status_color};">
                <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 0.75rem;">
                    <div>
                        <h4 style="margin: 0; font-size: 1.1rem;">{esc(t['match'])}</h4>
                        <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0; font-size: 0.85rem;">{esc(t['kickoff_time'])} • {esc(t['market'])}</p>
                    </div>
                    <span style="font-size: 1.25rem;">{status_emoji}</span>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span style="color: var(--text-primary); font-weight: 600;">{esc(t['selection'])}</span>
                        <span style="color: var(--text-secondary); font-size: 0.85rem; margin-left: 0.5rem;">@ {esc(t.get('odds', '—'))}</span>
                    </div>
                    <span style="color: {status_color}; font-size: 0.85rem; font-weight: 600; text-transform: uppercase;">{esc(t['status'])}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

    render_markdown('</div>', unsafe_allow_html=True)

# Admin board
if is_admin:
    render_markdown("---")
    render_markdown("""
    <div style="margin: 2rem 0 1rem 0;">
        <h2 style="margin: 0;">🛠️ Admin Board</h2>
        <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0;">Manage tips and member access</p>
    </div>
    """, unsafe_allow_html=True)

    # Post new tip form
    with st.expander("📝 Post New Tip", expanded=False):
        with st.form("new_tip_form"):
            render_markdown("### Create a new prediction tip")

            c1, c2 = st.columns(2)
            match = c1.text_input("Match", placeholder="e.g., Arsenal vs Chelsea")
            kickoff = c2.text_input("Kick-off Time (ISO)", value=datetime.now(timezone.utc).isoformat(), placeholder="2026-09-12T19:00:00Z")

            market = c1.text_input("Market", placeholder="e.g., 1X2, Over/Under")
            selection = c2.text_input("Selection", placeholder="e.g., Home Win, Over 2.5")

            odds = c1.number_input("Odds", min_value=1.0, step=0.01, value=1.90)
            confidence = c2.slider("Confidence Level", 0.0, 1.0, 0.6)

            notes = st.text_area("Analysis Notes", placeholder="Add your analysis and reasoning...")

            tier = st.radio("Access Tier", ["free", "vvip"], horizontal=True)

            if st.form_submit_button("🚀 Post Tip", use_container_width=True):
                try:
                    store.create_tip(
                        match=match, kickoff_time=kickoff, market=market, selection=selection,
                        odds=odds, confidence=confidence, notes=notes, tier=tier,
                        created_by=current_user_id
                    )
                    st.success("✅ Tip posted successfully!")
                    st.rerun()
                except Exception as exc:
                    st.error(f"❌ Failed to post tip: {str(exc)}")

    # Manage existing tips
    render_markdown("### 📋 Manage Existing Tips")

    for t in store.list_tips():
        with st.expander(f"{t['match']} — {t['market']} / {t['selection']} ({t['tier']}, {t['status']})"):
            cols = st.columns(4)

            if cols[0].button("✅ Mark Won", key=f"won-{t['id']}", use_container_width=True):
                store.update_tip(t["id"], status="won")
                st.success("Marked as won!")
                st.rerun()

            if cols[1].button("❌ Mark Lost", key=f"lost-{t['id']}", use_container_width=True):
                store.update_tip(t["id"], status="lost")
                st.success("Marked as lost!")
                st.rerun()

            if cols[2].button("➖ Mark Void", key=f"void-{t['id']}", use_container_width=True):
                store.update_tip(t["id"], status="void")
                st.success("Marked as void!")
                st.rerun()

            if cols[3].button("🗑️ Delete", key=f"del-{t['id']}", use_container_width=True):
                store.delete_tip(t["id"])
                st.success("Tip deleted!")
                st.rerun()

    # Member management
    render_markdown("### 👥 Member Management")

    for m in store.list_members():
        with st.expander(f"{m['email']} — {', '.join(m['roles']) or 'member'}"):
            cols = st.columns([3, 2, 2])

            cols[0].write(f"**{m['email']}**")
            cols[1].write(f"Roles: {', '.join(m['roles']) or 'member'}")

            is_vvip = "vvip" in m["roles"]
            button_text = "🔓 Revoke VVIP" if is_vvip else "🔑 Grant VVIP"
            button_type = "secondary" if is_vvip else "primary"

            if cols[2].button(button_text, key=f"vvip-{m['user_id']}", use_container_width=True):
                if is_vvip:
                    store.revoke_role(m["user_id"], "vvip")
                    st.success("VVIP access revoked!")
                else:
                    store.grant_role(m["user_id"], "vvip")
                    st.success("VVIP access granted!")
                st.rerun()

elif current_user_id:
    render_markdown("""
    <div style="text-align: center; padding: 2rem; background: var(--background-card); border-radius: 12px; border: 1px dashed var(--border-color);">
        <div style="font-size: 2rem; margin-bottom: 0.5rem;">🔒</div>
        <p style="color: var(--text-secondary);">You're signed in as a member. Ask an admin to grant VVIP access to unlock premium tips.</p>
    </div>
    """, unsafe_allow_html=True)
else:
    render_markdown("""
    <div style="text-align: center; padding: 2rem; background: var(--background-card); border-radius: 12px; border: 1px dashed var(--border-color);">
        <div style="font-size: 2rem; margin-bottom: 0.5rem;">👤</div>
        <p style="color: var(--text-secondary);">Sign in from the sidebar to unlock VVIP tips you have access to.</p>
    </div>
    """, unsafe_allow_html=True)
