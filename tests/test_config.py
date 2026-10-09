from __future__ import annotations

from pathlib import Path

from ai_coder.config import load_config

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "config.yaml"


def test_explain_action_in_enabled_actions() -> None:
    """Действие explain должно присутствовать в enabled_actions."""
    cfg = load_config(CONFIG_PATH)

    assert "explain" in cfg.actions
    assert "explain" in cfg.enabled_actions()
    assert cfg.enabled_actions()["explain"].enabled is True
