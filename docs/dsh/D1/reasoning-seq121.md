I now have a complete picture. Write the answer as a structured plan, in Russian (user writes Russian), concise but detailed with file:line references. No code edits. Include recommended minimal-diff MVP and the diff-isolation design.

Let me be careful about a subtlety: `_collect_diff` is defined in reverse.py and used in tool_loop. For per-subtask isolation, options discussed. Also note that `run_reverse_check` accepts a `diff` string, so no change to reverse.py is strictly required — the adapter belongs in decomposer.py (a new helper `_collect_subtask_diff(project_root, baseline)`), plus CLI/config plumbing only if a flag is desired.

One more nuance: `_MAX_DIFF_CHARS`/budget logic. Fine.

Also: baseline snapshot approach needs `git stash create` which requires git repo; decompose may run in non-git repo (is_git_repo check). Fall back: if not git repo → skip RC (like tool_loop's empty-diff skip) or use manifest-based synthetic diff.

Another nuance: RC model resolution falls back to cfg.agent.decompose_model, which is v4-pro — expensive per subtask. Recommend explicit reverse_check_model or pass model=subtask_model (flash).

Cost accounting and remaining budget: at line 248-250 `remaining = max(0, max_cost_rub - dec_result.cost_rub)` computed BEFORE the subtask; RC cost must be added to dec_result totals so the next iteration's remaining shrinks. Also the max_cost check at 348 should include RC cost.

Also mention: subtask_results[-1] wholesale replacement (333-346) — if RC runs before retry it gets lost; so run RC after the retry block (after line 346) and use loop_result (the final one).

Also: the "success" key semantic and rollback loop at 425-431.

Also mention tests that will need updates if flag default on; with default off none break. Tests asserting report.md content: test at 2390 only checks existence. chain tests are separate (tool_loop). So report column addition is safe, but chain report is written by a different function? test_cli_agent 695 report.md — that's for chain of tool loops, different. Fine.

Also note dry_run skip and interactive.

Write the final answer. Structure with 5 headings as requested. Include a short "минимальный MVP" recommendation. Keep code out (no code snippets? The user said "код НЕ правь" — don't edit code. Small illustrative signatures are fine but I'll keep it prose/short signatures, no implementation).

Include file links with line numbers per formatting rules. Use relative paths from working directory: ai_coder/agent/reverse.py.

Let me write it.
