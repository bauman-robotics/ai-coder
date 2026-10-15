I have everything I need. Now compose the plan, structured as requested. No code changes.

Key facts to cite with line numbers:

1. run_reverse_check (reverse.py:92-177):
- signature keyword-only: goal, diff, project_root, cfg, prompts_cfg, model=None → ReverseCheckResult
- returns ReverseCheckResult (models.py:44-54): ok, problems, suggestion, cost_rub/cny/usd, raw_response, parse_error
- diff is passed in, NOT collected inside. _collect_diff (reverse.py:22-89) collects git diff HEAD + untracked files appended manually; caps at _MAX_DIFF_CHARS=15000 (line 19, 84-89)
- truncates diff to cfg.agent.reverse_check_max_diff_chars (default 15000, config.py:210)
- prompt rendering: manual str.replace of {{goal}}/{{diff}} into system and user of prompts_cfg.get("agent_reverse_check") (lines 111-115)
- model resolution: model arg → cfg.agent.reverse_check_model → cfg.agent.decompose_model → cfg.api.model (117-122)
- LLMClient chat, temperature=0.0, no json_mode (line 126-131)
- cost computed via calculate_cost + rates (135-147)
- markdown fence strip (149-156); json.loads; ok default True; parse failure or LLM exception → ok=True with parse_error (fail-open; lines 132-133, 169-177)

2. Call site in tool loop: tool_loop.py:693-739. Called in _tool_loop_finalize, after verify, BEFORE auto_commit (diff collected at 696 pre-commit), guarded by `ctx.reverse_check and ctx.success and not ctx.dry_run and ctx.stopped_reason == "completed"`. Cost added to ctx totals (725-727). ok=False → warnings + print, does NOT fail the loop, does not rollback (728-737). Result stored in ctx.reverse_result → ToolLoopResult.reverse_check_result (759) and report (790-804).

In decompose: run_agent_decompose calls run_tool_loop without auto_commit and without reverse_check (decomposer.py:253-271), so per-subtask RC never runs, and no commits → whole worktree diff accumulates. Point of insertion: after loop_result success (after line 289 append / before line 291 fail-handling) — more precisely after the append of subtask_results and after the retry block (line 292-346), since for fail-retry path you'd want the check only on the final successful attempt. Recommended: insert right after the retry block ends, i.e. after line 346 / before the max_cost check at 348, gated on `loop_result.success and not dry_run`. Data available at that point: st (Subtask: n, goal, files, type), loop_result (success, stopped_reason, cost, backup_dir, journal_dir, commit_hash=None, verify_errors, warnings, history), subtask_subdir, dec_result, cfg, prompts_cfg, depth.

3. Data needed:
- goal: st.goal (exact text given to tool loop, decomposer.py:254)
- diff: must be the delta caused by THIS subtask only. Options:
  - A (recommended): baseline snapshot before subtask + diff after. Since decompose never commits (no auto_commit passed), `git diff HEAD` would swallow all previous subtasks. Use `git stash create` (or `git rev-parse HEAD` + writing tree) before the subtask to capture baseline tree-ish, then after: `git diff <baseline>` for tracked files + untracked-new-files appended by manifest. Untracked caveat: stash create excludes untracked, so use backup manifest / `git status --porcelain` sets before+after diff.
  - B: scope by backup manifest: loop_result.backup_dir/manifest.json contains operations list [{type: edit_file|create_file, path}] (tool_loop.py:154-170, 649-654). diff = `git diff HEAD -- <paths>` for edits + synthesized new-file diff for creates. Cheap and precise per-subtask, but misses files deleted/renamed by shell tools (run_shell) and any ops not routed through _backup_file_for_tool_loop.
  - C (cheapest MVP): whole-worktree `_collect_diff`, accept that later subtasks see earlier subtask diffs; only valid if we also add auto_commit=True per subtask (then HEAD advances, and unchanged behavior of _collect_diff works). Note: adding auto_commit to decompose changes existing behavior significantly (creates commits).
  - Also: pass project_root (needed for rates + is_git_repo), cfg, prompts_cfg, model (recommend a dedicated model, e.g. cfg.agent.reverse_check_model or per-subtask model flash).
- Also new config: `decompose_reverse_check: bool = False` (AgentConfig), maybe `decompose_reverse_check_on_fail: str` policy ("warn"|"fail"|"rollback"), CLI flag `--decompose-reverse-check` (CLI must not require --tool-loop; validation at cli.py:1443 currently requires --tool-loop for --reverse-check).
- prompt: same agent_reverse_check template; optionally add subtask context (index n/total) — would need template change or new prompt entry, but the current template only has goal/diff, so render works as-is.

