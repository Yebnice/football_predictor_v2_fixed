from __future__ import annotations
from typing import Any

class GroqExplainer:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.client = None
        if api_key:
            from groq import Groq
            self.client = Groq(api_key=api_key)

    def explain(self, match: dict[str, Any], shortlist: list[dict[str, Any]]) -> str:
        if not self.client:
            return "Groq is not configured. Statistical probabilities are still available."
        prompt = (
            "You are the explanation layer of a football analytics application. "
            "Do not claim certainty, guaranteed wins, or insider information. "
            "Explain the strongest markets using the supplied model outputs only. "
            f"Match: {match}\nMarkets: {shortlist}"
        )
        r = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=450,
            reasoning_effort="low",
            include_reasoning=False,
        )
        return r.choices[0].message.content or "No explanation generated."
