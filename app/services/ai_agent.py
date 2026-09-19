from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from ..engine import FootballProbabilityEngine, MAX_TIP_PROBABILITY
from ..schemas import Fixture


AGENT_MARKET_LIMIT = 4


@dataclass(frozen=True)
class AgentDecision:
    fixture_id: str
    candidate_index: int
    market: str
    selection: str
    approved: bool
    review_score: float
    rationale: str
    risk_flags: tuple[str, ...] = ()
    reviewers: tuple[str, ...] = ()


@dataclass
class AgentRun:
    decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    reviewed_fixtures: int = 0
    approved_fixtures: int = 0
    deep_reviewed_fixtures: int = 0
    providers_used: tuple[str, ...] = ()
    errors: list[str] = field(default_factory=list)


DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fixture_id": {"type": "string"},
                    "candidate_index": {"type": "integer"},
                    "approved": {"type": "boolean"},
                    "review_score": {"type": "number"},
                    "rationale": {"type": "string"},
                    "risk_flags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "fixture_id",
                    "candidate_index",
                    "approved",
                    "review_score",
                    "rationale",
                    "risk_flags",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["decisions"],
    "additionalProperties": False,
}


def _safe_text(value: Any, limit: int = 600) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _safe_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fixture_summary(fx: Fixture) -> dict[str, Any]:
    return {
        "fixture_id": str(fx.fixture_id),
        "kickoff_utc": fx.date.isoformat(),
        "league": _safe_text(fx.league, 120),
        "season": _safe_text(fx.season, 40),
        "home_team": _safe_text(fx.home_team, 100),
        "away_team": _safe_text(fx.away_team, 100),
        "status": _safe_text(fx.status, 80),
        "home_xg": fx.home_xg,
        "away_xg": fx.away_xg,
        "home_elo": float(fx.home_elo),
        "away_elo": float(fx.away_elo),
        "home_form": {
            "matches": fx.home_form.matches,
            "wins": fx.home_form.wins,
            "draws": fx.home_form.draws,
            "losses": fx.home_form.losses,
            "goals_for_per_game": round(fx.home_form.goals_for_per_game, 3),
            "goals_against_per_game": round(fx.home_form.goals_against_per_game, 3),
        },
        "away_form": {
            "matches": fx.away_form.matches,
            "wins": fx.away_form.wins,
            "draws": fx.away_form.draws,
            "losses": fx.away_form.losses,
            "goals_for_per_game": round(fx.away_form.goals_for_per_game, 3),
            "goals_against_per_game": round(fx.away_form.goals_against_per_game, 3),
        },
        "odds_1x2": {
            key: value
            for key, value in (fx.odds or {}).items()
            if key in {"home", "draw", "away"} and _safe_number(value) is not None
        },
    }


def _compact_provider_payload(payload: Any, limit: int = 1800) -> Any:
    """Keep provider evidence bounded so one match cannot dominate the prompt."""
    if payload is None:
        return None
    if isinstance(payload, (str, int, float, bool)):
        return _safe_text(payload, limit) if isinstance(payload, str) else payload
    if isinstance(payload, list):
        out = []
        for row in payload[:8]:
            out.append(_compact_provider_payload(row, 600))
        return out
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        preferred = (
            "home",
            "away",
            "home_team",
            "away_team",
            "home_score",
            "away_score",
            "date",
            "venue",
            "venue_city",
            "referee",
            "winner",
            "team",
            "player",
            "statistics",
            "odds",
            "status",
            "league",
            "season",
            "id",
            "fixture_id",
        )
        keys = [key for key in preferred if key in payload]
        keys += [key for key in payload if key not in keys]
        for key in keys[:18]:
            value = payload.get(key)
            if isinstance(value, (dict, list)):
                out[str(key)] = _compact_provider_payload(value, 700)
            else:
                out[str(key)] = _safe_text(value, 500) if isinstance(value, str) else value
        return out
    return _safe_text(payload, limit)


