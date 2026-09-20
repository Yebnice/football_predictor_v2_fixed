from __future__ import annotations

import hashlib
import json
import logging
import math
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import numpy as np
from sklearn.linear_model import PoissonRegressor
from sklearn.metrics import log_loss, mean_absolute_error
from sklearn.preprocessing import StandardScaler

from ..config import settings
from ..engine import FootballProbabilityEngine, MAX_TIP_PROBABILITY
from ..schemas import Fixture
from ..store import Store

logger = logging.getLogger("football_predictor.ml_pipeline")

FEATURE_NAMES = (
    "home_gf_5",
    "home_ga_5",
    "home_ppg_5",
    "home_gf_home_5",
    "home_ga_home_5",
    "away_gf_5",
    "away_ga_5",
    "away_ppg_5",
    "away_gf_away_5",
    "away_ga_away_5",
    "league_home_goals",
    "league_away_goals",
)
ALGORITHM = "poisson_regression"
MIN_TRAIN_ROWS = 40
VALIDATION_ROWS = 20
HISTORY_DAYS_DAILY = 180
HISTORY_DAYS_WEEKLY = 180
FORECAST_DAYS_DAILY = 31
FORECAST_DAYS_WEEKLY = 31
PREDICTION_CANDIDATES_PER_FIXTURE = 4
DRIFT_ALERT_Z = 0.75
PERFORMANCE_DRIFT_RATIO = 1.25


@dataclass
class PipelineResult:
    run_id: str
    mode: str
    status: str
    collected_matches: int = 0
    training_rows: int = 0
    model_version: str | None = None
    model_trained: bool = False
    predictions_created: int = 0
    ai_approved: int = 0
    ai_reviewed: int = 0
    ai_providers: tuple[str, ...] = ()
    ai_review_errors: list[str] | None = None
    settled_predictions: int = 0
    validation_log_loss: float | None = None
    calibration_ece: float | None = None
    feature_drift_score: float | None = None
    performance_log_loss: float | None = None
    drift_alert: bool = False
    errors: list[str] | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(dt: datetime) -> float:
    return dt.astimezone(timezone.utc).timestamp()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fixture_key(fx: Fixture) -> tuple[str, str, str, str]:
    return (
        fx.date.astimezone(timezone.utc).isoformat(),
        fx.home_team.strip().casefold(),
        fx.away_team.strip().casefold(),
        fx.league.strip().casefold(),
    )


def _is_finished(fx: Fixture) -> bool:
    status = str(fx.status or "").strip().casefold()
    return status in {
        "finished", "ft", "final", "completed", "aet", "pen",
        "match finished", "match finished after extra time",
        "match finished after penalty",
    } and fx.home_score is not None and fx.away_score is not None


def _history_stats(
    history: list[dict[str, Any]],
    team: str,
    before: str,
    *,
    venue: str | None = None,
    n: int = 5,
) -> dict[str, float]:
    target = team.strip().casefold()
    rows: list[dict[str, Any]] = []
    for row in history:
        try:
            if row["kickoff_utc"] >= before:
                continue
        except (KeyError, TypeError):
            continue
        home = str(row.get("home_team") or "").strip()
        away = str(row.get("away_team") or "").strip()
        if target not in {home.casefold(), away.casefold()}:
            continue
        if venue == "home" and home.casefold() != target:
            continue
        if venue == "away" and away.casefold() != target:
            continue
        if row.get("home_score") is None or row.get("away_score") is None:
            continue
        rows.append(row)
    rows.sort(key=lambda r: str(r.get("kickoff_utc", "")), reverse=True)
    rows = rows[:n]

    gf = ga = points = 0.0
    for row in rows:
        hs, aw = _safe_int(row.get("home_score")), _safe_int(row.get("away_score"))
        if hs is None or aw is None:
            continue
        if str(row.get("home_team") or "").strip().casefold() == target:
            gf += hs
            ga += aw
            points += 3 if hs > aw else 1 if hs == aw else 0
        else:
            gf += aw
            ga += hs
            points += 3 if aw > hs else 1 if aw == hs else 0
    count = len(rows)
    return {
        "gf": gf / count if count else 1.0,
        "ga": ga / count if count else 1.0,
        "ppg": points / count if count else 1.0,
    }


def _league_stats(history: list[dict[str, Any]], league: str, before: str, n: int = 80) -> dict[str, float]:
    target = str(league or "").strip().casefold()
    rows = [
        row for row in history
        if str(row.get("league") or "").strip().casefold() == target
        and str(row.get("kickoff_utc") or "") < before
        and row.get("home_score") is not None
        and row.get("away_score") is not None
    ]
    rows.sort(key=lambda r: str(r.get("kickoff_utc", "")), reverse=True)
    rows = rows[:n]
    if not rows:
        all_rows = [
            row for row in history
            if str(row.get("kickoff_utc") or "") < before
            and row.get("home_score") is not None
            and row.get("away_score") is not None
        ]
        all_rows.sort(key=lambda r: str(r.get("kickoff_utc", "")), reverse=True)
        rows = all_rows[:n]
    if not rows:
        return {"home": 1.35, "away": 1.05}
    return {
        "home": float(np.mean([_safe_float(r.get("home_score"), 1.35) for r in rows])),
        "away": float(np.mean([_safe_float(r.get("away_score"), 1.05) for r in rows])),
    }


