"""D7 #2: ловит ли run_reverse_check неправильный фикс из E2E-2?

Неправильный фикс: `step_type=st.type` — сырые значения ("verify",
"explore") вместо ожидаемых "read"/None/"edit". Формально это
«пробрасывает type подзадачи в step_type», поэтому вопрос: поймает ли
RC такую подмену, и зависит ли ответ от формулировки goal.

Запуск: .venv/bin/python scripts/d7_rc_experiment.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ai_coder.agent.reverse import run_reverse_check  # noqa: E402
from ai_coder.config import load_config, load_prompts  # noqa: E402

DIFF_WRONG = """\
diff --git a/ai_coder/agent/decomposer.py b/ai_coder/agent/decomposer.py
--- a/ai_coder/agent/decomposer.py
+++ b/ai_coder/agent/decomposer.py
@@ -364,7 +364,7 @@ def run_agent_decompose(
             verify_commands=verify_commands,
-            step_type="edit",
+            step_type=st.type,
             feedback_section=feedback,
         )
@@ -417,7 +417,7 @@ def run_agent_decompose(
                     verify_commands=verify_commands,
-                    step_type="edit",
+                    step_type=st.type,
                     feedback_section=feedback,
                 )
diff --git a/docs/state.md b/docs/state.md
--- a/docs/state.md
+++ b/docs/state.md
@@ -624,6 +624,7 @@ tool loop + модуль `spawn.py`.
   - `decompose_model` в config;
+  - **Fix:** verify-подзадача пробрасывает `type` подзадачи в `step_type`.
"""

DIFF_CORRECT = """\
diff --git a/ai_coder/agent/decomposer.py b/ai_coder/agent/decomposer.py
--- a/ai_coder/agent/decomposer.py
+++ b/ai_coder/agent/decomposer.py
@@ -346,6 +346,11 @@ def run_agent_decompose(
         subtask_model, subtask_iters = _resolve_subagent(st)
+        step_type = "edit"
+        if st.type == "explore":
+            step_type = "read"
+        elif st.type == "verify":
+            step_type = None
         final_iters = max_iterations if max_iterations is not None else subtask_iters
@@ -364,7 +369,7 @@ def run_agent_decompose(
             verify_commands=verify_commands,
-            step_type="edit",
+            step_type=step_type,
             feedback_section=feedback,
         )
"""

G1_VAGUE = (
    "Почини verify-подзадачу в decompose: пробрасывай type подзадачи "
    "в step_type. Обнови docs/state.md."
)
G2_PRECISE = (
    "Почини verify-подзадачу в decompose: тип verify НЕ должен требовать "
    "applied_ops>0. _handle_finish понимает только step_type=None "
    "(успех по finish), 'read' (нужен read_ops>0) и 'edit' "
    "(нужен applied_ops>0). Сделай так, чтобы verify получал None."
)
G3_ISSUE = (
    "verify-подзадача в decompose: type подзадачи → step_type. "
    "explore→'read', verify→None, edit-*/неизвестный→'edit'."
)

CASES = [
    ("wrong + G1 (goal из E2E-2)", DIFF_WRONG, G1_VAGUE),
    ("wrong + G2 (точный goal)", DIFF_WRONG, G2_PRECISE),
    ("wrong + G3 (issue-стиль)", DIFF_WRONG, G3_ISSUE),
    ("correct + G1 (контроль)", DIFF_CORRECT, G1_VAGUE),
]


def main() -> int:
    cfg = load_config(REPO / "config" / "config.yaml")
    prompts = load_prompts(REPO / "config" / "prompts.yaml")
    rows = []
    for name, diff, goal in CASES:
        rc = run_reverse_check(
            goal=goal, diff=diff, project_root=REPO, cfg=cfg, prompts_cfg=prompts
        )
        rows.append(
            {
                "case": name,
                "ok": rc.ok,
                "problems": rc.problems,
                "suggestion": rc.suggestion,
                "cost_rub": round(rc.cost_rub, 4),
                "parse_error": rc.parse_error,
            }
        )
        verdict = "ПОЙМАЛ" if rc.ok is False else "НЕ поймал"
        print(f"{name:32} ok={rc.ok!s:5} {verdict}  {rc.cost_rub:.4f} RUB")
        for p in rc.problems[:3]:
            print(f"      - {p[:100]}")
        if rc.suggestion:
            print(f"      -> {rc.suggestion[:100]}")
        print()

    out = REPO / ".ai-out" / "dsh-d7" / "rc-experiment.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"всего: {sum(r['cost_rub'] for r in rows):.4f} RUB")
    print(f"сырые данные: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
