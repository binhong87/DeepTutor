"""Regression test for the `binding` property on services-layer providers.

T9b added `binding` to deeptutor.tutorbot.providers.* but missed the
parallel hierarchy at deeptutor.services.llm.provider_core.*, which is
what TutorBot actually loads via deeptutor_adapter → provider_factory.
The omission surfaced as a runtime AttributeError when a TutorBot chat
sent attachments. These tests pin the contract on the services-layer
providers so the regression doesn't recur.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_base_llm_provider_has_default_binding():
    from deeptutor.services.llm.provider_core import LLMProvider

    # Smoke check that the property exists at the abstract base level.
    # We can't instantiate LLMProvider directly (it's abstract), so probe
    # the descriptor instead.
    assert isinstance(LLMProvider.__dict__.get("binding"), property)


def test_openai_compat_provider_binding_from_provider_name():
    from deeptutor.services.llm.provider_core import OpenAICompatProvider

    p = OpenAICompatProvider(api_key="x", provider_name="deepseek")
    assert p.binding == "deepseek"


def test_openai_compat_provider_binding_from_spec_when_no_provider_name():
    from deeptutor.services.llm.provider_core import OpenAICompatProvider

    spec = SimpleNamespace(name="openrouter", default_api_base=None, env_key=None, env_extras=())
    p = OpenAICompatProvider(api_key="x", spec=spec)
    assert p.binding == "openrouter"


def test_openai_compat_provider_binding_default_fallback():
    from deeptutor.services.llm.provider_core import OpenAICompatProvider

    p = OpenAICompatProvider(api_key="x")
    assert p.binding == "openai"


def test_anthropic_provider_binding():
    from deeptutor.services.llm.provider_core import AnthropicProvider

    # api_key=None is fine for binding lookup; constructor runs.
    p = AnthropicProvider(api_key="sk-test")
    assert p.binding == "anthropic"


@pytest.mark.parametrize(
    "binding_str,expected_audio,expected_vision",
    [
        ("openai", False, False),    # base default
        ("deepseek", False, False),  # not in capability tables
        ("anthropic", False, True),  # Claude has vision in the existing table
    ],
)
def test_binding_string_routes_through_capability_tables(
    binding_str, expected_audio, expected_vision
):
    """The binding string returned by these providers must be a valid key
    for the multimodal capability gating. We don't assert specific model
    matches — only that the lookup doesn't crash and returns a bool.
    """
    from deeptutor.services.llm.capabilities import supports_audio, supports_vision

    # supports_* return False for unknown bindings, never raise.
    audio = supports_audio(binding_str, "some-model")
    vision = supports_vision(binding_str, "some-model")
    assert isinstance(audio, bool)
    assert isinstance(vision, bool)
