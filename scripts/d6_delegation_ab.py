"""D6 #3: A/B делегирования `spawn_subagent` (эксперимент, не прод-код).

Вопрос: делегирует ли модель САМА (без имён ролей в goal), и зависит ли
это от размера задачи и от формулировки промпта.

Запуск:
    .venv/bin/python scripts/d6_delegation_ab.py --reps 3 --model deepseek-flash
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ai_coder.agent.tool_loop import run_tool_loop  # noqa: E402
from ai_coder.config import AppConfig, PromptsConfig, load_config, load_prompts  # noqa: E402

# --- задачи ---------------------------------------------------------------

GOAL_SMALL = "Добавь функцию mul(a, b) в calc.py и упомяни её в README.md."

GOAL_LARGE = (
    "Разберись, как в этом проекте обрабатываются ошибки: найди ВСЕ места, "
    "где ошибки логируются, глотаются или пробрасываются, и опиши различия "
    "между подсистемами (storage, api, cache, worker)."
)

# --- варианты промпта -----------------------------------------------------

SECTION_RICH = """## ДОСТУПНЫЕ SUBAGENTS (инструмент spawn_subagent)

Делегируй, когда работа требует **прочитать много файлов** или сделать
**несколько независимых шагов** — это дешевле, чем делать то же своими
итерациями. НЕ делегируй мелочи (правка в 1 файле, чтение 1 функции).

- code-explorer — разведка по проекту: найти, где что лежит, собрать
  список файл:строка. **Когда:** «найди все места, где …», «разберись,
  как устроено …», «собери список …» по всему проекту.
  tools: read_file, read_symbol, list_files, run_shell
- test-runner — прогон тестов. **Когда:** нужно проверить правки или
  собрать падения.
  tools: run_shell
- markdown-writer — правка markdown. **Когда:** нужно обновить docs.
  tools: read_file, write_file
"""

RULE_STRONG = """    ДЕЛЕГИРОВАНИЕ (spawn_subagent) — ГЛАВНОЕ ПРАВИЛО ВЫБОРА ПУТИ:
    Прежде чем читать файлы самому, спроси себя: сколько файлов нужно
    просмотреть? Если больше 3-4 или неизвестно — СНАЧАЛА вызови
    spawn_subagent(name="code-explorer") для разведки, и только потом
    правь сам. Разведка своими силами на 10+ итераций — дороже и медленнее.
    Не делегируй только мелочи (1 файл, 1 функция) и саму правку.