def build_features(fx: Fixture, history: list[dict[str, Any]]) -> dict[str, float]:
    before = fx.date.astimezone(timezone.utc).isoformat()
    home = _history_stats(history, fx.home_team, before, n=5)
    away = _history_stats(history, fx.away_team, before, n=5)
    home_venue = _history_stats(history, fx.home_team, before, venue="home", n=5)
    away_venue = _history_stats(history, fx.away_team, before, venue="away", n=5)
    league = _league_stats(history, fx.league, before)

    return {
        "home_gf_5": home["gf"],
        "home_ga_5": home["ga"],
        "home_ppg_5": home["ppg"],
        "home_gf_home_5": home_venue["gf"],
        "home_ga_home_5": home_venue["ga"],
        "away_gf_5": away["gf"],
        "away_ga_5": away["ga"],
        "away_ppg_5": away["ppg"],
        "away_gf_away_5": away_venue["gf"],
        "away_ga_away_5": away_venue["ga"],
        "league_home_goals": league["home"],
        "league_away_goals": league["away"],
    }


def _feature_vector(features: dict[str, float]) -> list[float]:
    return [_safe_float(features.get(name), 0.0) for name in FEATURE_NAMES]


def _score_probs(home_lambda: float, away_lambda: float, max_goals: int = 8) -> tuple[float, float, float]:
    home_lambda = max(0.05, min(5.0, float(home_lambda)))
    away_lambda = max(0.05, min(5.0, float(away_lambda)))
    def pois(lam: float, k: int) -> float:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)
    home = np.array([pois(home_lambda, i) for i in range(max_goals + 1)])
    away = np.array([pois(away_lambda, i) for i in range(max_goals + 1)])
    matrix = np.outer(home, away)
    matrix /= max(matrix.sum(), 1e-12)
    home_p = float(np.tril(matrix, -1).sum())
    draw_p = float(np.trace(matrix))
    away_p = float(np.triu(matrix, 1).sum())
    total = home_p + draw_p + away_p
    return home_p / total, draw_p / total, away_p / total


def _calibration_ece(y_true: list[int], probs: np.ndarray, bins: int = 10) -> float:
    if not y_true or len(probs) != len(y_true):
        return 1.0
    errors: list[float] = []
    for class_index in range(probs.shape[1]):
        y = np.asarray([1 if target == class_index else 0 for target in y_true], dtype=float)
        p = probs[:, class_index]
        for lower in np.linspace(0.0, 0.9, bins):
            upper = lower + 0.1
            mask = (p >= lower) & (p < upper if upper < 1.0 else p <= upper)
            if not np.any(mask):
                continue
            errors.append(abs(float(y[mask].mean()) - float(p[mask].mean())))
    return float(np.mean(errors)) if errors else 1.0


def _model_version(trained_at: datetime) -> str:
    return f"poisson-{trained_at.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _serialize_model(
    home_model: PoissonRegressor,
    away_model: PoissonRegressor,
    scaler: StandardScaler,
) -> str:
    payload = {
        "algorithm": ALGORITHM,
        "feature_names": list(FEATURE_NAMES),
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "home": {
            "coef": home_model.coef_.tolist(),
            "intercept": float(home_model.intercept_),
        },
        "away": {
            "coef": away_model.coef_.tolist(),
            "intercept": float(away_model.intercept_),
        },
    }
    return json.dumps(payload, separators=(",", ":"))


def _predict_artifact(artifact: dict[str, Any], features: list[float]) -> tuple[float, float]:
    mean = np.asarray(artifact["scaler_mean"], dtype=float)
    scale = np.asarray(artifact["scaler_scale"], dtype=float)
    scale = np.where(np.abs(scale) < 1e-12, 1.0, scale)
    x = (np.asarray(features, dtype=float) - mean) / scale
    def mean_goal(side: str) -> float:
        block = artifact[side]
        linear = float(block["intercept"]) + float(np.dot(np.asarray(block["coef"], dtype=float), x))
        return float(np.clip(np.exp(np.clip(linear, -4.0, 2.0)), 0.05, 5.0))
    return mean_goal("home"), mean_goal("away")


