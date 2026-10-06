from __future__ import annotations

from pathlib import Path

import pytest

from ai_coder.config import (
    AgentConfig, 
    AppConfig,
    ApiConfig,
    CurrencyConfig,
    CurrencyPair,
    FixConfig,
    ModelPricing,
    OutputConfig,
    PeakSchedule,
    PeakWindow,
    PricePair,
    PromptsConfig,
    PromptEntry,
    ScanningConfig,
    UsageConfig,
    WriteConfig,
)


@pytest.fixture
def minimal_pricing() -> dict[str, ModelPricing]:
    """Одна модель с простыми ценами для тестов."""
    return {
        "test-model": ModelPricing(
            cache_hit_per_1m_cny=PricePair(off_peak=0.02, peak=0.04),
            cache_miss_per_1m_cny=PricePair(off_peak=1.0, peak=2.0),
            output_per_1m_cny=PricePair(off_peak=4.0, peak=8.0),
        ),
    }


@pytest.fixture
def minimal_cfg(minimal_pricing) -> AppConfig:
    """Минимальный AppConfig для тестов, без чтения YAML."""
    return AppConfig(
        api=ApiConfig(
            base_url="https://api.deepseek.com",
            api_key_env="DUMMY_KEY",
            model="test-model",
            models=["test-model"],
            temperature=0.3,
            max_output_tokens=8000,
            timeout_sec=10,
            retries=1,
            pricing=minimal_pricing,
            peak_schedule=PeakSchedule(
                timezone="UTC",
                weekdays_only=True,
                windows=[
                    PeakWindow(start="01:00", end="04:00"),
                    PeakWindow(start="06:00", end="10:00"),
                ],
                display_timezone="Europe/Moscow",
            ),
        ),
        currency=CurrencyConfig(
            cny_to_rub=CurrencyPair(fetch_online=False, fallback=12.5, cache_hours=24),
            usd_to_rub=CurrencyPair(fetch_online=False, fallback=92.0, cache_hours=24),
        ),
        scanning=ScanningConfig(
            use_gitignore=True,
            extra_ignore=[".venv/**", "__pycache__/**", ".git/**", ".ai-out/**"],
            secret_ignore=["*.env", "*secret*"],
            binary_extensions=[".png", ".jpg"],
            max_file_size_kb=500,
            max_total_tokens=60000,
            include_extensions=[],
        ),
        output=OutputConfig(
            dir=".ai-out",
            per_project_subdir=True,
            filename_pattern="{action}-{timestamp}.md",
            save_raw_response=False,
            use_cache=True,
            cache_dir_name="cache",
        ),
        usage=UsageConfig(
            jsonl=".ai-out/usage.jsonl",
            summary=".ai-out/usage_summary.json",
            per_project=True,
        ),
        write=WriteConfig(
            max_operations=20,
            blacklist_paths=[".git/**", ".ai-out/**", "*.key", "*.pem"],
            blacklist_files=["pyproject.toml", "config/config.yaml"],
            verify_after_apply=True,
            backup_dir_name="backup",
        ),
        fix=FixConfig(max_attempts=3, prompt="fix_errors_json"),
        agent=AgentConfig(
            max_steps=10,
            max_minutes=30,
            verify_commands=[],
            stop_on_verify_failure=True,
            include_read_steps=False,
        ),
        actions={},
    )


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    """
    Создаёт временный проект с типичной структурой и .gitignore.
    Возвращает путь к корню проекта.
    """
    root = tmp_path / "sample"
    root.mkdir()

    # .gitignore
    (root / ".gitignore").write_text(
        "node_modules/\n*.log\nbuild/\n",
        encoding="utf-8",
    )

    # исходники
    src = root / "src"
    src.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "main.py").write_text(
        'def hello():\n    return "world"\n',
        encoding="utf-8",
    )
    (src / "utils.py").write_text(
        "def add(a, b):\n    return a + b\n",
        encoding="utf-8",
    )

    # служебные
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "main.cpython-311.pyc").write_bytes(b"\x00\x01\x02")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "index.js").write_text("console.log('x')", encoding="utf-8")

    # секретный файл
    (root / ".env").write_text("SECRET=abc", encoding="utf-8")
    (root / "credentials.json").write_text('{"key": "value"}', encoding="utf-8")

    # бинарник
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    # README
    (root / "README.md").write_text("# sample\n", encoding="utf-8")

    return root


@pytest.fixture
def prompts_cfg() -> PromptsConfig:
    """Минимальный PromptsConfig — набор промптов для тестов."""
    return PromptsConfig(
        prompts={
            "greet": PromptEntry(system="S", user="U"),
            "fix": PromptEntry(system="S", user="U"),
        }
    )
