"""HarpCache coverage."""

from __future__ import annotations

import pytest

pytest.importorskip("harp.proto_loader")  # skip if protos aren't vendored
from harp import harpcache as harpcache_module

from harp.harpcache import HarpCache
from harp.proto_loader import Request
from harp.settings import Settings


def _settings(root: str) -> Settings:
    settings = Settings()
    settings.harpcache_host_root = root
    settings.harpcache_container_root = root
    settings.harpcache_max_files = 20
    settings.harpcache_manifest_entries = 20
    settings.harpcache_relevant_files = 3
    settings.harpcache_ttl_s = 60
    settings.harpcache_walk_time_budget_s = 1.0
    return settings


def _request(root: str, pwd: str | None = None) -> Request:
    req = Request()
    req.input.user_inputs.inputs.add().user_query.query = "where is billing cache?"
    req.input.context.directory.pwd = pwd or root
    req.input.context.git.branch = "main"
    req.input.context.git.head = "abc123"
    codebase = req.input.context.codebases.add()
    codebase.name = "example"
    codebase.path = root
    return req


def test_harpcache_builds_repo_context_and_reuses_snapshot(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "README.md").write_text("Example service overview", encoding="utf-8")
    (root / ".env").write_text("SECRET_TOKEN=do-not-read", encoding="utf-8")
    src = root / "src"
    src.mkdir()
    (src / "billing.py").write_text("def billing_cache():\n    return 'cached'\n", encoding="utf-8")

    cache = HarpCache(_settings(str(root)))
    req = _request(str(root), str(src))

    first = cache.build_context(req, "explain billing cache")
    second = cache.build_context(req, "explain billing cache")

    assert first is not None
    assert second is not None
    assert not first.cache_hit
    assert second.cache_hit
    assert "<HarpCache>" in first.text
    assert "README.md" in first.text
    assert "src/billing.py" in first.text
    assert "billing_cache" in first.text
    assert "SECRET_TOKEN" not in first.text


def test_harpcache_refuses_paths_outside_allowed_root(tmp_path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    (outside / ".git").mkdir()
    (outside / "README.md").write_text("outside", encoding="utf-8")

    cache = HarpCache(_settings(str(allowed)))
    req = _request(str(outside))

    assert cache.build_context(req, "read outside") is None


def test_harpcache_includes_active_project_rules(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "README.md").write_text("Example", encoding="utf-8")
    req = _request(str(root))
    rules = req.input.context.project_rules.add()
    active = rules.active_rule_files.add()
    active.file_path = "AGENTS.md"
    active.content = "Always cite project files."

    context = HarpCache(_settings(str(root))).build_context(req, "what are the rules?")

    assert context is not None
    assert "Project rules" in context.text
    assert "Always cite project files." in context.text


def test_harpcache_respects_project_ignore_files(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / ".gitignore").write_text("ignored_dir/\n*.log\n", encoding="utf-8")
    (root / ".warpignore").write_text("secrets/\n", encoding="utf-8")
    (root / "README.md").write_text("Example", encoding="utf-8")
    (root / "debug.log").write_text("hidden log", encoding="utf-8")

    ignored_dir = root / "ignored_dir"
    ignored_dir.mkdir()
    (ignored_dir / "hidden.py").write_text("IGNORED_BY_GITIGNORE = True\n", encoding="utf-8")

    secrets = root / "secrets"
    secrets.mkdir()
    (secrets / "private.py").write_text("IGNORED_BY_WARPIGNORE = True\n", encoding="utf-8")

    src = root / "src"
    src.mkdir()
    (src / "kept.py").write_text("def kept_cache():\n    return True\n", encoding="utf-8")

    context = HarpCache(_settings(str(root))).build_context(_request(str(root)), "kept cache")

    assert context is not None
    assert "Ignore files applied: .gitignore, .warpignore" in context.text
    assert "src/kept.py" in context.text
    assert "kept_cache" in context.text
    assert "IGNORED_BY_GITIGNORE" not in context.text
    assert "IGNORED_BY_WARPIGNORE" not in context.text
    assert "debug.log" not in context.text


def test_harpcache_walk_deduplicates_repeated_entries(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".warpignore").write_text("ignored\n", encoding="utf-8")
    cache = HarpCache(_settings(str(root)))

    def fake_walk(path):
        yield str(path), [], [".warpignore", ".warpignore", ".warpignore"]

    monkeypatch.setattr(harpcache_module.os, "walk", fake_walk)

    files = cache._walk_files(root, [])

    assert [file.name for file in files] == [".warpignore"]


def test_harpcache_walk_stops_at_time_budget(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("Example", encoding="utf-8")
    settings = _settings(str(root))
    settings.harpcache_walk_time_budget_s = 0.1
    cache = HarpCache(settings)
    monotonic_values = iter([0.0, 1.0])
    monkeypatch.setattr(
        harpcache_module.time,
        "monotonic",
        lambda: next(monotonic_values, 1.0),
    )

    assert cache._walk_files(root, []) == []
