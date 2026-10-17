"""Smoke-тесты GUI (FastAPI + Jinja2 + HTMX).

Покрывают GET/POST роуты через fastapi.testclient.TestClient.
Не покрывают: POST /run, POST /stop/{run_id} (запускают subprocess).
Реальные данные (.ai-out/, docs/cli/) читаются как есть — тесты
проверяют только status_code и ключевые элементы HTML.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from ai_coder.gui.app import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


# ---------- GET / ----------


def test_root_ok(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert 'id="build-form"' in r.text or "build-form" in r.text


def test_health_ok(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ---------- /help → /docs/cli/help ----------


def test_help_redirects(client: TestClient) -> None:
    r = client.get("/help", follow_redirects=False)
    assert r.status_code == 301
    assert "/docs/cli/help" in r.headers.get("location", "")


def test_help_via_docs_cli(client: TestClient) -> None:
    r = client.get("/docs/cli/help")
    assert r.status_code == 200
    assert "Справка" in r.text or "справка" in r.text.lower()


# ---------- /docs/cli ----------


def test_docs_cli_index(client: TestClient) -> None:
    r = client.get("/docs/cli")
    assert r.status_code == 200
    assert "Справочник" in r.text or "справочник" in r.text.lower()


def test_docs_cli_agent(client: TestClient) -> None:
    r = client.get("/docs/cli/agent")
    assert r.status_code == 200


def test_docs_cli_nonexistent_404(client: TestClient) -> None:
    r = client.get("/docs/cli/nonexistent-page-xyz")
    assert r.status_code == 404


# ---------- POST /build ----------


def test_build_default(client: TestClient) -> None:
    r = client.post("/build", data={})
    assert r.status_code == 200
    assert "ai-coder agent" in r.text


def test_build_tool_loop(client: TestClient) -> None:
    r = client.post(
        "/build",
        data={
            "goal": "fix bug",
            "path": ".",
            "mode": "tool-loop",
            "model": "deepseek-flash",
        },
    )
    assert r.status_code == 200
    assert "--tool-loop" in r.text


def test_build_chain(client: TestClient) -> None:
    r = client.post(
        "/build",
        data={
            "goal": "",
            "path": ".",
            "mode": "chain",
            "chain_path": "issues/demos",
            "model": "deepseek-flash",
        },
    )
    assert r.status_code == 200
    assert "--chain" in r.text
    assert "issues/demos" in r.text


def test_build_run(client: TestClient) -> None:
    r = client.post(
        "/build",
        data={
            "task_type": "run",
            "run_action": "greet",
            "path": ".",
        },
    )
    assert r.status_code == 200
    assert "ai-coder run" in r.text
    assert "greet" in r.text


# ---------- /stats ----------


def test_stats_data_json(client: TestClient) -> None:
    r = client.get("/stats/data")
    assert r.status_code == 200
    data = r.json()
    for key in ("summary", "by_day", "by_model", "by_action"):
        assert key in data, f"нет ключа {key}"


def test_stats_view(client: TestClient) -> None:
    r = client.get("/stats")
    assert r.status_code == 200


# ---------- /reports ----------


def test_reports_list(client: TestClient) -> None:
    r = client.get("/reports")
    assert r.status_code == 200


def test_reports_traversal_404(client: TestClient) -> None:
    r = client.get("/reports/nonexistent-project/nonexistent-journal")
    assert r.status_code == 404


# ---------- POST /diff ----------


def test_diff_ok(client: TestClient) -> None:
    """POST /diff — либо {"diff": "..."}, либо {"diff": "", "error": "..."}.

    При чистом рабочем дереве — diff пустой, error отсутствует.
    При ошибке (не-каталог, OSError) — error непустой.
    """
    r = client.post("/diff", data={"path": "."})
    assert r.status_code == 200
    data = r.json()
    assert "diff" in data, "нет ключа diff"


def test_diff_bad_path_error(client: TestClient) -> None:
    """POST /diff на несуществующий путь — error в JSON."""
    r = client.post("/diff", data={"path": "/nonexistent/xyz-123"})
    assert r.status_code == 200
    data = r.json()
    assert "error" in data and data["error"], "ожидался error"


# ---------- D12: прогресс и ссылка на отчёт ----------


def test_run_status_indicator_present(client: TestClient) -> None:
    """D12: на странице есть элемент статуса выполнения и спиннер в CSS."""
    r = client.get("/")
    assert r.status_code == 200
    assert 'id="run-status"' in r.text
    assert "btn-running" in r.text  # JS переключает класс


def test_spinner_css_present(client: TestClient) -> None:
    """D12: CSS для спиннера кнопки отдаётся статикой."""
    r = client.get("/static/style.css")
    assert r.status_code == 200
    assert "btn-spin" in r.text
    assert "button.btn-running::before" in r.text


def test_newest_report_finds_fresh_report(tmp_path, monkeypatch):
    """D12: _newest_report находит свежий отчёт и пропускает cache/."""
    import time

    from ai_coder.gui import app as gui_app

    monkeypatch.setattr(gui_app, "AI_OUT_DIR", tmp_path / ".ai-out")
    _newest_report = gui_app._newest_report

    out = tmp_path / ".ai-out" / "proj"
    out.mkdir(parents=True)
    (out / "cache").mkdir()
    old = out / "greet-old.md"
    old.write_text("old", encoding="utf-8")
    (out / "cache" / "cached.md").write_text("cached", encoding="utf-8")

    since = time.time()
    time.sleep(0.01)
    fresh = out / "suggest_improvements-new.md"
    fresh.write_text("fresh", encoding="utf-8")

    found = _newest_report(since)

    assert found == ("proj", "suggest_improvements-new.md")


def test_newest_report_none_when_nothing_fresh(tmp_path, monkeypatch):
    import time

    from ai_coder.gui import app as gui_app

    monkeypatch.setattr(gui_app, "AI_OUT_DIR", tmp_path / ".ai-out")
    out = tmp_path / ".ai-out" / "proj"
    out.mkdir(parents=True)
    (out / "old.md").write_text("old", encoding="utf-8")

    assert gui_app._newest_report(time.time()) is None

    # каталога .ai-out нет вовсе
    monkeypatch.setattr(gui_app, "AI_OUT_DIR", tmp_path / "nope")
    assert gui_app._newest_report(0.0) is None


def test_flat_report_route_serves_run_report(client: TestClient):
    """D12: /reports/file/<project>/<file>.md отдаёт отчёт действия run.

    Подкладываем файл в реальный AI_OUT_DIR и убираем за собой.
    """
    from ai_coder.gui.app import AI_OUT_DIR

    project_dir = AI_OUT_DIR / "d12-test-project"
    project_dir.mkdir(parents=True, exist_ok=True)
    report = project_dir / "greet-2026-01-01T00-00-00.md"
    report.write_text("# Отчёт D12\n\nтекст\n", encoding="utf-8")
    try:
        r = client.get("/reports/file/d12-test-project/greet-2026-01-01T00-00-00.md")
        assert r.status_code == 200
        assert "Отчёт D12" in r.text
    finally:
        report.unlink(missing_ok=True)
        if not any(project_dir.iterdir()):
            project_dir.rmdir()


def test_flat_report_route_rejects_traversal(client: TestClient) -> None:
    """D12: маршрут не отдаёт ничего вне AI_OUT_DIR и не .md."""
    assert client.get("/reports/file/..%2F..%2Fetc/passwd.md").status_code == 404
    assert client.get("/reports/file/proj/secrets.txt").status_code == 404
    assert client.get("/reports/file/proj/missing.md").status_code == 404


def test_stream_process_emits_report_marker(tmp_path, monkeypatch):
    """D12: после выхода процесса в SSE уходит маркер [отчёт]."""
    import time

    from ai_coder.gui import app as gui_app

    monkeypatch.setattr(gui_app, "AI_OUT_DIR", tmp_path / ".ai-out")
    _stream_process = gui_app._stream_process

    out = tmp_path / ".ai-out" / "proj"
    out.mkdir(parents=True)
    since = time.time()
    time.sleep(0.01)
    (out / "greet-2026-01-01T00-00-00.md").write_text("# r", encoding="utf-8")

    class FakeProc:
        returncode = 0
        stdout: list[str] = []

        def wait(self) -> int:
            return 0

    events = list(_stream_process("run123", FakeProc(), True, since))  # type: ignore[arg-type]

    joined = "".join(events)
    assert "data: run_id: run123" in joined
    assert "data: [exit 0]" in joined
    assert "[отчёт] /reports/file/proj/greet-2026-01-01T00-00-00.md" in joined


def test_stream_process_without_report_root_has_no_marker():
    """D12: для agent/tool-loop (emit_report=False) маркер не шлётся."""
    from ai_coder.gui.app import _stream_process

    class FakeProc:
        returncode = 0
        stdout: list[str] = []

        def wait(self) -> int:
            return 0

    joined = "".join(_stream_process("run1", FakeProc()))  # type: ignore[arg-type]
    assert "[отчёт]" not in joined
    assert "[exit 0]" in joined


def test_newest_report_filters_by_project(tmp_path, monkeypatch):
    """D12: скан не подхватывает отчёт чужого проекта."""
    import time

    from ai_coder.gui import app as gui_app

    monkeypatch.setattr(gui_app, "AI_OUT_DIR", tmp_path / ".ai-out")
    for name in ("proj-a", "proj-b"):
        d = tmp_path / ".ai-out" / name
        d.mkdir(parents=True)
        (d / "inventory-x.md").write_text("# r", encoding="utf-8")
    since = 0.0

    assert gui_app._newest_report(since, "proj-a")[0] == "proj-a"
    assert gui_app._newest_report(since, "proj-b")[0] == "proj-b"
    assert gui_app._newest_report(since, "other") is None


def test_run_command_has_no_apply():
    """run не принимает --apply: GUI не должен его добавлять."""
    from ai_coder.gui.app import _build_command

    cmd = _build_command(
        goal="",
        path=".",
        mode="plain",
        model="default",
        apply=True,
        commit=False,
        check_mode="normal",
        max_cost_rub="",
        advanced_flags="",
        task_type="run",
        run_action="greet",
    )
    assert "--apply" not in cmd
    assert cmd.startswith("ai-coder run greet")
