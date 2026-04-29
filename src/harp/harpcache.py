"""Local project-context cache for Harp-served Warp OSS requests."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from threading import RLock

from .proto_loader import Request
from .settings import Settings

_IMPORTANT_FILENAMES = {
    "AGENTS.md",
    "WARP.md",
    ".warpignore",
    "README.md",
    "README.rst",
    "README.txt",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "docker-compose.yml",
    "compose.yml",
    ".warpindexingignore",
}
_IGNORE_FILENAMES = (
    ".gitignore",
    ".warpignore",
    ".warpindexingignore",
    ".cursorignore",
    ".cursorindexingignore",
    ".codeiumignore",
)
_TEXT_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".py",
    ".rs",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
_SKIP_DIRS = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
    "vendor",
}
_SKIP_FILENAMES = {
    ".DS_Store",
    ".env",
    ".env.local",
    ".env.production",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
}
_TOKEN_RE = re.compile(r"[A-Za-z0-9_./-]{3,}")


@dataclass(slots=True)
class HarpCacheContext:
    """Rendered context and cache metadata for one request."""

    text: str
    repo_root: str
    cache_hit: bool


@dataclass(slots=True)
class _RepoSnapshot:
    repo_root: Path
    host_root: str
    name: str
    pwd: str
    branch: str
    head: str
    files: list[str]
    important_files: dict[str, str]
    ignored_by: list[str]
    built_at: float
    expires_at: float


@dataclass(slots=True)
class _IgnoreRule:
    pattern: str
    source: str
    negated: bool = False
    directory_only: bool = False
    anchored: bool = False


class HarpCache:
    """Bounded in-memory project cache keyed by repo root and git state."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = RLock()
        self._snapshots: dict[tuple[str, str, str], _RepoSnapshot] = {}

    def build_context(self, req: Request, user_text: str) -> HarpCacheContext | None:
        """Return a HarpCache context block for the request, if safely available."""

        if not self._settings.harpcache_enabled:
            return None

        repo = self._resolve_repo(req)
        if repo is None:
            return None

        host_root, repo_root, pwd = repo
        branch = req.input.context.git.branch
        head = req.input.context.git.head
        key = (str(repo_root), branch, head)

        now = time.time()
        with self._lock:
            snapshot = self._snapshots.get(key)
            cache_hit = snapshot is not None and snapshot.expires_at > now
            if not cache_hit:
                snapshot = self._build_snapshot(
                    repo_root=repo_root,
                    host_root=host_root,
                    pwd=pwd,
                    branch=branch,
                    head=head,
                    now=now,
                )
                self._snapshots[key] = snapshot
                self._evict_if_needed()

        text = self._render(snapshot, user_text, req)
        if not text:
            return None
        return HarpCacheContext(text=text, repo_root=host_root, cache_hit=cache_hit)

    def _resolve_repo(self, req: Request) -> tuple[str, Path, str] | None:
        pwd_host = req.input.context.directory.pwd
        if not pwd_host:
            return None

        candidate_host = self._matching_codebase_root(req, pwd_host) or pwd_host
        repo_root = self._map_host_path(candidate_host)
        if repo_root is None:
            return None
        if not repo_root.exists() or not repo_root.is_dir():
            return None

        discovered = self._find_git_root(repo_root)
        if discovered is not None:
            repo_root = discovered
            host_root = self._container_to_host_path(repo_root)
        else:
            host_root = candidate_host

        pwd = self._map_host_path(pwd_host)
        if pwd is None:
            pwd = repo_root
        return host_root, repo_root, self._safe_relpath(pwd, repo_root)

    @staticmethod
    def _matching_codebase_root(req: Request, pwd_host: str) -> str | None:
        pwd_path = Path(pwd_host).expanduser()
        matches: list[Path] = []
        for codebase in req.input.context.codebases:
            if not codebase.path:
                continue
            root = Path(codebase.path).expanduser()
            try:
                pwd_path.relative_to(root)
            except ValueError:
                continue
            matches.append(root)
        if not matches:
            return None
        return str(max(matches, key=lambda path: len(path.parts)))

    def _map_host_path(self, host_path: str) -> Path | None:
        host = Path(host_path).expanduser()
        host_root = Path(self._settings.harpcache_host_root).expanduser()
        container_root = Path(self._settings.harpcache_container_root).expanduser()
        try:
            rel = host.relative_to(host_root)
        except ValueError:
            return None
        return (container_root / rel).resolve(strict=False)

    def _container_to_host_path(self, container_path: Path) -> str:
        container_root = Path(self._settings.harpcache_container_root).expanduser()
        host_root = Path(self._settings.harpcache_host_root).expanduser()
        try:
            rel = container_path.relative_to(container_root)
        except ValueError:
            return str(container_path)
        return str(host_root / rel)

    @staticmethod
    def _find_git_root(path: Path) -> Path | None:
        for parent in (path, *path.parents):
            if (parent / ".git").exists():
                return parent
        return None

    def _build_snapshot(
        self,
        *,
        repo_root: Path,
        host_root: str,
        pwd: str,
        branch: str,
        head: str,
        now: float,
    ) -> _RepoSnapshot:
        files: list[str] = []
        seen_files: set[str] = set()
        important_files: dict[str, str] = {}
        ignore_rules = self._load_ignore_rules(repo_root)

        for file_path in self._walk_files(repo_root, ignore_rules):
            rel = self._safe_relpath(file_path, repo_root)
            if rel in seen_files:
                continue
            seen_files.add(rel)
            files.append(rel)
            if file_path.name in _IMPORTANT_FILENAMES:
                content = self._read_text(file_path)
                if content:
                    important_files[rel] = content

        return _RepoSnapshot(
            repo_root=repo_root,
            host_root=host_root,
            name=repo_root.name,
            pwd=pwd,
            branch=branch,
            head=head,
            files=files,
            important_files=important_files,
            ignored_by=sorted({rule.source for rule in ignore_rules}),
            built_at=now,
            expires_at=now + self._settings.harpcache_ttl_s,
        )

    def _walk_files(self, root: Path, ignore_rules: list[_IgnoreRule]) -> list[Path]:
        out: list[Path] = []
        seen: set[str] = set()
        max_files = self._settings.harpcache_max_files
        deadline = time.monotonic() + self._settings.harpcache_walk_time_budget_s
        for current_root_str, dirs, files in os.walk(root):
            if time.monotonic() > deadline:
                break
            current_root = Path(current_root_str)
            dirs[:] = [
                d
                for d in sorted(set(dirs))
                if d not in _SKIP_DIRS
                and not d.startswith(".")
                and self._inside_root(current_root / d, root)
                and not self._is_ignored(current_root / d, root, ignore_rules, is_dir=True)
            ]
            for name in sorted(set(files)):
                if len(out) >= max_files:
                    return out
                if time.monotonic() > deadline:
                    return out
                path = current_root / name
                if self._should_skip_file(path):
                    continue
                if not self._inside_root(path, root):
                    continue
                if self._is_ignored(path, root, ignore_rules, is_dir=False):
                    continue
                rel = self._safe_relpath(path, root)
                if rel in seen:
                    continue
                seen.add(rel)
                out.append(path)
        return out

    def _load_ignore_rules(self, root: Path) -> list[_IgnoreRule]:
        rules: list[_IgnoreRule] = []
        for filename in _IGNORE_FILENAMES:
            path = root / filename
            try:
                data = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line in data.splitlines():
                rule = self._parse_ignore_line(line, filename)
                if rule is not None:
                    rules.append(rule)
        return rules

    @staticmethod
    def _parse_ignore_line(line: str, source: str) -> _IgnoreRule | None:
        raw = line.strip()
        if not raw or raw.startswith("#"):
            return None
        if raw.startswith("\\#") or raw.startswith("\\!"):
            raw = raw[1:]

        negated = raw.startswith("!")
        if negated:
            raw = raw[1:].strip()
        if not raw:
            return None

        directory_only = raw.endswith("/")
        anchored = raw.startswith("/")
        pattern = raw.strip("/")
        if not pattern:
            return None

        return _IgnoreRule(
            pattern=pattern,
            source=source,
            negated=negated,
            directory_only=directory_only,
            anchored=anchored,
        )

    def _is_ignored(
        self,
        path: Path,
        root: Path,
        ignore_rules: list[_IgnoreRule],
        *,
        is_dir: bool,
    ) -> bool:
        rel = self._safe_relpath(path, root).replace(os.sep, "/")
        if not rel or rel == ".":
            return False

        ignored = False
        for rule in ignore_rules:
            if self._matches_ignore_rule(rule, rel, is_dir):
                ignored = not rule.negated
        return ignored

    @staticmethod
    def _matches_ignore_rule(rule: _IgnoreRule, rel: str, is_dir: bool) -> bool:
        pattern = rule.pattern.replace(os.sep, "/")
        parts = rel.split("/")

        if rule.directory_only:
            dir_parts = parts if is_dir else parts[:-1]
            if not dir_parts:
                return False
            if rule.anchored or "/" in pattern:
                dir_rel = "/".join(dir_parts)
                return (
                    dir_rel == pattern
                    or dir_rel.startswith(f"{pattern}/")
                    or fnmatch(dir_rel, pattern)
                )
            return any(fnmatch(part, pattern) for part in dir_parts)

        if rule.anchored or "/" in pattern:
            return rel == pattern or fnmatch(rel, pattern)

        return fnmatch(parts[-1], pattern)

    def _render(self, snapshot: _RepoSnapshot, user_text: str, req: Request) -> str:
        max_chars = self._settings.harpcache_max_context_chars
        sections: list[str] = [
            "<HarpCache>",
            "Use this read-only local project context to ground the answer. "
            "If it is insufficient, say what file or command output is needed.",
            f"Repo: {snapshot.name}",
            f"Root: {snapshot.host_root}",
            f"PWD: {snapshot.pwd or '.'}",
        ]
        if snapshot.branch or snapshot.head:
            sections.append(f"Git: branch={snapshot.branch or '-'} head={snapshot.head or '-'}")
        if snapshot.ignored_by:
            sections.append("Ignore files applied: " + ", ".join(snapshot.ignored_by))

        rules = self._project_rules(req)
        if rules:
            sections.append("Project rules:\n" + self._join_snippets(rules))

        if snapshot.files:
            shown = snapshot.files[: self._settings.harpcache_manifest_entries]
            sections.append("File manifest:\n" + "\n".join(f"- {path}" for path in shown))

        if snapshot.important_files:
            sections.append("Important files:\n" + self._join_snippets(snapshot.important_files))

        relevant = self._relevant_snippets(snapshot, user_text)
        if relevant:
            sections.append("Relevant snippets:\n" + self._join_snippets(relevant))

        text = "\n\n".join(sections) + "\n</HarpCache>"
        return text[:max_chars]

    def _relevant_snippets(self, snapshot: _RepoSnapshot, user_text: str) -> dict[str, str]:
        terms = {term.lower() for term in _TOKEN_RE.findall(user_text)}
        if not terms:
            return {}

        scored: list[tuple[int, str]] = []
        for rel in snapshot.files:
            lower = rel.lower()
            score = sum(10 for term in terms if term in lower)
            if Path(rel).name in _IMPORTANT_FILENAMES:
                score += 5
            if Path(rel).suffix in _TEXT_EXTENSIONS:
                score += 1
            if score:
                scored.append((score, rel))

        scored.sort(reverse=True)
        snippets: dict[str, str] = {}
        for _, rel in scored[: self._settings.harpcache_relevant_files]:
            content = self._read_text(snapshot.repo_root / rel)
            if content:
                snippets[rel] = content
        return snippets

    @staticmethod
    def _project_rules(req: Request) -> dict[str, str]:
        rules: dict[str, str] = {}
        for project_rules in req.input.context.project_rules:
            for active in project_rules.active_rule_files:
                if active.file_path and active.content:
                    rules[active.file_path] = active.content
        return rules

    def _read_text(self, path: Path) -> str:
        try:
            stat = path.stat()
        except OSError:
            return ""
        if stat.st_size > self._settings.harpcache_max_file_bytes:
            return ""
        try:
            data = path.read_bytes()
        except OSError:
            return ""
        if b"\x00" in data:
            return ""
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return ""
        return text[: self._settings.harpcache_max_snippet_chars].strip()

    def _should_skip_file(self, path: Path) -> bool:
        if path.name in _SKIP_FILENAMES:
            return True
        if path.name.startswith(".env"):
            return True
        if path.suffix and path.suffix not in _TEXT_EXTENSIONS:
            return True
        return False

    @staticmethod
    def _inside_root(path: Path, root: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(root.resolve(strict=False))
        except ValueError:
            return False
        return True

    @staticmethod
    def _safe_relpath(path: Path, root: Path) -> str:
        try:
            return str(path.relative_to(root))
        except ValueError:
            return str(path)

    @staticmethod
    def _join_snippets(snippets: dict[str, str]) -> str:
        return "\n\n".join(f"--- {path} ---\n{content}" for path, content in snippets.items())

    def _evict_if_needed(self) -> None:
        max_entries = self._settings.harpcache_max_repos
        if len(self._snapshots) <= max_entries:
            return
        oldest = sorted(self._snapshots.items(), key=lambda item: item[1].built_at)
        for key, _ in oldest[: len(self._snapshots) - max_entries]:
            self._snapshots.pop(key, None)
