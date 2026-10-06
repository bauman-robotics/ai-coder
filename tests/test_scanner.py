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