class AIPredictionAgent:
    """Agentic review layer over the deterministic football probability model.

    The agent never invents a market or probability. The statistical engine
    creates the candidate markets; this service gathers additional provider
    evidence, asks the configured AI model(s) to review those candidates, and
    returns only validated selections that exist in the original candidate set.
    """

    def __init__(
        self,
        engine: FootballProbabilityEngine,
        provider: Any,
        *,
        min_confidence: float = 0.60,
        gemini_api_key: str = "",
        gemini_model: str = "gemini-3.8-flash",
        groq_api_key: str = "",
        groq_model: str = "openai/gpt-oss-120b",
        batch_size: int = 30,
    ):
        self.engine = engine
        self.provider = provider
        self.min_confidence = float(min_confidence)
        self.gemini_api_key = (gemini_api_key or "").strip()
        self.gemini_model = (gemini_model or "gemini-3.8-flash").strip()
        self.groq_api_key = (groq_api_key or "").strip()
        self.groq_model = (groq_model or "openai/gpt-oss-120b").strip()
        self.batch_size = max(5, int(batch_size))
        self.last_run = AgentRun()

        self._gemini_client = None
        self._groq_client = None

        if self.gemini_api_key:
            try:
                from google import genai
                self._gemini_client = genai.Client(api_key=self.gemini_api_key)
            except Exception:
                self._gemini_client = None

        if self.groq_api_key:
            try:
                from groq import Groq
                self._groq_client = Groq(api_key=self.groq_api_key)
            except Exception:
                self._groq_client = None

    @property
    def configured(self) -> bool:
        return bool(self._gemini_client or self._groq_client)

    @staticmethod
    def _candidate_payload(engine: FootballProbabilityEngine, fx: Fixture) -> list[dict[str, Any]]:
        candidates = engine.shortlist(
            fx,
            min_conf=0.0,
            top_n=AGENT_MARKET_LIMIT,
            max_conf=MAX_TIP_PROBABILITY,
        )
        # The engine ranks by market edge when bookmaker odds are available;
        # otherwise it ranks by coherent statistical probability.
        out = []
        for index, candidate in enumerate(candidates):
            out.append({
                "candidate_index": index,
                "market": candidate.market,
                "selection": candidate.selection,
                "model_probability": round(float(candidate.probability), 4),
                "fair_odds": candidate.fair_odds,
                "market_odds": candidate.market_odds,
                "edge": candidate.edge,
            })
        return out

    def _build_records(
        self,
        fixtures: Iterable[Fixture],
        candidate_limit: int,
        deep_evidence_limit: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Fixture]]:
        unique: dict[str, Fixture] = {}
        for fx in fixtures:
            fixture_id = str(getattr(fx, "fixture_id", "") or "")
            if fixture_id:
                unique.setdefault(fixture_id, fx)

        rows: list[dict[str, Any]] = []
        for fx in unique.values():
            candidates = [
                row for row in self._candidate_payload(self.engine, fx)
                if self.min_confidence <= float(row["model_probability"]) <= MAX_TIP_PROBABILITY
            ]
            if not candidates:
                continue
            rows.append({
                "fixture": _fixture_summary(fx),
                "candidates": candidates,
                "deep_evidence": {},
            })

        rows.sort(
            key=lambda row: (
                max(float(c["model_probability"]) for c in row["candidates"]),
                row["fixture"]["kickoff_utc"],
            ),
            reverse=True,
        )
        rows = rows[: max(0, int(candidate_limit))]

        by_id = {row["fixture"]["fixture_id"]: unique[row["fixture"]["fixture_id"]] for row in rows}

        for row in rows[: max(0, int(deep_evidence_limit))]:
            fixture_id = row["fixture"]["fixture_id"]
            fx = by_id[fixture_id]
            row["deep_evidence"] = self._deep_evidence(fx)

        return rows, by_id

    def _deep_evidence(self, fx: Fixture) -> dict[str, Any]:
        evidence: dict[str, Any] = {}

        try:
            detailed = self.provider.fixture_by_id(fx.fixture_id)
            if detailed:
                evidence["fixture_details_normalized"] = _fixture_summary(detailed)
                evidence["fixture_stats"] = _compact_provider_payload(detailed.stats, 1400)
                evidence["odds_1x2"] = {
                    key: value for key, value in (detailed.odds or {}).items()
                    if key in {"home", "draw", "away"}
                }
                evidence["provider"] = (detailed.stats or {}).get("provider")
        except Exception as exc:
            evidence["fixture_by_id_error"] = _safe_text(exc, 250)

        try:
            raw_details = self.provider.fixture_details(fx.fixture_id)
            if raw_details:
                evidence["fixture_details"] = _compact_provider_payload(raw_details, 1200)
        except Exception:
            pass

        stats = fx.stats or {}
        home_id = stats.get("home_team_id")
        away_id = stats.get("away_team_id")
        if home_id and away_id:
            try:
                h2h = self.provider.head_to_head(home_id, away_id, limit=5)
                if h2h:
                    evidence["head_to_head_last5"] = _compact_provider_payload(h2h, 1300)
            except Exception:
                pass

        # Pre-match lineups are often unavailable; only query them when the
        # provider reports a state where lineup data is meaningful.
        status = str(fx.status or "").casefold()
        if status not in {"scheduled", "not started", "ns", ""}:
            try:
                lineups = self.provider.lineups(fx.fixture_id)
                if lineups:
                    evidence["lineups"] = _compact_provider_payload(lineups, 1200)
            except Exception:
                pass

        return evidence

    @staticmethod
    def _prompt(records: list[dict[str, Any]]) -> str:
        return (
            "You are an AI football prediction review agent. Review the supplied "
            "fixtures using only the deterministic model candidates and the factual "
            "provider evidence included below. Your job is to approve or reject one "
            "existing candidate per fixture. You are NOT allowed to invent a market, "
            "selection, fixture, injury, lineup, odds value, or probability. "
            "candidate_index must point to an item in that fixture's candidate list. "
            "A review_score is your confidence in the review decision, NOT the event "
            "probability. The statistical model probability is the authoritative "
            "quantitative input. Prefer rejection over a speculative approval when "
            "the evidence contradicts the candidate, but do not reject solely because "
            "optional deep evidence is unavailable; instead record that limitation in "
            "risk_flags. Return one decision for every fixture presented.\n\n"
            + json.dumps(records, ensure_ascii=False, default=str)
        )

    @staticmethod
    def _parse(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            rows = payload.get("decisions", [])
        elif isinstance(payload, list):
            rows = payload
        else:
            return []
        return [row for row in rows if isinstance(row, dict)]

    def _review_with_gemini(self, prompt: str) -> list[dict[str, Any]]:
        if not self._gemini_client:
            return []
        from google.genai import types

        config_kwargs: dict[str, Any] = {
            "max_output_tokens": 6000,
            "response_mime_type": "application/json",
            "response_schema": DECISION_SCHEMA,
        }
        try:
            medium_level = getattr(types.ThinkingLevel, "MEDIUM", "medium")
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=medium_level
            )
        except (AttributeError, TypeError):
            pass

        response = self._gemini_client.models.generate_content(
            model=self.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        raw = (getattr(response, "text", "") or "").strip()
        return self._parse(json.loads(raw)) if raw else []

    def _review_with_groq(self, prompt: str) -> list[dict[str, Any]]:
        if not self._groq_client:
            return []

        response_format: dict[str, Any] = {
            "type": "json_schema",
            "json_schema": {
                "name": "football_prediction_review",
                "strict": self.groq_model in {
                    "openai/gpt-oss-20b",
                    "openai/gpt-oss-120b",
                    "qwen/qwen3.8-27b",
                },
                "schema": DECISION_SCHEMA,
            },
        }
        request_kwargs = {
            "model": self.groq_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a structured football prediction review agent. "
                        "Return JSON only and never invent facts."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": response_format,
            "temperature": 0.1,
            "max_tokens": 6000,
        }
        # reasoning_effort is documented for GPT-OSS models. Do not send it
        # to arbitrary custom Groq model IDs configured by a deployment.
        if self.groq_model.startswith("openai/gpt-oss-"):
            request_kwargs["reasoning_effort"] = "medium"
        response = self._groq_client.chat.completions.create(**request_kwargs)
        raw = (response.choices[0].message.content or "").strip()
        return self._parse(json.loads(raw)) if raw else []

    @staticmethod
    def _validate_model_decisions(
        rows: list[dict[str, Any]],
        records: list[dict[str, Any]],
        reviewer: str,
    ) -> dict[str, AgentDecision]:
        allowed = {
            str(row["fixture"]["fixture_id"]): row["candidates"]
            for row in records
        }
        out: dict[str, AgentDecision] = {}

        for row in rows:
            fixture_id = str(row.get("fixture_id", "") or "")
            if fixture_id not in allowed:
                continue
            try:
                candidate_index = int(row.get("candidate_index"))
            except (TypeError, ValueError):
                continue
            candidates = allowed[fixture_id]
            if not 0 <= candidate_index < len(candidates):
                continue
            candidate = candidates[candidate_index]
            approved = bool(row.get("approved"))
            try:
                review_score = max(0.0, min(1.0, float(row.get("review_score", 0.0))))
            except (TypeError, ValueError):
                review_score = 0.0
            rationale = _safe_text(row.get("rationale"), 900)
            risk_flags = tuple(
                _safe_text(flag, 180)
                for flag in (row.get("risk_flags") or [])
                if _safe_text(flag, 180)
            )
            out[fixture_id] = AgentDecision(
                fixture_id=fixture_id,
                candidate_index=candidate_index,
                market=str(candidate["market"]),
                selection=str(candidate["selection"]),
                approved=approved,
                review_score=review_score,
                rationale=rationale,
                risk_flags=risk_flags,
                reviewers=(reviewer,),
            )
        return out

    @staticmethod
    def _merge_decisions(
        gemini: dict[str, AgentDecision],
        groq: dict[str, AgentDecision],
        records: list[dict[str, Any]],
    ) -> dict[str, AgentDecision]:
        by_id = {str(row["fixture"]["fixture_id"]): row for row in records}
        merged: dict[str, AgentDecision] = {}

        for fixture_id in by_id:
            g = gemini.get(fixture_id)
            q = groq.get(fixture_id)
            choices = [x for x in (g, q) if x is not None]

            if not choices:
                continue
            approved = [x for x in choices if x.approved]
            if not approved:
                # Preserve the strongest explicit rejection for diagnostics.
                best = max(choices, key=lambda x: x.review_score)
                merged[fixture_id] = best
                continue

            # Deterministic arbiter: the AI layer can reject or switch the
            # supported market, but quantitative ranking remains model-first.
            candidate_map = {
                (x.market, x.selection): x for x in approved
            }
            winner = max(
                candidate_map.values(),
                key=lambda x: (
                    float(
                        next(
                            (
                                c["model_probability"]
                                for c in by_id[fixture_id]["candidates"]
                                if c["candidate_index"] == x.candidate_index
                            ),
                            0.0,
                        )
                    ),
                    x.review_score,
                ),
            )
            reviewer_names = tuple(
                sorted({name for x in choices for name in x.reviewers})
            )
            merged[fixture_id] = AgentDecision(
                fixture_id=winner.fixture_id,
                candidate_index=winner.candidate_index,
                market=winner.market,
                selection=winner.selection,
                approved=True,
                review_score=winner.review_score,
                rationale=winner.rationale,
                risk_flags=winner.risk_flags,
                reviewers=reviewer_names,
            )

        return merged

    def review_fixtures(
        self,
        fixtures: Iterable[Fixture],
        *,
        candidate_limit: int = 60,
        deep_evidence_limit: int = 20,
    ) -> AgentRun:
        records, _ = self._build_records(
            fixtures,
            candidate_limit=max(1, int(candidate_limit)),
            deep_evidence_limit=max(0, int(deep_evidence_limit)),
        )
        run = AgentRun(
            reviewed_fixtures=len(records),
            deep_reviewed_fixtures=min(len(records), max(0, int(deep_evidence_limit))),
        )

        if not records:
            self.last_run = run
            return run

        if not self.configured:
            run.errors.append("No AI provider is configured.")
            self.last_run = run
            return run

        batches = [
            records[index:index + self.batch_size]
            for index in range(0, len(records), self.batch_size)
        ]

        merged_all: dict[str, AgentDecision] = {}

        for batch_number, batch in enumerate(batches, start=1):
            prompt = self._prompt(batch)
            gemini_rows: list[dict[str, Any]] = []
            groq_rows: list[dict[str, Any]] = []

            if self._gemini_client:
                try:
                    gemini_rows = self._review_with_gemini(prompt)
                    if gemini_rows:
                        run.providers_used = tuple(sorted(set(run.providers_used + ("gemini",))))
                except Exception as exc:
                    run.errors.append(f"Gemini batch {batch_number}: {_safe_text(exc, 260)}")

            if self._groq_client:
                try:
                    groq_rows = self._review_with_groq(prompt)
                    if groq_rows:
                        run.providers_used = tuple(sorted(set(run.providers_used + ("groq",))))
                except Exception as exc:
                    run.errors.append(f"Groq batch {batch_number}: {_safe_text(exc, 260)}")

            gemini = self._validate_model_decisions(gemini_rows, batch, "gemini")
            groq = self._validate_model_decisions(groq_rows, batch, "groq")
            merged_all.update(self._merge_decisions(gemini, groq, batch))

        for fixture_id, decision in merged_all.items():
            if decision.approved:
                run.decisions[fixture_id] = {
                    "market": decision.market,
                    "selection": decision.selection,
                    "approved": True,
                    "review_score": round(decision.review_score, 4),
                    "rationale": decision.rationale,
                    "risk_flags": list(decision.risk_flags),
                    "reviewers": list(decision.reviewers),
                }

        run.approved_fixtures = len(run.decisions)
        self.last_run = run
        return run
