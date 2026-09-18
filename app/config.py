from pydantic_settings import BaseSettings, SettingsConfigDict
import logging

logger = logging.getLogger("football_predictor.config")

class Settings(BaseSettings):
    app_name: str = "Global AI Football Predictor"
    app_env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    # `auto` uses the configured provider chain and gracefully skips providers
    # whose credentials are absent. No synthetic data provider is included.
    football_provider: str = "auto"
    football_provider_chain: str = "api-football,football-data,livescorefootball,thesportsdb,sofascore"
    football_provider_mode: str = "fallback"
    football_api_base_url: str = ""
    football_api_key: str = ""
    api_football_key: str = ""
    football_data_api_key: str = ""
    football_data_base_url: str = "https://api.football-data.org/v4"
    football_data_competition: str = "PL"
    football_data_enrich_form: bool = False
    thesportsdb_api_key: str = "123"
    thesportsdb_base_url: str = "https://www.thesportsdb.com/api/v1/json"
    thesportsdb_league_id: str = "4328"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    appwrite_endpoint: str = ""
    appwrite_project_id: str = ""
    appwrite_database_id: str = ""
    appwrite_profiles_collection_id: str = ""
    appwrite_tips_collection_id: str = ""
    appwrite_subscriptions_collection_id: str = ""
    appwrite_payments_collection_id: str = ""
    appwrite_api_key: str = ""
    usdt_network: str = "TRC20"
    usdt_receiving_address: str = ""
    mtn_momo_enabled: bool = False
    telecel_enabled: bool = False
    mtn_momo_api_base_url: str = ""
    telecel_api_base_url: str = ""
    max_score_goals: int = 8
    min_selection_confidence: float = 0.60
    rng_salt: str = "change-me-to-secure-random-string"
    provider_cache_ttl_seconds: float = 60.0
    sofascore_browser_path: str = ""
    livescorefootball_league: str = "eng.1"
    # Comma-separated free livescoreFootball leagues used when no explicit league is requested.
    livescorefootball_leagues: str = "eng.1,esp.1,eng.2"
    # Name of the API-Football bookmaker to prefer for 1X2 odds (case-insensitive,
    # e.g. "Bet365"). Empty = use whichever bookmaker has a usable price first.
    odds_preferred_bookmaker: str = ""
    # Off by default — see ApiFootballProvider.enrich_list_fixtures docstring
    # for the free-plan quota trade-off before turning this on.
    api_football_enrich_lists: bool = False
    # Off by default — pulls real corners/cards averages via
    # /fixtures/statistics instead of corners_cards.py's neutral league-average
    # fallback. Costs ~1 extra call per historical match per team; see
    # ApiFootballProvider._recent_discipline docstring.
    api_football_fetch_discipline: bool = False
    # Dixon-Coles low-score correlation. -0.1 is a conservative literature-typical
    # default; set to 0 to fall back to pure independent Poisson.
    dixon_coles_rho: float = -0.1
    # CORS: comma-separated list of allowed origins, or "*" for none configured
    # (dev-only — sensible browsers still ignore "*" with credentialed requests).
    cors_allowed_origins: str = "*"
    # Basic in-process rate limiting (no Redis needed for a single-process
    # deployment; swap for a shared store behind a load balancer).
    rate_limit_auth_per_minute: int = 10
    rate_limit_default_per_minute: int = 120
    # Admin/VVIP tip board
    # Local SQLite file path (default, zero-setup) OR a full postgres://
    # connection string (for deployments where the local filesystem isn't
    # persistent — see app/db.py). Detected automatically by scheme.
    db_path: str = "data/predictor.sqlite3"
    auth_jwt_secret: str = "change-me-to-secure-random-jwt-secret"
    auth_jwt_expiry_hours: float = 24.0
    admin_bootstrap_email: str = ""
    admin_bootstrap_password: str = ""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._validate_security_settings()

    def _validate_security_settings(self):
        """Reject known placeholder secrets in production; allow them in development."""
        if self.app_env.strip().lower() == "production":
            insecure = []
            if self.rng_salt in {"change-me", "change-me-to-secure-random-string"}:
                insecure.append("RNG_SALT")
            if self.auth_jwt_secret in {"change-me-too", "change-me-to-secure-random-jwt-secret"}:
                insecure.append("AUTH_JWT_SECRET")
            if insecure:
                raise ValueError(
                    "Production startup blocked: set secure non-placeholder values for "
                    + ", ".join(insecure) + "."
                )

settings = Settings()
