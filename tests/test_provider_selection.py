from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


PLUGIN_MAIN_PATH = Path(__file__).resolve().parents[1] / "main.py"
MODULE_SPEC = importlib.util.spec_from_file_location(
    "astrbot_plugin_anti_porn_main",
    PLUGIN_MAIN_PATH,
)
assert MODULE_SPEC and MODULE_SPEC.loader
PLUGIN_MODULE = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(PLUGIN_MODULE)
AntiPorn = PLUGIN_MODULE.AntiPorn


class FakeProvider:
    def __init__(self, response_text: str, provider_config: dict | None = None) -> None:
        self.response_text = response_text
        self.provider_config = provider_config or {}
        self.calls: list[dict] = []

    async def text_chat(self, *args, **kwargs):
        call = dict(kwargs)
        if args:
            call["prompt"] = args[0]
        self.calls.append(call)
        return SimpleNamespace(completion_text=self.response_text)


class FakeContext:
    def __init__(
        self,
        *,
        default_provider: FakeProvider | None,
        providers: dict[str, FakeProvider] | None = None,
    ) -> None:
        self.default_provider = default_provider
        self.providers = providers or {}
        self.get_provider_by_id_calls: list[str] = []

    def get_provider_by_id(self, provider_id: str):
        self.get_provider_by_id_calls.append(provider_id)
        return self.providers.get(provider_id)

    def get_using_provider(self):
        return self.default_provider


class FakeEvent:
    def __init__(self, sender_id: str = "42") -> None:
        self.sender_id = sender_id

    def get_sender_id(self) -> str:
        return self.sender_id


def build_plugin(config: dict, context: FakeContext) -> AntiPorn:
    plugin = AntiPorn.__new__(AntiPorn)
    plugin.config = config
    plugin.context = context
    return plugin


@pytest.mark.asyncio
async def test_llm_censor_uses_configured_provider_id() -> None:
    default_provider = FakeProvider("No")
    moderation_provider = FakeProvider("Yes")
    context = FakeContext(
        default_provider=default_provider,
        providers={"cheap-review": moderation_provider},
    )
    plugin = build_plugin(
        {
            "llm_censor_probability": 1,
            "text_censor_provider_id": "cheap-review",
        },
        context,
    )

    result = await plugin._llm_censor_check(FakeEvent(), "test message")

    assert result is True
    assert context.get_provider_by_id_calls == ["cheap-review"]
    assert len(moderation_provider.calls) == 1
    assert default_provider.calls == []


@pytest.mark.asyncio
async def test_llm_censor_falls_back_to_default_provider_when_configured_provider_missing() -> None:
    default_provider = FakeProvider("Yes")
    context = FakeContext(default_provider=default_provider)
    plugin = build_plugin(
        {
            "llm_censor_probability": 1,
            "text_censor_provider_id": "missing-provider",
        },
        context,
    )

    result = await plugin._llm_censor_check(FakeEvent(), "test message")

    assert result is True
    assert context.get_provider_by_id_calls == ["missing-provider"]
    assert len(default_provider.calls) == 1


@pytest.mark.asyncio
async def test_image_censor_uses_configured_provider_id() -> None:
    default_provider = FakeProvider("No", {"modalities": ["image"]})
    image_provider = FakeProvider("Yes", {"modalities": ["image"]})
    context = FakeContext(
        default_provider=default_provider,
        providers={"vision-review": image_provider},
    )
    plugin = build_plugin(
        {
            "image_censor_probability": 1,
            "image_censor_provider_id": "vision-review",
        },
        context,
    )

    result = await plugin._llm_image_censor_check(
        FakeEvent(),
        ["https://example.com/image.png"],
    )

    assert result is True
    assert context.get_provider_by_id_calls == ["vision-review"]
    assert len(image_provider.calls) == 1
    assert default_provider.calls == []


@pytest.mark.asyncio
async def test_image_censor_falls_back_to_default_provider_when_not_configured() -> None:
    default_provider = FakeProvider("No", {"modalities": ["image"]})
    context = FakeContext(default_provider=default_provider)
    plugin = build_plugin(
        {
            "image_censor_probability": 1,
        },
        context,
    )

    result = await plugin._llm_image_censor_check(
        FakeEvent(),
        ["https://example.com/image.png"],
    )

    assert result is False
    assert context.get_provider_by_id_calls == []
    assert len(default_provider.calls) == 1
