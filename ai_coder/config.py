from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------- api ----------


class PricePair(BaseModel):
    off_peak: float
    peak: float

    def get(self, is_peak: bool) -> float:
        return self.peak if is_peak else self.off_peak


class ModelPricing(BaseModel):
    cache_hit_per_1m_cny: PricePair
    cache_miss_per_1m_cny: PricePair
    output_per_1m_cny: PricePair


class PeakWindow(BaseModel):
    start: str  # "HH:MM"
    end: str  # "HH:MM"

    @field_validator("start", "end")
    @classmethod
    def _check_time(cls, v: str) -> str:
        h, m = v.split(":")
        assert 0 <= int(h) < 24 and 0 <= int(m) < 60, f"bad time: {v}"
        return v


class PeakSchedule(BaseModel):
    timezone: str = "UTC"
    weekdays_only: bool = True
    windows: list[PeakWindow] = Field(default_factory=list)
    display_timezone: str = "Europe/Moscow"


class ApiConfig(BaseModel):
    base_url: str
    api_key_env: str
    model: str
    models: list[str]
    temperature: float = 0.3
    max_output_tokens: int = 8000
    timeout_sec: int = 120
    retries: int = 3
    pricing: dict[str, ModelPricing]
    peak_schedule: PeakSchedule

    @field_validator("model")
    @classmethod
    def _check_default_model(cls, v: str, info) -> str:
        models = info.data.get("models") or []
        if models and v not in models:
            raise ValueError(f"default model '{v}' not in models list {models}")
        return v

    def api_key(self) -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise RuntimeError(
                f"Переменная окружения {self.api_key_env} не задана. Установите API-ключ DeepSeek."
            )
        return key

    def pricing_for(self, model: str) -> ModelPricing:
        if model not in self.pricing:
            raise KeyError(f"Нет цен для модели '{model}' в конфиге")
        return self.pricing[model]


# ---------- currency ----------


class CurrencyPair(BaseModel):
    fetch_online: bool = True
    source: str = "cbr"
    fallback: float
    cache_hours: int = 24


class CurrencyConfig(BaseModel):
    cny_to_rub: CurrencyPair
    usd_to_rub: CurrencyPair


# ---------- scanning ----------


class ScanningConfig(BaseModel):
    use_gitignore: bool = True
    extra_ignore: list[str] = Field(default_factory=list)
    secret_ignore: list[str] = Field(default_factory=list)
    binary_extensions: list[str] = Field(default_factory=list)
    max_file_size_kb: int = 500
    max_total_tokens: int = 60000
    include_extensions: list[str] = Field(default_factory=list)
    only_paths: list[str] = Field(default_factory=list)

    @field_validator("binary_extensions")
    @classmethod
    def _normalize_ext(cls, v: list[str]) -> list[str]:
        return [e if e.startswith(".") else f".{e}" for e in (e.lower() for e in v)]


# ---------- output / usage ----------


class OutputConfig(BaseModel):
    dir: str = ".ai-out"
    per_project_subdir: bool = True
    filename_pattern: str = "{action}-{timestamp}.md"
    save_raw_response: bool = True
    use_cache: bool = True  # по умолчанию кэш включён
    cache_dir_name: str = "cache"


class UsageConfig(BaseModel):
    jsonl: str = ".ai-out/usage.jsonl"
    summary: str = ".ai-out/usage_summary.json"
    per_project: bool = True


# ---------- write (ДО AppConfig!) ----------


class WriteConfig(BaseModel):
    max_operations: int = 20
    blacklist_paths: list[str] = Field(default_factory=list)
    blacklist_files: list[str] = Field(default_factory=list)
    verify_after_apply: bool = True
    backup_dir_name: str = "backup"


class FixConfig(BaseModel):
    max_attempts: int = 3
    prompt: str = "fix_errors_json"


class GitConfig(BaseModel):
    """Настройки git-интеграции агента."""

    enabled: bool = True
    require_clean: bool = True  # проверять чистоту перед --apply
    auto_commit: bool = False  # коммитить после --apply (дефолт для флага)
    commit_template: str = "ai-coder: {goal_short} ({ops} ops, {cost_rub:.2f} RUB)"


# ---------- actions ----------

ActionMode = Literal["read", "write"]

# Расширения «вёрстки» — для авто-исключения в greet/inventory/write_readme.
# Агент по умолчанию их видит, `--exclude-web` — исключает.
WEB_ASSET_EXTENSIONS: tuple[str, ...] = (
    "*.html",
    "*.htm",
    "*.css",
    "*.scss",
    "*.less",
    "*.js",
    "*.jsx",
    "*.ts",
    "*.tsx",
    "*.mjs",
    "*.cjs",
    "*.vue",
    "*.svelte",
    "*.svg",
)


class ActionConfig(BaseModel):
    description: str
    prompt: str
    mode: ActionMode = "read"
    enabled: bool = True
    max_output_tokens: int | None = None
    temperature: float | None = None
    exclude_web_assets: bool = False


# ---------- subagents (Направление 12, D4) ----------

# Имя subagent'а: нижний регистр, цифры, дефис. Нижний регистр — чтобы
# LLM не путал регистр в args.name.
_SUBAGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")


