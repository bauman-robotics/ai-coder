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
