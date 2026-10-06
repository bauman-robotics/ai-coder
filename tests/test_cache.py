from __future__ import annotations

from pathlib import Path

from ai_coder import cache as cache_mod
from ai_coder.apply import Operation, WritePlan
from ai_coder.llm import LLMResponse
from ai_coder.scanner import ScanResult


def _scan(files: dict[str, str], root: Path = Path("/tmp/x")) -> ScanResult:
    return ScanResult(root=root, files=files, tree="")


def _llm(content: str = "answer") -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test-model",
        prompt_tokens=100,
        prompt_cache_hit_tokens=80,
        prompt_cache_miss_tokens=20,
        completion_tokens=50,
        total_tokens=150,
        duration_ms=1000,
        finish_reason="stop",
    )


def test_compute_hash_stable():
    scan = _scan({"a.py": "x = 1\n"})
    h1 = cache_mod.compute_hash(scan, "S", "U", "m", "shallow")
    h2 = cache_mod.compute_hash(scan, "S", "U", "m", "shallow")
    assert h1 == h2


def test_compute_hash_changes_with_file_content():
    h1 = cache_mod.compute_hash(_scan({"a.py": "x = 1\n"}), "S", "U", "m", "shallow")
    h2 = cache_mod.compute_hash(_scan({"a.py": "x = 2\n"}), "S", "U", "m", "shallow")
    assert h1 != h2


def test_compute_hash_changes_with_prompt():
    scan = _scan({"a.py": "x = 1\n"})
    h1 = cache_mod.compute_hash(scan, "S1", "U", "m", "shallow")
    h2 = cache_mod.compute_hash(scan, "S2", "U", "m", "shallow")
    assert h1 != h2


def test_compute_hash_changes_with_model():
    scan = _scan({"a.py": "x = 1\n"})
    h1 = cache_mod.compute_hash(scan, "S", "U", "m1", "shallow")
    h2 = cache_mod.compute_hash(scan, "S", "U", "m2", "shallow")
    assert h1 != h2


def test_compute_hash_changes_with_depth():
    scan = _scan({"a.py": "x = 1\n"})
    h1 = cache_mod.compute_hash(scan, "S", "U", "m", "shallow")
    h2 = cache_mod.compute_hash(scan, "S", "U", "m", "normal")
    assert h1 != h2


def test_cache_round_trip_llm_only(tmp_path: Path):
    scan = _scan({"a.py": "x = 1\n"})
    llm = _llm("hello world")
    hash_hex = cache_mod.compute_hash(scan, "S", "U", "m", "shallow")

    cache_mod.save(
        project_root=tmp_path,
        output_dir=".ai-out",
        cache_dir_name="cache",
        hash_hex=hash_hex,
        action="greet",
        model="m",
        depth="shallow",
        prompt_name="greet",
        llm=llm,
        write_plan=None,
    )

    result = cache_mod.from_cache(
        project_root=tmp_path,
        output_dir=".ai-out",
        cache_dir_name="cache",
        hash_hex=hash_hex,
        scan=scan,
    )
    assert result is not None
    llm2, plan2 = result
    assert llm2.content == "hello world"
    assert llm2.prompt_tokens == 100
    assert llm2.prompt_cache_hit_tokens == 80
    assert plan2 is None


def test_cache_round_trip_with_plan(tmp_path: Path):
    scan = _scan({"a.py": "x = 1\n"})
    llm = _llm("plan-json")
    plan = WritePlan(
        explanation="test",
        operations=[
            Operation(type="create_file", path="new.py", content="y = 1\n"),
        ],
        problems=[],
        diff="--- /dev/null\n+++ b/new.py\n+y = 1\n",
        raw_json="{}",
    )
    hash_hex = cache_mod.compute_hash(scan, "S", "U", "m", "shallow")

    cache_mod.save(
        project_root=tmp_path,
        output_dir=".ai-out",
        cache_dir_name="cache",
        hash_hex=hash_hex,
        action="write_readme",
        model="m",
        depth="shallow",
        prompt_name="write_readme_json",
        llm=llm,
        write_plan=plan,
    )

    result = cache_mod.from_cache(
        project_root=tmp_path,
        output_dir=".ai-out",
        cache_dir_name="cache",
        hash_hex=hash_hex,
        scan=scan,
    )
    assert result is not None
    _, plan2 = result
    assert plan2 is not None
    assert len(plan2.operations) == 1
    assert plan2.operations[0].type == "create_file"
    assert plan2.operations[0].path == "new.py"
    assert plan2.operations[0].content == "y = 1\n"


def test_cache_miss(tmp_path: Path):
    scan = _scan({"a.py": "x = 1\n"})
    hash_hex = "deadbeef" * 8
    result = cache_mod.from_cache(
        project_root=tmp_path,
        output_dir=".ai-out",
        cache_dir_name="cache",
        hash_hex=hash_hex,
        scan=scan,
    )
    assert result is None
