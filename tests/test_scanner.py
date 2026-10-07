from __future__ import annotations

from pathlib import Path

from ai_coder.scanner import build_tree, render_files_block, scan_project


def test_scan_ignores_git_venv_pycache(sample_project: Path, minimal_cfg):
    res = scan_project(sample_project, minimal_cfg.scanning)

    rel_paths = set(res.files.keys())

    # что должно попасть
    assert "src/main.py" in rel_paths
    assert "src/utils.py" in rel_paths
    assert "src/__init__.py" in rel_paths
    assert "README.md" in rel_paths

    # что НЕ должно попасть
    assert not any(p.startswith(".git/") for p in rel_paths)
    assert not any(p.startswith("__pycache__/") for p in rel_paths)


def test_scan_ignores_gitignore(sample_project: Path, minimal_cfg):
    res = scan_project(sample_project, minimal_cfg.scanning)
    rel_paths = set(res.files.keys())
    # node_modules — в .gitignore
    assert not any("node_modules" in p for p in rel_paths)


def test_scan_ignores_secrets(sample_project: Path, minimal_cfg):
    res = scan_project(sample_project, minimal_cfg.scanning)
    rel_paths = set(res.files.keys())
    assert ".env" not in rel_paths


def test_scan_ignores_binary(sample_project: Path, minimal_cfg):
    res = scan_project(sample_project, minimal_cfg.scanning)
    rel_paths = set(res.files.keys())
    assert "logo.png" not in rel_paths


def test_build_tree():
    tree = build_tree(["src/main.py", "src/utils.py", "README.md"])
    assert "src" in tree
    assert "main.py" in tree
    assert "utils.py" in tree
    assert "README.md" in tree


def test_render_files_block(sample_project: Path, minimal_cfg):
    res = scan_project(sample_project, minimal_cfg.scanning)
    block = render_files_block(res)
    assert "### src/main.py" in block
    assert 'return "world"' in block

def test_scan_ignores_too_large_file(sample_project: Path, minimal_cfg):
    """Файл больше max_file_size_kb должен попасть в skipped."""
    big = sample_project / "big.py"
    # minimal_cfg.scanning.max_file_size_kb = 500 → создаём 600 KB
    big.write_text("# x\n" * 200_000, encoding="utf-8")

    res = scan_project(sample_project, minimal_cfg.scanning)
    assert "big.py" not in res.files
    reasons = {s.reason for s in res.skipped if s.path == "big.py"}
    assert "too_large" in reasons

def test_scan_ignores_content_secret(sample_project: Path, minimal_cfg):
    secrets_file = sample_project / "settings.py"
    secrets_file.write_text(
        'API_KEY = "sk-abcdefghijklmnopqrstuvwxyz1234567890"\n',
        encoding="utf-8",
    )
    res = scan_project(sample_project, minimal_cfg.scanning)
    assert "settings.py" not in res.files
    reasons = {s.reason for s in res.skipped if s.path == "settings.py"}
    assert any(r.startswith("secret_content") for r in reasons)


def test_scan_ignores_private_key_pem(sample_project: Path, minimal_cfg):
    pem_file = sample_project / "server.crt"
    pem_file.write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    res = scan_project(sample_project, minimal_cfg.scanning)
    assert "server.crt" not in res.files


def test_scan_keeps_normal_file_with_short_token(sample_project: Path, minimal_cfg):
    f = sample_project / "config.py"
    f.write_text('TOKEN = "sk-short"\n', encoding="utf-8")
    res = scan_project(sample_project, minimal_cfg.scanning)
    assert "config.py" in res.files    