def _load_active_artifact(store: Store) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
    row = store.get_active_ml_model()
    if not row:
        return None
    try:
        return (
            str(row["model_version"]),
            json.loads(row["artifact_json"]),
            json.loads(row["metrics_json"] or "{}"),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _build_training_rows(history: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    finished = [
        row for row in history
        if row.get("home_score") is not None and row.get("away_score") is not None
    ]
    finished.sort(key=lambda r: str(r.get("kickoff_utc", "")))

    X: list[list[float]] = []
    y: list[list[float]] = []
    metadata: list[dict[str, Any]] = []
    for row in finished:
        fx = Fixture(
            fixture_id=str(row.get("fixture_id") or ""),
            date=datetime.fromisoformat(str(row["kickoff_utc"]).replace("Z", "+00:00")),
            league=str(row.get("league") or "Unknown"),
            season=str(row.get("season") or ""),
            home_team=str(row.get("home_team") or "Unknown"),
            away_team=str(row.get("away_team") or "Unknown"),
            status="finished",
            home_score=_safe_int(row.get("home_score")),
            away_score=_safe_int(row.get("away_score")),
        )
        before = str(row["kickoff_utc"])
        home_history = [
            h for h in finished
            if str(h.get("kickoff_utc", "")) < before
        ]
        hf = _history_stats(home_history, fx.home_team, before, n=5)
        af = _history_stats(home_history, fx.away_team, before, n=5)
        if not home_history or not any(
            str(h.get("home_team") or "").strip().casefold() == fx.home_team.strip().casefold()
            or str(h.get("away_team") or "").strip().casefold() == fx.home_team.strip().casefold()
            for h in home_history
        ):
            continue
        if not any(
            str(h.get("home_team") or "").strip().casefold() == fx.away_team.strip().casefold()
            or str(h.get("away_team") or "").strip().casefold() == fx.away_team.strip().casefold()
            for h in home_history
        ):
            continue
        f = build_features(fx, home_history)
        X.append(_feature_vector(f))
        y.append([float(fx.home_score or 0), float(fx.away_score or 0)])
        metadata.append({"kickoff_utc": before, "fixture": fx})

    return np.asarray(X, dtype=float), np.asarray(y, dtype=float), metadata


def _evaluate(
    home_model: PoissonRegressor,
    away_model: PoissonRegressor,
    scaler: StandardScaler,
    X: np.ndarray,
    y: np.ndarray,
    max_goals: int,
) -> dict[str, float]:
    if len(X) == 0:
        return {}
    Xs = scaler.transform(X)
    home_lambda = home_model.predict(Xs)
    away_lambda = away_model.predict(Xs)
    probs = np.asarray([
        _score_probs(h, a, max_goals=max_goals)
        for h, a in zip(home_lambda, away_lambda)
    ])
    labels = [0 if h > a else 1 if h == a else 2 for h, a in y]
    metrics = {
        "log_loss": float(log_loss(labels, probs, labels=[0, 1, 2])),
        "calibration_ece": _calibration_ece(labels, probs),
        "home_goal_mae": float(mean_absolute_error(y[:, 0], home_lambda)),
        "away_goal_mae": float(mean_absolute_error(y[:, 1], away_lambda)),
        "validation_rows": int(len(X)),
        "mean_home_lambda": float(np.mean(home_lambda)),
        "mean_away_lambda": float(np.mean(away_lambda)),
    }
    return metrics


def train_poisson_model(
    store: Store,
    history: list[dict[str, Any]],
    *,
    max_goals: int = 8,
    force: bool = False,
) -> tuple[str | None, dict[str, Any], bool]:
    X, y, metadata = _build_training_rows(history)
    if len(X) < MIN_TRAIN_ROWS:
        return None, {"reason": f"Need at least {MIN_TRAIN_ROWS} leakage-safe training rows; found {len(X)}."}, False

    split = max(20, int(len(X) * 0.80))
    if len(X) - split < 10:
        split = len(X) - 10
    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    home_model = PoissonRegressor(alpha=1.0, max_iter=1000)
    away_model = PoissonRegressor(alpha=1.0, max_iter=1000)
    home_model.fit(X_train_scaled, y_train[:, 0])
    away_model.fit(X_train_scaled, y_train[:, 1])

    metrics = _evaluate(home_model, away_model, scaler, X_val, y_val, max_goals)
    metrics["training_rows"] = int(len(X_train))
    metrics["total_rows"] = int(len(X))
    metrics["feature_names"] = list(FEATURE_NAMES)

    active = store.get_active_ml_model()
    if active and not force:
        try:
            old_metrics = json.loads(active["metrics_json"] or "{}")
            old_loss = float(old_metrics.get("log_loss", 999.0))
            new_loss = float(metrics.get("log_loss", 999.0))
            # Keep the active model when the new validation result is materially
            # worse. Retraining still gets recorded for auditability.
            if new_loss > old_loss * 1.05:
                metrics["rejected_for_regression"] = True
                return str(active["model_version"]), metrics, False
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    trained_at = _now()
    version = _model_version(trained_at)
    artifact = _serialize_model(home_model, away_model, scaler)
    store.create_ml_model(
        model_version=version,
        algorithm=ALGORITHM,
        trained_at=_ts(trained_at),
        training_rows=len(X_train),
        metrics=metrics,
        artifact_json=artifact,
    )
    store.set_active_ml_model(version)
    return version, metrics, True


def _collect_from_provider(
    provider: Any,
    start: datetime,
    end: datetime,
    *,
    max_results: int = 800,
) -> list[Fixture]:
    """Collect a bounded historical+forecast window with score-aware merging.

    Background ML needs completed scores for training. A generic provider merge
    can legitimately return a fixture-only copy before a results provider returns
    the same match with its final score. For ML collection we therefore make a
    second, provider-specific pass whenever score coverage is too low and always
    prefer scored records during de-duplication.
    """
    rows: list[Fixture] = []
    providers = getattr(provider, "providers", [])

    # API-Football has a dedicated global endpoint, so use it when available.
    for name, child in providers:
        if name in {"api-football", "api-sports", "apisports"}:
            fetch = getattr(child, "global_fixtures", None)
            if callable(fetch):
                try:
                    rows.extend(fetch(start, end, max_results=max_results))
                except Exception as exc:
                    logger.warning("API-Football global ML collection failed: %s", exc)

    # Normal composite collection. Query both adjacent seasons because the
    # 180-day window crosses the 2025/26 -> 2026/27 boundary.
    for season_year in dict.fromkeys((start.year, start.year - 1)):
        try:
            rows.extend(list(provider.fixtures(start, end, season=season_year) or []))
        except Exception as exc:
            logger.warning(
                "Composite ML collection failed for season %s: %s",
                season_year,
                exc,
            )

    def has_score(fx: Fixture) -> bool:
        return fx.home_score is not None and fx.away_score is not None

    scored_count = sum(1 for fx in rows if has_score(fx))

    # If the composite result contains too few historical scores, query each
    # child provider directly. This bypasses provider-level deduplication and
    # catches the important case where a fixture/schedule source has masked a
    # richer historical-results source.
    if providers and scored_count < MIN_TRAIN_ROWS:
        for name, child in providers:
            if name in {"api-football", "api-sports", "apisports"}:
                # global_fixtures was already attempted above.
                continue
            for season_year in dict.fromkeys((start.year, start.year - 1)):
                try:
                    direct = list(
                        child.fixtures(start, end, season=season_year) or []
                    )
                    rows.extend(direct)
                except Exception as exc:
                    logger.warning(
                        "Direct ML history collection failed for %s season %s: %s",
                        name,
                        season_year,
                        exc,
                    )

    # De-duplicate by the stable football identity while preferring a record
    # that contains an actual final score.
    by_key: dict[tuple[str, str, str, str], Fixture] = {}
    for fx in rows:
        if (
            not fx.fixture_id
            or str(fx.home_team).strip().casefold() in {"", "unknown"}
            or str(fx.away_team).strip().casefold() in {"", "unknown"}
        ):
            continue
        key = _fixture_key(fx)
        current = by_key.get(key)
        if current is None:
            by_key[key] = fx
            continue
        if not has_score(current) and has_score(fx):
            by_key[key] = fx

    out = list(by_key.values())
    out.sort(key=lambda x: x.date)

    score_count = sum(1 for fx in out if has_score(fx))
    logger.info(
        "ML collection coverage: total=%s scored=%s unscored=%s window=%s..%s",
        len(out),
        score_count,
        len(out) - score_count,
        start.isoformat(),
        end.isoformat(),
    )
    return out[:max_results]


def collect_and_store_matches(
    provider: Any,
    store: Store,
    *,
    history_days: int,
    forecast_days: int,
) -> tuple[list[dict[str, Any]], int]:
    now = _now()
    start = now - timedelta(days=max(1, int(history_days)))
    end = now + timedelta(days=max(1, int(forecast_days)))
    fixtures = _collect_from_provider(provider, start, end, max_results=800)
    rows: list[dict[str, Any]] = []
    for fx in fixtures:
        rows.append({
            "fixture_id": str(fx.fixture_id),
            "kickoff_utc": fx.date.astimezone(timezone.utc).isoformat(),
            "league": str(fx.league or "Unknown"),
            "season": str(fx.season or ""),
            "home_team": str(fx.home_team or "Unknown"),
            "away_team": str(fx.away_team or "Unknown"),
            "status": str(fx.status or "scheduled"),
            "home_score": _safe_int(fx.home_score),
            "away_score": _safe_int(fx.away_score),
            "source_provider": str((fx.stats or {}).get("provider") or (fx.stats or {}).get("source") or ""),
            "raw_json": json.dumps(fx.__dict__, default=str, separators=(",", ":")),
        })
    store.upsert_ml_matches(rows)
    return rows, len(rows)


def _prediction_candidate_rows(
    engine: FootballProbabilityEngine,
    fx: Fixture,
    home_lambda: float,
    away_lambda: float,
) -> tuple[Fixture, list[Any]]:
    model_fx = replace(fx, home_xg=float(home_lambda), away_xg=float(away_lambda))
    candidates = engine.shortlist(
        model_fx,
        min_conf=0.0,
        top_n=PREDICTION_CANDIDATES_PER_FIXTURE,
        max_conf=MAX_TIP_PROBABILITY,
    )
    return model_fx, candidates


def create_background_predictions(
    store: Store,
    engine: FootballProbabilityEngine,
    fixtures: Iterable[Fixture],
    history: list[dict[str, Any]],
    model_version: str,
    artifact: dict[str, Any],
) -> tuple[list[Fixture], int]:
    upcoming: list[Fixture] = []
    created = 0
    for fx in fixtures:
        status = str(fx.status or "").casefold()
        if fx.date <= _now() or status not in {"scheduled", "not started", "ns", "tbd", "upcoming", ""}:
            continue
        features = build_features(fx, history)
        vector = _feature_vector(features)
        home_lambda, away_lambda = _predict_artifact(artifact, vector)
        model_fx, candidates = _prediction_candidate_rows(engine, fx, home_lambda, away_lambda)
        if not candidates:
            continue
        feature_json = json.dumps(features, separators=(",", ":"))
        feature_hash = hashlib.sha256(feature_json.encode()).hexdigest()
        store.save_ml_feature_snapshot(
            fixture_id=fx.fixture_id,
            as_of_utc=fx.date.astimezone(timezone.utc).isoformat(),
            features=features,
            model_version=model_version,
            feature_hash=feature_hash,
        )

        # Persist the complete internal 1X2 distribution for proper log-loss
        # evaluation even when the publishable tip is BTTS/Goals/Double Chance.
        one_x_two = [m for m in engine.markets(model_fx) if m.market == "1X2"]
        for market in one_x_two:
            store.save_ml_prediction(
                prediction_id=str(uuid.uuid4()),
                fixture_id=fx.fixture_id,
                model_version=model_version,
                predicted_at=_ts(_now()),
                kickoff_utc=fx.date.astimezone(timezone.utc).isoformat(),
                league=fx.league,
                home_team=fx.home_team,
                away_team=fx.away_team,
                market=market.market,
                selection=market.selection,
                probability=float(market.probability),
                fair_odds=market.fair_odds,
                model_probability=float(market.probability),
                home_lambda=home_lambda,
                away_lambda=away_lambda,
                candidate_index=-1,
                status="internal",
            )

        for index, candidate in enumerate(candidates):
            store.save_ml_prediction(
                prediction_id=str(uuid.uuid4()),
                fixture_id=fx.fixture_id,
                model_version=model_version,
                predicted_at=_ts(_now()),
                kickoff_utc=fx.date.astimezone(timezone.utc).isoformat(),
                league=fx.league,
                home_team=fx.home_team,
                away_team=fx.away_team,
                market=candidate.market,
                selection=candidate.selection,
                probability=float(candidate.probability),
                fair_odds=candidate.fair_odds,
                model_probability=float(candidate.probability),
                home_lambda=home_lambda,
                away_lambda=away_lambda,
                candidate_index=index,
                status="pending_ai",
            )
            created += 1
        upcoming.append(model_fx)
    return upcoming, created


def settle_predictions(store: Store, history: list[dict[str, Any]]) -> int:
    by_key = {
        (
            str(row.get("fixture_id") or ""),
            str(row.get("kickoff_utc") or ""),
        ): row
        for row in history
        if row.get("home_score") is not None and row.get("away_score") is not None
    }
    settled = 0
    for prediction in store.list_ml_predictions(limit=10000, statuses=("approved", "internal", "pending_ai")):
        key = (str(prediction["fixture_id"]), str(prediction["kickoff_utc"]))
        row = by_key.get(key)
        if not row:
            continue
        hs, aw = _safe_int(row.get("home_score")), _safe_int(row.get("away_score"))
        if hs is None or aw is None:
            continue
        selection = str(prediction.get("selection") or "")
        market = str(prediction.get("market") or "")
        if market == "1X2":
            actual = "Home Win" if hs > aw else "Draw" if hs == aw else "Away Win"
        elif market == "BTTS":
            actual = "Yes" if hs > 0 and aw > 0 else "No"
        elif market == "Double Chance":
            actual = "1X" if (hs >= aw) else "X2" if aw >= hs else "12"
        elif market == "Draw No Bet":
            actual = "Home" if hs > aw else "Away" if aw > hs else "Void"
        elif market == "Total Goals":
            try:
                line = float(selection.split()[-1])
                total = hs + aw
                actual = ("Over " if total > line else "Under ") + f"{line:.1f}"
            except Exception:
                actual = None
        elif market.endswith(" Goals"):
            try:
                line = float(selection.split()[-1])
                goals = hs if market.startswith(str(prediction.get("home_team"))) else aw
                actual = ("Over " if goals > line else "Under ") + f"{line:.1f}"
            except Exception:
                actual = None
        else:
            actual = None
        if actual is None:
            continue
        won = actual == selection
        store.settle_ml_prediction(
            prediction_id=str(prediction["id"]),
            actual_outcome=actual,
            won=won,
            settled_at=_ts(_now()),
        )
        settled += 1
    return settled


def performance_and_drift(store: Store, model_version: str | None) -> tuple[float | None, float | None, bool, dict[str, Any]]:
    if not model_version:
        return None, None, False, {"reason": "No active model"}

    model = store.get_ml_model(model_version)
    if not model:
        return None, None, False, {"reason": "Active model record missing"}

    try:
        metrics = json.loads(model["metrics_json"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        metrics = {}

    settled = [
        row for row in store.list_ml_predictions(limit=10000, statuses=("internal", "settled_internal"))
        if str(row.get("model_version")) == model_version and row.get("settled_at")
    ]
    if settled:
        by_fixture: dict[str, dict[str, Any]] = {}
        for row in settled:
            by_fixture.setdefault(str(row["fixture_id"]), {})[str(row["selection"])] = row
        y: list[int] = []
        probs: list[list[float]] = []
        for rows in by_fixture.values():
            if not {"Home Win", "Draw", "Away Win"}.issubset(rows):
                continue
            actual = str(next(iter(rows.values())).get("actual_outcome") or "")
            label = {"Home Win": 0, "Draw": 1, "Away Win": 2}.get(actual)
            if label is None:
                continue
            probs.append([
                _safe_float(rows["Home Win"]["probability"]),
                _safe_float(rows["Draw"]["probability"]),
                _safe_float(rows["Away Win"]["probability"]),
            ])
            y.append(label)
        performance_loss = float(log_loss(y, np.asarray(probs), labels=[0, 1, 2])) if y else None
    else:
        performance_loss = None

    validation_loss = _safe_float(metrics.get("log_loss"), 999.0)
    drift_alert = bool(
        performance_loss is not None and validation_loss < 999.0
        and performance_loss > validation_loss * PERFORMANCE_DRIFT_RATIO
    )
    details = {
        "validation_log_loss": validation_loss,
        "performance_log_loss": performance_loss,
        "prediction_count": len(y) if settled else 0,
        "performance_ratio": (
            performance_loss / validation_loss
            if performance_loss is not None and validation_loss > 0 else None
        ),
    }
    return performance_loss, None, drift_alert, details


def feature_drift(store: Store, model_version: str | None) -> tuple[float | None, bool, dict[str, Any]]:
    if not model_version:
        return None, False, {"reason": "No active model"}
    model = store.get_ml_model(model_version)
    if not model:
        return None, False, {"reason": "Model record missing"}
    try:
        metrics = json.loads(model["metrics_json"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        metrics = {}
    current = store.list_ml_feature_snapshots(model_version=model_version, limit=10000)
    if len(current) < 20:
        return None, False, {"reason": "Fewer than 20 feature snapshots"}

    reference_means = metrics.get("feature_reference_means") or {}
    reference_stds = metrics.get("feature_reference_stds") or {}
    scores: dict[str, float] = {}
    for name in FEATURE_NAMES:
        values = [_safe_float(json.loads(row["features_json"]).get(name)) for row in current if row.get("features_json")]
        if not values:
            continue
        mean = float(np.mean(values))
        ref_mean = _safe_float(reference_means.get(name), mean)
        ref_std = max(_safe_float(reference_stds.get(name), 1.0), 0.05)
        scores[name] = abs(mean - ref_mean) / ref_std
    score = float(np.mean(list(scores.values()))) if scores else None
    alert = bool(score is not None and score >= DRIFT_ALERT_Z)
    return score, alert, {"feature_z_scores": scores, "snapshots": len(current)}


def run_background_pipeline(
    *,
    provider: Any,
    store: Store,
    engine: FootballProbabilityEngine,
    prediction_agent: Any,
    mode: str = "daily",
) -> PipelineResult:
    mode = str(mode or "daily").strip().lower()
    if mode not in {"daily", "weekly"}:
        raise ValueError("mode must be daily or weekly")

    started = _now()
    run_id = str(uuid.uuid4())
    result = PipelineResult(run_id=run_id, mode=mode, status="running", errors=[])
    store.create_ml_run(run_id, mode, _ts(started), "running", {})

    try:
        history_days = HISTORY_DAYS_WEEKLY if mode == "weekly" else HISTORY_DAYS_DAILY
        forecast_days = FORECAST_DAYS_WEEKLY if mode == "weekly" else FORECAST_DAYS_DAILY
        rows, collected = collect_and_store_matches(
            provider,
            store,
            history_days=history_days,
            forecast_days=forecast_days,
        )
        result.collected_matches = collected

        history = store.list_ml_matches(limit=10000, finished_only=True)
        result.settled_predictions = settle_predictions(store, rows)

        active = _load_active_artifact(store)
        force_train = mode == "weekly" or active is None
        model_version = active[0] if active else None
        metrics = active[2] if active else {}

        latest_trained_at = None
        active_row = store.get_active_ml_model()
        if active_row:
            latest_trained_at = float(active_row["trained_at"])
        if latest_trained_at and (_ts(_now()) - latest_trained_at) >= 7 * 24 * 3600:
            force_train = True

        new_version, train_info, model_trained = train_poisson_model(
            store,
            history,
            max_goals=engine.max_goals,
            force=force_train,
        )
        if new_version:
            model_version = new_version
        if model_trained:
            active = _load_active_artifact(store)
            metrics = active[2] if active else train_info
            result.model_trained = True
        elif not model_version:
            metrics = train_info

        result.model_version = model_version
        result.training_rows = int(metrics.get("training_rows", 0))
        result.validation_log_loss = _safe_float(metrics.get("log_loss"), None) if metrics.get("log_loss") is not None else None
        result.calibration_ece = _safe_float(metrics.get("calibration_ece"), None) if metrics.get("calibration_ece") is not None else None

        if model_version:
            active = _load_active_artifact(store)
            if not active:
                raise RuntimeError("Active ML model could not be loaded after training.")
            _, artifact, metrics = active

            # Update the training reference distribution for feature-drift monitoring.
            if "feature_reference_means" not in metrics:
                X, _, _ = _build_training_rows(history)
                if len(X):
                    metrics["feature_reference_means"] = {
                        name: float(np.mean(X[:, idx])) for idx, name in enumerate(FEATURE_NAMES)
                    }
                    metrics["feature_reference_stds"] = {
                        name: float(np.std(X[:, idx]) or 1.0) for idx, name in enumerate(FEATURE_NAMES)
                    }
                    store.update_ml_model_metrics(model_version, metrics)

            performance_loss, _, performance_alert, perf_details = performance_and_drift(store, model_version)
            feature_score, feature_alert, feature_details = feature_drift(store, model_version)
            result.performance_log_loss = performance_loss
            result.feature_drift_score = feature_score
            result.drift_alert = bool(performance_alert or feature_alert)
            store.save_ml_drift(
                drift_id=str(uuid.uuid4()),
                checked_at=_ts(_now()),
                model_version=model_version,
                feature_drift_score=feature_score,
                performance_log_loss=performance_loss,
                validation_log_loss=_safe_float(metrics.get("log_loss"), 999.0),
                alert=result.drift_alert,
                details={"performance": perf_details, "feature": feature_details},
            )

            # Generate new forecasts before the AI gate.
            future_start = _now()
            future_end = future_start + timedelta(days=forecast_days)
            future_rows = [
                fx for fx in _collect_from_provider(provider, future_start, future_end, max_results=400)
                if fx.date >= future_start
            ]
            forecast_fx, created = create_background_predictions(
                store,
                engine,
                future_rows,
                history,
                model_version,
                artifact,
            )
            result.predictions_created = created

            # AI is the publication gate. It receives model metrics, drift state,
            # processed feature data and deeper provider evidence. No foreground
            # UI call is required for this step.
            if forecast_fx and prediction_agent.configured:
                ai_context = {
                    "pipeline": "background",
                    "model_version": model_version,
                    "algorithm": ALGORITHM,
                    "training_rows": metrics.get("training_rows"),
                    "validation_log_loss": metrics.get("log_loss"),
                    "calibration_ece": metrics.get("calibration_ece"),
                    "performance_log_loss": performance_loss,
                    "feature_drift_score": feature_score,
                    "drift_alert": result.drift_alert,
                }
                # Stratify the AI review pool by kickoff window. The old
                # probability-only top-60 selection could spend the entire review
                # budget on later 31-day fixtures, leaving only a few predictions
                # approved for the next 24 hours/7 days even when the providers
                # supplied many nearer-term matches.
                review_pool: list[Fixture] = []
                review_seen: set[str] = set()
                review_now = _now()

                def add_review_rows(rows: list[Fixture], limit: int) -> None:
                    for item in sorted(rows, key=lambda x: x.date)[:max(0, int(limit))]:
                        fid = str(item.fixture_id)
                        if not fid or fid in review_seen:
                            continue
                        review_seen.add(fid)
                        review_pool.append(item)

                daily_rows = [
                    fx for fx in forecast_fx
                    if review_now <= fx.date <= review_now + timedelta(days=1)
                ]
                weekly_rows = [
                    fx for fx in forecast_fx
                    if review_now + timedelta(days=1) < fx.date <= review_now + timedelta(days=7)
                ]
                later_rows = [
                    fx for fx in forecast_fx
                    if review_now + timedelta(days=7) < fx.date <= review_now + timedelta(days=31)
                ]

                # Review the whole near-term daily window whenever possible,
                # then enough additional weekly/monthly rows to keep the same
                # maximum 60-review budget.
                add_review_rows(daily_rows, 30)
                add_review_rows(weekly_rows, 20)
                add_review_rows(later_rows, 10)

                agent_run = prediction_agent.review_fixtures(
                    review_pool,
                    candidate_limit=len(review_pool),
                    deep_evidence_limit=min(10, len(review_pool)),
                    background_context=ai_context,
                )
                for fx in forecast_fx:
                    decision = agent_run.decisions.get(str(fx.fixture_id))
                    if decision:
                        store.approve_ml_prediction(
                            fixture_id=str(fx.fixture_id),
                            model_version=model_version,
                            market=str(decision["market"]),
                            selection=str(decision["selection"]),
                            review_score=float(decision.get("review_score", 0.0)),
                            rationale=str(decision.get("rationale") or ""),
                            risk_flags=decision.get("risk_flags") or [],
                            reviewers=decision.get("reviewers") or [],
                        )
                    else:
                        store.reject_pending_ml_predictions(
                            fixture_id=str(fx.fixture_id),
                            model_version=model_version,
                        )
                result.ai_approved = int(agent_run.approved_fixtures)
                result.ai_reviewed = int(agent_run.reviewed_fixtures)
                result.ai_providers = tuple(agent_run.providers_used)
                result.ai_review_errors = list(agent_run.errors)
                if agent_run.errors:
                    result.errors.extend(agent_run.errors)
                if agent_run.reviewed_fixtures and agent_run.approved_fixtures == 0:
                    logger.warning(
                        "AI review produced 0 approvals: reviewed=%s providers=%s errors=%s",
                        agent_run.reviewed_fixtures,
                        agent_run.providers_used,
                        agent_run.errors,
                    )
            else:
                # Never publish unreviewed predictions.
                for fx in forecast_fx:
                    store.reject_pending_ml_predictions(
                        fixture_id=str(fx.fixture_id),
                        model_version=model_version,
                    )
                if not prediction_agent.configured:
                    result.errors.append("AI review not configured; all new predictions were withheld.")

        result.status = "completed"
        summary = {
            "collected_matches": result.collected_matches,
            "training_rows": result.training_rows,
            "model_trained": result.model_trained,
            "model_version": result.model_version,
            "predictions_created": result.predictions_created,
            "ai_approved": result.ai_approved,
            "ai_reviewed": result.ai_reviewed,
            "ai_providers": list(result.ai_providers),
            "ai_review_errors": result.ai_review_errors or [],
            "settled_predictions": result.settled_predictions,
            "validation_log_loss": result.validation_log_loss,
            "calibration_ece": result.calibration_ece,
            "performance_log_loss": result.performance_log_loss,
            "feature_drift_score": result.feature_drift_score,
            "drift_alert": result.drift_alert,
            "errors": result.errors,
        }
        store.finish_ml_run(run_id, _ts(_now()), "completed", summary, result.errors)
        return result
    except Exception as exc:
        logger.exception("Background ML pipeline failed")
        result.status = "failed"
        result.errors.append(str(exc))
        store.finish_ml_run(
            run_id,
            _ts(_now()),
            "failed",
            {"errors": result.errors, "collected_matches": result.collected_matches},
            result.errors,
        )
        return result


def create_runtime_components() -> tuple[Any, Store, FootballProbabilityEngine, Any]:
    from ..data_providers import build_provider_from_settings
    from .ai_agent import AIPredictionAgent

    provider = build_provider_from_settings(settings)
    store = Store(settings.db_path)
    engine = FootballProbabilityEngine(settings.max_score_goals, rho=settings.dixon_coles_rho)
    agent = AIPredictionAgent(
        engine,
        provider,
        min_confidence=settings.min_selection_confidence,
        gemini_api_key=settings.gemini_api_key,
        gemini_model=settings.gemini_model,
        groq_api_key=settings.groq_api_key,
        groq_model=settings.groq_model,
        # Keep each AI review request small enough for free-tier input limits.
        batch_size=4,
    )
    return provider, store, engine, agent


def main(mode: str = "daily") -> PipelineResult:
    provider, store, engine, agent = create_runtime_components()
    try:
        return run_background_pipeline(
            provider=provider,
            store=store,
            engine=engine,
            prediction_agent=agent,
            mode=mode,
        )
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()
