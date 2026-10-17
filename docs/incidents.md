# Инциденты и потери

Журнал **потерь данных** и **инцидентов** (без обвинений — что случилось, что сделали, как не повторить).

---

## 2026-10-17 — потеряны старые логи `.ai-out` (до 10 дней)

**Что потеряно:** отчёты `ai-coder` в `.ai-out/ai-coder/` за ~10 дней
(09–14 окт: `greet-*.md`, `tool-loop-*`, `autofix-*`,
`tool-loop-backup-*`). Восстановить нельзя.

**Что осталось (проверено 2026-10-17):**
- **worktree** `.worktrees/reports-structure/.ai-out/reports-structure/`:
  - плоские `greet-*.md` (12:37–13:06) и legacy `tool-loop-*`
    (12:46, 12:48);
  - `2026-10-17/00–20_.../` — в основном только `goal.txt`
    (неудачные/прерванные прогоны);
  - полные: `2026-10-17/18_run_greet/` (report + goal + raw, 16:07) и
    `2026-10-17/99_tool-loop_test/` (report + step + history, live-check);
  - **артефакт бага `Path('.')`:**
    `.worktrees/reports-structure/.ai-out/2026-10-17/99_tool-loop_test/`
    (без `/reports-structure/`) — оставлен как evidence, не удалять
    до фиксации инцидента.
- **main** `.ai-out/ai-coder/`:
  - `2026-10-17/00_run_greet/` — report + goal + raw (16:11);
  - `2026-10-17/03_tool-loop_eto-ne-direktoriya/goal.txt` (16:32,
    без `report.md`);
  - `usage.jsonl` — 1 запись (16:11).
- **другие проекты** (`lichess_db_project`, `youtube-...`) — свои, не
  наши.

Проверить фактически:
`find .ai-out -name report.md` и
`find .worktrees/reports-structure/.ai-out -name report.md`.

**Как потеряли (по фактам):**
- `.ai-out` — в `.gitignore` (**локальный**, не в git).
- `dsh` **не** удалял (траектория `session.v4.jsonl` — чистая:
  `rm` только в `/tmp` и `.verify-run`).
- `.ai-out/ai-coder/usage.jsonl` — **Birth 16:11:51** (создан заново).
- `dsh` в 16:21 **видел** старые (`autofix-2026-10-09`,
  `tool-loop-backup-20261009`) — значит, удалены **после 16:21**.
- `bash_history` / `session.v4.jsonl` — `rm .ai-out` **нет**.
- **Точный виновник неизвестен** (ручной `rm`? `git clean`? — не
  зафиксировано).

**Как не повторить:**
1. **Backup** `.ai-out` → `~/.ai-coder/archive/`. Скрипт + cron — TODO;
   минимум перед рискованным действием:
   `cp -a .ai-out ~/.ai-coder/archive/$(date +%F)`. Проверять, что
   архив **непустой** (`find ... -name report.md | wc -l`).
2. **Перед** merge / `pip install -e .` / `rm` / `git clean` —
   **проверить** `.ai-out` (`ls -la .ai-out/ai-coder/`,
   `find .ai-out -name report.md | wc -l`).
3. **Docs**: `.ai-out` — локальный, в git не попадает. `git clean -fdx`
   / `rm -rf .ai-out` — **удалит** логи.
4. **Не** запускать `git clean -fdx` без `-e .ai-out` (или
   `git clean -fdX` без `x`).
5. **Не** считать `.ai-out` бэкапом: отчёты в worktree и в main —
   разные каталоги; worktree-логи исчезнут при удалении worktree.

**Урок:** `.ai-out` — **не** в git, **не** бэкапится → **хрупкий**.
Backup — обязателен.

---
