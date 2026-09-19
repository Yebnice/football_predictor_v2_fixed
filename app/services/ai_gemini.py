from __future__ import annotations
from typing import Any


class GeminiExplainer:
    """Google Gemini Flash explanation layer for football match analysis."""

    def __init__(self, api_key: str, model: str = "gemini-3.8-flash"):
        self.api_key = (api_key or "").strip()
        self.model = (model or "gemini-3.8-flash").strip()
        self.client = None
        if self.api_key:
            from google import genai
            self.client = genai.Client(api_key=self.api_key)

    def explain(self, match: dict[str, Any], shortlist: list[dict[str, Any]]) -> str:
        if not self.client:
            return "Gemini is not configured. Statistical probabilities are still available."

        prompt = (
            "You are the Gemini explanation layer of a football analytics application. "
            "Use only the supplied match data and model markets. "
            "Do not claim certainty, guaranteed wins, insider information, or knowledge "
            "of future events. Explain the strongest markets, key supporting signals, "
            "and important uncertainty in concise, practical language. "
            f"Match: {match}\nMarkets: {shortlist}"
        )

        from google.genai import types

        config_kwargs: dict[str, Any] = {"max_output_tokens": 900}
        # The Google GenAI SDK has changed the ThinkingLevel enum across
        # releases. Use LOW when that enum exists, otherwise omit the optional
        # thinking setting so text generation remains compatible.
        try:
            low_level = getattr(types.ThinkingLevel, "LOW", None)
            if low_level is not None:
                config_kwargs["thinking_config"] = types.ThinkingConfig(
                    thinking_level=low_level
                )
        except (AttributeError, TypeError):
            pass

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        return (response.text or "").strip() or "No Gemini explanation generated."