class SubagentConfig(BaseModel):
    """Описание subagent'а, которого родитель может вызвать (spawn_subagent)."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    tools: list[str]
    model: str | None = None  # None → cfg.api.model
    max_iterations: int = Field(5, ge=1, le=30)
    instructions: str | None = None  # доп. инструкция в user-промпт (НЕ system)
    max_cost_rub: float | None = Field(None, gt=0)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not _SUBAGENT_NAME_RE.match(v):
            raise ValueError(f"subagent.name {v!r} не соответствует ^[a-z][a-z0-9-]{{1,30}}$")
        return v

    @field_validator("tools")
    @classmethod
    def _validate_tools(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("subagent.tools не может быть пустым")
        # depth = 1: subagent НЕ может вызывать subagent'ов.
        if "spawn_subagent" in v:
            raise ValueError("spawn_subagent нельзя включать в tools subagent'а (depth=1)")
        # Ленивый импорт: config → tools → scanner → config был бы циклом.
        from .tools import TOOL_REGISTRY

        unknown = sorted(t for t in v if t not in TOOL_REGISTRY)
        if unknown:
            raise ValueError(f"неизвестные инструменты в subagent.tools: {unknown}")
        return v


class AgentConfig(BaseModel):
    max_steps: int = 10
    max_minutes: int = 30
    verify_commands: list[str] = Field(default_factory=list)
    verify_timeout_sec: int = 60
    verify_max_output_chars: int = 10_000
    stop_on_verify_failure: bool = True
    step_max_output_tokens: int = 8000
    include_read_steps: bool = False
    auto_only_paths: bool = True
    phase1_enabled: bool = True  # NEW
    phase1_max_output_tokens: int = 2000  # NEW
    tool_loop_history_max_chars: int = 10_000
    tool_loop_history_other_max_chars: int = 500
    decompose_model: str | None = None
    split_goals_model: str | None = None  # NEW: модель для --split-goals
    decompose_replan: bool = False
    decompose_rollback_on_fail: bool = False
    reverse_check_model: str | None = None  # NEW: модель для --reverse-check
    reverse_check_max_diff_chars: int = 15000  # NEW: обрезка diff
    decompose_reverse_check: bool = False
    feedback_enabled: bool = True  # NEW: feedback-loop между подзадачами
    feedback_max_subtasks: int = 7  # NEW: сколько предыдущих подзадач включать
    subagents: list[SubagentConfig] = Field(default_factory=list)  # NEW (D4)
    subagent_max_per_task: int = Field(3, ge=1)  # NEW: spawn на один tool loop
    subagent_max_total_cost_rub: float = Field(3.0, gt=0)  # NEW: на все spawn
    subagent_default_max_cost_rub: float = Field(1.5, gt=0)  # NEW: один spawn

    @model_validator(mode="after")
    def _validate_subagents(self) -> AgentConfig:
        names = [s.name for s in self.subagents]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"дубликаты имён subagents: {dupes}")
        return self


# ---------- root ----------


class AppConfig(BaseModel):
    """Корневой конфиг приложения, объединяющий все секции config.yaml."""

    api: ApiConfig
    currency: CurrencyConfig
    scanning: ScanningConfig
    output: OutputConfig
    usage: UsageConfig
    write: WriteConfig
    fix: FixConfig
    git: GitConfig
    agent: AgentConfig  # ← NEW
    actions: dict[str, ActionConfig]

    def enabled_actions(self) -> dict[str, ActionConfig]:
        return {k: v for k, v in self.actions.items() if v.enabled}

    @model_validator(mode="after")
    def _validate_subagent_models(self) -> AppConfig:
        # Цены живут в api, а subagents — в agent: проверять можно только тут.
        # pricing_for() бросает KeyError в рантайме — ловим на старте.
        for s in self.agent.subagents:
            if s.model and s.model not in self.api.pricing:
                raise ValueError(f"subagent '{s.name}': нет цен для модели '{s.model}'")
        return self


# ---------- prompts ----------


class PromptEntry(BaseModel):
    system: str
    user: str


class PromptsConfig(BaseModel):
    prompts: dict[str, PromptEntry]

    def get(self, name: str) -> PromptEntry:
        if name not in self.prompts:
            raise KeyError(f"Промпт '{name}' не найден в prompts.yaml")
        return self.prompts[name]


# ---------- загрузка ----------


def _read_yaml(path: Path) -> dict[str, Any]:
    """Читает YAML-файл и гарантирует, что результатом является словарь."""
    if not path.exists():
        raise FileNotFoundError(f"Конфиг не найден: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Ожидался словарь в {path}, получено {type(data).__name__}")
    return data


def load_config(path: str | Path) -> AppConfig:
    """Загружает и валидирует основной конфиг приложения (config.yaml)."""
    data = _read_yaml(Path(path))
    return AppConfig.model_validate(data)


def load_prompts(path: str | Path) -> PromptsConfig:
    raw = _read_yaml(Path(path))
    if "prompts" in raw and isinstance(raw["prompts"], dict):
        payload = raw
    else:
        payload = {"prompts": raw}
    return PromptsConfig.model_validate(payload)
