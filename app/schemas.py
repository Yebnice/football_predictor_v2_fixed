from dataclasses import dataclass, field
from typing import Any
from datetime import datetime

@dataclass
class TeamForm:
    matches: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: float = 0.0
    goals_against: float = 0.0

    @property
    def points_per_game(self) -> float:
        return (3*self.wins + self.draws) / self.matches if self.matches else 0.0

    @property
    def goal_diff_per_game(self) -> float:
        return (self.goals_for - self.goals_against) / self.matches if self.matches else 0.0

    @property
    def goals_for_per_game(self) -> float:
        """Per-match attack rate. `goals_for` is stored as a raw sum over
        `matches` fixtures, so this — not `goals_for` itself — is what should
        feed a rate-based model; otherwise widening the form window (e.g.
        last-5 to last-10) silently inflates the estimate."""
        return self.goals_for / self.matches if self.matches else 0.0

    @property
    def goals_against_per_game(self) -> float:
        """Per-match defensive rate. See `goals_for_per_game`."""
        return self.goals_against / self.matches if self.matches else 0.0

@dataclass
class TeamDiscipline:
    """Per-team corners/cards averages, in the same spirit as TeamForm but for
    the corners/cards estimator. Any field left as None falls back to half the
    fixture's league average (a neutral assumption: this team is average)."""
    corners_for_avg: float | None = None
    corners_against_avg: float | None = None
    cards_for_avg: float | None = None
    cards_against_avg: float | None = None

@dataclass
class Fixture:
    fixture_id: str
    date: datetime
    league: str
    season: str
    home_team: str
    away_team: str
    status: str = "scheduled"
    home_score: int | None = None
    away_score: int | None = None
    home_xg: float | None = None
    away_xg: float | None = None
    home_elo: float = 1500.0
    away_elo: float = 1500.0
    home_form: TeamForm = field(default_factory=TeamForm)
    away_form: TeamForm = field(default_factory=TeamForm)
    odds: dict[str, float] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    home_discipline: TeamDiscipline = field(default_factory=TeamDiscipline)
    away_discipline: TeamDiscipline = field(default_factory=TeamDiscipline)
    # Defaults are modeling assumptions, not live league stats: total corners
    # ~9.6 sits between the Premier League's 2026/27 average (8.97) and the
    # Champions League's 2025/26 average (9.7) per FootyStats; total cards
    # ~3.8 reflects the commonly-cited 3.5-4.0 range for competitive top-flight
    # leagues. Override per-fixture when you have real league figures.
    league_avg_corners: float = 9.6
    league_avg_cards: float = 3.8

@dataclass
class MarketPrediction:
    market: str
    selection: str
    probability: float
    fair_odds: float | None
    market_odds: float | None = None
    edge: float | None = None
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class Slip:
    period: str
    slip_number: int
    generated_at: datetime
    selections: list[dict[str, Any]]
    seed: str
