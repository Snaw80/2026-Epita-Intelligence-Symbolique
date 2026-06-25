from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ProviderTests(unittest.TestCase):
    def test_provider_options_include_openai_model_and_optional_mistral(self) -> None:
        from m8_proof_agent.providers import provider_options

        options = provider_options(
            {
                "OPENAI_API_KEY": "openai-key",
                "OPENAI_MODEL": "gpt-test",
                "MISTRAL_API_KEY": "mistral-key",
                "MISTRAL_MODEL": "mistral-test",
            }
        )

        self.assertEqual(
            options,
            [
                {
                    "name": "openai",
                    "label": "OpenAI (gpt-test)",
                    "model": "gpt-test",
                    "configured": True,
                },
                {
                    "name": "mistral",
                    "label": "Mistral (mistral-test)",
                    "model": "mistral-test",
                    "configured": True,
                },
            ],
        )

    def test_provider_options_omit_mistral_without_key(self) -> None:
        from m8_proof_agent.providers import provider_options

        options = provider_options(
            {"OPENAI_API_KEY": "openai-key", "OPENAI_MODEL": "gpt-test"}
        )

        self.assertEqual([option["name"] for option in options], ["openai"])

    def test_get_provider_uses_model_from_environment(self) -> None:
        from m8_proof_agent.providers import get_provider

        provider = get_provider(
            "openai", environ={"OPENAI_API_KEY": "key", "OPENAI_MODEL": "gpt-test"}
        )

        self.assertEqual(provider.name, "openai")
        self.assertEqual(provider.model, "gpt-test")


if __name__ == "__main__":
    unittest.main()
