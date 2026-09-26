from __future__ import annotations

from app.config import Settings


def test_text_layer_is_optional_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HEXA_REQUIRE_TEXT_LAYER", raising=False)

    settings = Settings.from_env()

    assert settings.require_text_layer is False


def test_text_layer_can_be_required_explicitly(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HEXA_REQUIRE_TEXT_LAYER", "1")

    settings = Settings.from_env()

    assert settings.require_text_layer is True