4. Effect on logic: propose an enum-like policy. ok=True → mark subtask "reverse_check_ok": True in subtask_results dict, continue. ok=False → three possible policies:
  - warn (default, mirrors tool_loop): append problems to subtask dict + dec_result-ish warnings, continue. No rollback.
  - fail: set dec_result.parse_error = f"subtask {st.n} reverse-check failed", save report, return — reuses fail path (line 434-439). But note this sits AFTER loop_result.success, so the existing fail branch at 354 won't trigger; would need a separate exit or a synthesized failure.
  - rollback: rollback loop_result.backup_dir (same helper as lines 407-418) and either retry once with the problem text fed back into the goal, or fail. Retry-feedback is the highest-value option but needs a re-run of run_tool_loop with goal + "\n\nЗамечания ревьюера: ...".
  Cost accounting: add reverse_result.cost_rub/cny/usd to dec_result totals (mirrors 273-275 / 324-326). Careful: in the retry path the subtask_results[-1] dict is REPLACED wholesale (line 333-346) — any new keys added before retry would be lost; so RC should run after the retry block, or the replacement must carry the keys.
  subtask_results gets new keys: "reverse_ok", "reverse_problems", "reverse_suggestion", "reverse_cost_rub", maybe "reverse_check": {...}. Update both dict literals (278-289 and 333-346) to stay consistent.
  report.md: _save_decompose_report table (decomposer.py:489-494) — add a column, e.g. "RC" with ✅/❌/—; plus a "## Reverse-check" section listing per-subtask problems + suggestion; add total RC cost line.
  Also note: report is only written to journal dir (decompose_dir / "report.md").

5. Risks/conflicts:
- Double-check: currently no overlap because decompose passes reverse_check=False and auto_commit not passed. But if a caller passes both (or if `run_tool_loop` in decompose ever gets reverse_check=True), each subtask would be validated twice: once inside tool_loop (with a global worktree diff!) and once at the decompose level. Recommendation: do NOT pass reverse_check=True into the inner run_tool_loop; keep per-subtask check exclusively in decomposer, and gate with one flag.
- Diff-isolation risk (biggest): decompose doesn't commit → `git diff HEAD` inside sub-loop would include previous subtasks; must use baseline snapshot or manifest scoping. Also subtask A's uncommitted changes may be needed by subtask B (sequential dependency), so a "clean per-subtask diff" isn't the same as "correct worktree" — validator judges only the delta, so a subtask that legitimately depends on prior state may be judged on a partial diff. Mention.
- rollback risk: rolling back subtask N after RC failure can break later subtasks that depend on N; also rollback of an RC-failed subtask can delete something later subtask already touched (backup_dir snapshot is per-file). Recommend default warn-only, rollback opt-in.
- Cost: +1 LLM call per successful subtask (N extra calls) → could nearly double call count; N up to many. Dedicated cheaper model recommended (flash), plus max_cost budget check: RC cost counts toward dec_result.cost_rub and toward remaining budget (line 248-250 uses dec_result.cost_rub), so the budget cut at 348 must include RC cost; also add a cap on diff chars (already exists) and possibly skip RC for trivial subtasks (applied_ops == 0 → nothing changed → skip, mirroring tool_loop's "diff пустой — пропуск" at 738-739).
- Latency: validator inside the loop makes decompose slower; no parallelism available (subtasks are sequential).
- dry_run: must be skipped (no LLM spend / no changes), mirror tool_loop guard `not ctx.dry_run`.
- parse_error fail-open: ok=True on parse error means RC never blocks on bad LLM JSON — keep the same semantic so a flaky validator doesn't fail good subtasks.
- Rollback_on_fail interaction: dec_result.rolled_back / rollback loop at 421-432 iterates subtask_results with success && backup_dir; if RC-failed subtask is marked success=False, then a later failure's full rollback would also revert it (probably desired), but "success" is also used for the report status. Decide semantics: success = tool loop success vs overall success (tool loop AND RC). Suggest separate keys, keep "success" as tool-loop truth, add "verified".
- Tests that break:
  - tests/test_agent.py decompose tests (2111-2300+) patch `ai_coder.agent.decomposer.run_tool_loop` and build fake ToolLoopResult objects. If run_reverse_check is called with default flag off (new param default False), these tests pass unchanged. If default on, they'd hit a real LLMClient → break/network. So default must be False.
  - prompt fixture: tests/conftest.py:195 already has agent_reverse_check, fine.
  - Tests asserting exact subtask_results dict shape or report.md content: test_run_agent_decompose_retry_cost_summation (2250) checks cost summation; a wholesale dict replacement at 333-346 means added keys must be preserved or tests comparing dicts exactly may fail. Need to check if any test asserts equality on the dict / report text. Let me quickly grep for report.md assertions and subtask_results assertions to be concrete.

Let me grep quickly to be precise about tests.
