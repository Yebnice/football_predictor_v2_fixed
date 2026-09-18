import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from app.services.ai_gemini import GeminiExplainer


class TestGeminiExplainer(unittest.TestCase):
    def test_unconfigured(self):
        self.assertIn("not configured", GeminiExplainer("").explain({}, []))

    def test_uses_documented_gemini_flash_config(self):
        google = types.ModuleType("google")
        genai = types.ModuleType("google.genai")
        genai_types = types.ModuleType("google.genai.types")

        class ThinkingLevel:
            MEDIUM = "MEDIUM"

        class ThinkingConfig:
            def __init__(self, thinking_level):
                self.thinking_level = thinking_level

        class GenerateContentConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        genai_types.ThinkingLevel = ThinkingLevel
        genai_types.ThinkingConfig = ThinkingConfig
        genai_types.GenerateContentConfig = GenerateContentConfig

        class Client:
            def __init__(self, api_key):
                self.api_key = api_key
                self.models = MagicMock()

        genai.Client = Client
        google.genai = genai

        with patch.dict(sys.modules, {
            "google": google,
            "google.genai": genai,
            "google.genai.types": genai_types,
        }):
            service = GeminiExplainer("test-key")
            response = MagicMock()
            response.text = "ok"
            service.client.models.generate_content.return_value = response

            self.assertEqual(
                service.explain({"home_team": "A", "away_team": "B"}, []),
                "ok",
            )
            kwargs = service.client.models.generate_content.call_args.kwargs
            self.assertEqual(kwargs["model"], "gemini-3.8-flash")
            self.assertEqual(
                kwargs["config"].kwargs["thinking_config"].thinking_level,
                "MEDIUM",
            )
            self.assertEqual(kwargs["config"].kwargs["max_output_tokens"], 1200)


if __name__ == "__main__":
    unittest.main()