"""


def section_old(cfg: AppConfig) -> str:
    """Точная копия ПРЕЖНЕГО build_subagents_section (baseline для A/B)."""
    subs = cfg.agent.subagents
    if not subs:
        return ""
    lines = ["## ДОСТУПНЫЕ SUBAGENTS (инструмент spawn_subagent)", ""]
    for s in subs:
        lines.append(f"- {s.name} — {s.description}")
        lines.append(f"  tools: {', '.join(s.tools)}")
    return "\n".join(lines).rstrip()


def make_prompts(variant: str, base: PromptsConfig) -> PromptsConfig:
    """Возвращает PromptsConfig с модифицированным agent_tool_json."""
    entry = base.get("agent_tool_json")
    system, user = entry.system, entry.user
    if variant in ("v2", "v3"):
        # вставить усиленное правило в начало ПРАВИЛ
        user = user.replace("    ПРАВИЛА:\n", "    ПРАВИЛА:\n" + RULE_STRONG, 1)
    data = dict(base.prompts)
    from ai_coder.config import PromptEntry

    data["agent_tool_json"] = PromptEntry(system=system, user=user)
    return PromptsConfig(prompts=data)


# --- песочница ------------------------------------------------------------


FILES = {
    "README.md": "# sandbox\n\nМини-проект для A/B делегирования.\n",
    "calc.py": "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n",
}


def _subsystem(name: str, n: int) -> dict[str, str]:
    """Генерит подсистему из n файлов с РАЗНЫМ обращением с ошибками.

    Смысл: чтобы ответить на вопрос «как обрабатываются ошибки», нужно
    прочитать все файлы — ручная разведка становится дорогой.
    """
    out: dict[str, str] = {f"{name}/__init__.py": ""}
    patterns = [
        "log.error('{m}: %s', e)\n        raise",
        "log.warning('{m}: %s', e)\n        return None",
        "pass  # молча глотаем",
        "return {{'error': str(e)}}",
        "log.info('{m}: %s', e)\n        return []",
        "raise RuntimeError('{m}') from e",
    ]
    for i in range(n):
        body = patterns[i % len(patterns)].format(m=f"{name}{i}")
        out[f"{name}/mod_{i}.py"] = (
            "import logging\n\n"
            f"log = logging.getLogger(__name__)\n\n\n"
            f"def op_{i}(x):\n"
            f"    try:\n"
            f"        return _do_{i}(x)\n"
            f"    except Exception as e:\n"
            f"        {body}\n"
        )
    return out


for _name, _n in (("storage", 6), ("api", 7), ("cache", 5), ("worker", 6)):
    FILES.update(_subsystem(_name, _n))


def build_sandbox(root: Path) -> Path:
    if root.exists():
        shutil.rmtree(root)
    for rel, content in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return root


# --- один прогон ----------------------------------------------------------


def run_one(
    cfg: AppConfig,
    prompts: PromptsConfig,
    sandbox: Path,
    goal: str,
    model: str,
    max_iterations: int,
    max_cost_rub: float,
    section: str | None,
) -> dict:
    res = run_tool_loop(
        goal=goal,
        project_root=sandbox,
        cfg=cfg,
        prompts_cfg=prompts,
        model=model,
        max_iterations=max_iterations,
        max_cost_rub=max_cost_rub,
        journal=False,
        subagents_section=section,
        verify_commands=[],  # эксперимент про делегирование, не про verify
    )
    tools: dict[str, int] = {}
    for action, _ in res.history:
        if action.tool:
            tools[action.tool] = tools.get(action.tool, 0) + 1
    return {
        "spawn": tools.get("spawn_subagent", 0),
        "steps": len(res.history),
        "iterations": res.iterations,
        "tools": tools,
        "success": res.success,
        "stopped": res.stopped_reason,
        "cost_rub": round(res.total_cost_rub, 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--goal", choices=["small", "large", "both"], default="both")
    ap.add_argument("--variants", default="v0,v1")
    ap.add_argument("--max-iterations", type=int, default=12)
    ap.add_argument("--max-cost-rub", type=float, default=3.0)
    ap.add_argument("--out", default=".ai-out/d6-exp/results.jsonl")
    args = ap.parse_args()

    cfg = load_config(REPO / "config" / "config.yaml")
    base_prompts = load_prompts(REPO / "config" / "prompts.yaml")
    sandbox = build_sandbox(REPO / ".ai-out" / "d6-exp" / "sandbox")
    out_path = REPO / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    all_goals = {"small": GOAL_SMALL, "large": GOAL_LARGE}
    goals = all_goals if args.goal == "both" else {args.goal: all_goals[args.goal]}

    rows: list[dict] = []
    with out_path.open("w", encoding="utf-8") as fh:
        for variant in args.variants.split(","):
            prompts = make_prompts(variant, base_prompts)
            if variant in ("v0", "old"):
                section = section_old(cfg)  # baseline: старый текст
            elif variant in ("v1", "v3"):
                section = SECTION_RICH  # богатая (с per-role «Когда»)
            else:
                section = None  # v2: авто-генератор (то, что шипим)
            for gname, goal in goals.items():
                for rep in range(args.reps):
                    build_sandbox(sandbox)  # чистая песочница каждый прогон
                    row = run_one(
                        cfg,
                        prompts,
                        sandbox,
                        goal,
                        args.model,
                        args.max_iterations,
                        args.max_cost_rub,
                        section,
                    )
                    row.update(variant=variant, goal=gname, rep=rep, model=args.model)
                    rows.append(row)
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    fh.flush()
                    print(
                        f"{variant} {gname:5} rep{rep}: spawn={row['spawn']} "
                        f"steps={row['steps']:2} {row['cost_rub']:.4f} RUB "
                        f"{row['stopped']}",
                        flush=True,
                    )

    print("\n=== СВОДКА ===")
    for variant in args.variants.split(","):
        for gname in goals:
            cell = [r for r in rows if r["variant"] == variant and r["goal"] == gname]
            if not cell:
                continue
            spawned = sum(1 for r in cell if r["spawn"] > 0)
            print(
                f"{variant} {gname:5}: делегировали {spawned}/{len(cell)} | "
                f"средн. шагов {statistics.mean(r['steps'] for r in cell):.1f} | "
                f"сумма {sum(r['cost_rub'] for r in cell):.4f} RUB"
            )
    print(f"\nвсего: {sum(r['cost_rub'] for r in rows):.4f} RUB")
    print(f"сырые данные: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
