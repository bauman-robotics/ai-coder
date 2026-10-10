from __future__ import annotations

from pathlib import Path

from ai_coder.scanner import (
    build_tree,
    render_files_block,
    render_metadata_block,
    scan_project,
    scan_project_metadata,
)


def test_scan_ignores_git_venv_pycache(sample_project: Path, minimal_cfg):
    res = scan_project(sample_project, minimal_cfg.scanning)

    rel_paths = set(res.files.keys())

    # что должно попасть
    assert "src/main.py" in rel_paths
    assert "src/utils.py" in rel_paths
    assert "README.md" in rel_paths
    # src/__init__.py пустой — пропускается (reason="empty")
    assert "src/__init__.py" not in rel_paths

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


def test_scan_skips_empty_files(sample_project: Path, minimal_cfg):
    """Пустые файлы пропускаются с reason='empty'."""
    empty_file = sample_project / "empty.py"
    empty_file.write_text("", encoding="utf-8")

    res = scan_project(sample_project, minimal_cfg.scanning)

    assert "empty.py" not in res.files
    reasons = {s.reason for s in res.skipped if s.path == "empty.py"}
    assert "empty" in reasons


def test_only_paths_selects_single_file(sample_project: Path, minimal_cfg):
    """--only-path на конкретный файл: в контексте только он."""
    minimal_cfg.scanning.only_paths = ["src/main.py"]

    res = scan_project(sample_project, minimal_cfg.scanning)

    assert set(res.files.keys()) == {"src/main.py"}


def test_only_paths_selects_directory(sample_project: Path, minimal_cfg):
    """--only-path на директорию: в контексте всё её содержимое (кроме пустых)."""
    minimal_cfg.scanning.only_paths = ["src/"]

    res = scan_project(sample_project, minimal_cfg.scanning)

    assert set(res.files.keys()) == {"src/main.py", "src/utils.py"}


def test_only_paths_nested_directory(sample_project: Path, minimal_cfg):
    """--only-path на вложенный файл: родительские директории проходятся."""
    (sample_project / "src" / "sub").mkdir()
    (sample_project / "src" / "sub" / "deep.py").write_text("x = 1\n", encoding="utf-8")

    minimal_cfg.scanning.only_paths = ["src/sub/deep.py"]

    res = scan_project(sample_project, minimal_cfg.scanning)

    assert set(res.files.keys()) == {"src/sub/deep.py"}


def test_only_paths_no_match(sample_project: Path, minimal_cfg):
    """--only-path на несуществующий путь: пустой результат, без ошибок."""
    minimal_cfg.scanning.only_paths = ["nonexistent/"]

    res = scan_project(sample_project, minimal_cfg.scanning)

    assert res.files == {}


def test_only_paths_normalizes_dot_slash(sample_project: Path, minimal_cfg):
    """--only-path с ведущим './' должен нормализоваться."""
    minimal_cfg.scanning.only_paths = ["./src/main.py"]

    res = scan_project(sample_project, minimal_cfg.scanning)

    assert "src/main.py" in res.files


def test_scan_project_only_paths_param_overrides_cfg(sample_project, minimal_cfg):
    """Явный only_paths= в аргументе перебивает cfg.scanning.only_paths."""
    minimal_cfg.scanning.only_paths = ["src/utils.py"]  # cfg
    res = scan_project(sample_project, minimal_cfg.scanning, only_paths=["src/main.py"])  # аргумент
    assert set(res.files.keys()) == {"src/main.py"}


def test_scan_project_only_paths_empty_disables_filter(sample_project, minimal_cfg):
    """only_paths=[] отключает фильтр, даже если cfg не пуст."""
    minimal_cfg.scanning.only_paths = ["src/main.py"]
    res = scan_project(sample_project, minimal_cfg.scanning, only_paths=[])
    assert "src/utils.py" in res.files
    assert "README.md" in res.files


def test_scan_project_metadata_returns_tree_and_metadata(sample_project, minimal_cfg):
    """Metadata-scan возвращает дерево и содержимое README."""
    res = scan_project_metadata(sample_project, minimal_cfg.scanning)

    assert "src" in res.tree
    assert "main.py" in res.tree
    assert "README.md" in res.metadata
    assert "# sample" in res.metadata["README.md"]


def test_scan_project_metadata_no_content_in_tree(sample_project, minimal_cfg):
    """В дереве — только имена, без содержимого."""
    res = scan_project_metadata(sample_project, minimal_cfg.scanning)

    assert "def hello" not in res.tree
    assert "def add" not in res.tree
    assert "main.py" in res.tree
    assert "utils.py" in res.tree


def test_scan_project_metadata_respects_only_paths(sample_project, minimal_cfg):
    """only_paths сужает metadata-scan."""
    res = scan_project_metadata(sample_project, minimal_cfg.scanning, only_paths=["src/main.py"])

    assert "main.py" in res.tree
    assert "utils.py" not in res.tree
    assert res.metadata == {}


def test_render_metadata_block(sample_project, minimal_cfg):
    """render_metadata_block формирует блок с README."""
    res = scan_project_metadata(sample_project, minimal_cfg.scanning)
    block = render_metadata_block(res)

    assert "### README.md" in block
    assert "# sample" in block


# ---------- mask_secrets ----------


def test_mask_secrets_empty():
    from ai_coder.scanner import mask_secrets

    masked, names = mask_secrets("hello world")
    assert masked == "hello world"
    assert names == []


def test_mask_secrets_aws_key():
    from ai_coder.scanner import mask_secrets

    text = "aws_key = 'AKIAIOSFODNN7EXAMPLE'"
    masked, names = mask_secrets(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in masked
    assert "***REDACTED (AWS access key)***" in masked
    assert names == ["AWS access key"]


def test_mask_secrets_multiple():
    from ai_coder.scanner import mask_secrets

    text = (
        "openai = 'sk-aaaaaaaaaaaaaaaaaaaaaaaaa'\n"
        "github = 'ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'\n"
    )
    masked, names = mask_secrets(text)
    assert "sk-aaaaaaaaaaaaaaaaaaaaaaaaa" not in masked
    assert "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in masked
    assert "OpenAI/DeepSeek API key" in names
    assert "GitHub personal access token" in names
    assert len(names) == 2
