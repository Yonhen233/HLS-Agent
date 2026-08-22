from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hpp",
    ".json",
    ".md",
    ".py",
    ".rst",
    ".tcl",
    ".txt",
    ".yaml",
    ".yml",
}
DEFAULT_IGNORES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "runs",
}


@dataclass(frozen=True)
class SourceRange:
    path: str
    start_line: int
    end_line: int

    @property
    def citation(self) -> str:
        return f"{self.path}:L{self.start_line}-L{self.end_line}"


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    range: SourceRange
    signature: str = ""


class WorkspaceContext:
    """Permission-aware, incremental index for mixed document/code workspaces."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        permission_gate=None,
        index_path: str | Path | None = None,
        max_file_bytes: int = 1_000_000,
        extensions: set[str] | None = None,
        ignored_names: set[str] | None = None,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.permission_gate = permission_gate
        self.index_path = Path(index_path or (self.workspace_root / "runs" / "workspace_index.json"))
        self.max_file_bytes = max(1, int(max_file_bytes))
        self.extensions = {item.lower() for item in (extensions or DEFAULT_EXTENSIONS)}
        self.ignored_names = set(ignored_names or DEFAULT_IGNORES)
        self._manifest = self._load_manifest()

    def scan(self, paths: Iterable[str | Path] | None = None) -> dict[str, Any]:
        roots = list(paths or [self.workspace_root])
        previous = dict(self._manifest.get("documents", {}))
        documents: dict[str, dict[str, Any]] = {}
        changed = 0
        skipped: list[dict[str, str]] = []
        for path in self._iter_files(roots):
            relative = self._relative(path)
            permission = self._check_read(path)
            if permission["decision"] != "allow":
                skipped.append({"path": relative, "reason": permission["reason"]})
                continue
            try:
                stat = path.stat()
                if stat.st_size > self.max_file_bytes:
                    skipped.append({"path": relative, "reason": "file_too_large"})
                    continue
                digest = self._hash_file(path)
                old = previous.get(relative)
                if old and old.get("sha256") == digest:
                    documents[relative] = old
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                symbols = [self._symbol_dict(item) for item in self._extract_symbols(path, text)]
                documents[relative] = {
                    "path": relative,
                    "sha256": digest,
                    "size": stat.st_size,
                    "line_count": max(1, len(text.splitlines())),
                    "language": self._language(path),
                    "symbols": symbols,
                }
                changed += 1
            except OSError as exc:
                skipped.append({"path": relative, "reason": str(exc)})
        removed = sorted(set(previous) - set(documents))
        self._manifest = {"version": 1, "root": str(self.workspace_root), "documents": documents}
        self._write_manifest()
        return {
            "status": "success",
            "documents": len(documents),
            "changed": changed,
            "unchanged": len(documents) - changed,
            "removed": removed,
            "skipped": skipped,
            "index_path": str(self.index_path),
        }

    def read_batch(
        self,
        requests: list[dict[str, Any]],
        *,
        max_total_chars: int = 40_000,
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        remaining = max(0, int(max_total_chars))
        for request in requests:
            raw_path = str(request.get("path", ""))
            path = self._resolve(raw_path)
            permission = self._check_read(path)
            if permission["decision"] != "allow":
                results.append({"path": raw_path, "status": permission["decision"], "reason": permission["reason"]})
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError as exc:
                results.append({"path": raw_path, "status": "error", "reason": str(exc)})
                continue
            start = max(1, int(request.get("start_line", 1)))
            end = min(len(lines), int(request.get("end_line", min(len(lines), start + 199))))
            if end < start or remaining <= 0:
                excerpt = ""
                was_truncated = end >= start
            else:
                full_excerpt = "\n".join(f"{index:>6} | {lines[index - 1]}" for index in range(start, end + 1))
                was_truncated = len(full_excerpt) > remaining
                excerpt = full_excerpt[:remaining]
            remaining -= len(excerpt)
            source = SourceRange(self._relative(path), start, max(start, end))
            results.append({
                "path": source.path,
                "status": "success",
                "start_line": source.start_line,
                "end_line": source.end_line,
                "citation": source.citation,
                "content": excerpt,
                "truncated": was_truncated,
            })
        return {"status": "success", "documents": results, "remaining_chars": remaining}

    def search(self, query: str, *, top_k: int = 20, context_lines: int = 2) -> dict[str, Any]:
        terms = [item.lower() for item in re.findall(r"[A-Za-z_][A-Za-z0-9_]+|[\u4e00-\u9fff]+", query)]
        if not terms:
            return {"status": "success", "query": query, "matches": []}
        if not self._manifest.get("documents"):
            self.scan()
        matches: list[dict[str, Any]] = []
        for relative in self._manifest.get("documents", {}):
            path = self.workspace_root / relative
            if self._check_read(path)["decision"] != "allow":
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for index, line in enumerate(lines, start=1):
                lower = line.lower()
                hit_count = sum(lower.count(term) for term in terms)
                if not hit_count:
                    continue
                start = max(1, index - context_lines)
                end = min(len(lines), index + context_lines)
                source = SourceRange(relative, start, end)
                matches.append({
                    "path": relative,
                    "line": index,
                    "citation": source.citation,
                    "score": hit_count / max(1, len(terms)),
                    "excerpt": "\n".join(lines[start - 1 : end])[:2000],
                })
        matches.sort(key=lambda item: (-float(item["score"]), item["path"], item["line"]))
        return {"status": "success", "query": query, "matches": matches[: max(1, int(top_k))]}

    def symbol_search(self, query: str, *, top_k: int = 20, kind: str | None = None) -> dict[str, Any]:
        if not self._manifest.get("documents"):
            self.scan()
        needle = query.strip().lower()
        matches: list[dict[str, Any]] = []
        for document in self._manifest.get("documents", {}).values():
            for symbol in document.get("symbols", []):
                if kind and symbol.get("kind") != kind:
                    continue
                name = str(symbol.get("name", ""))
                if needle not in name.lower():
                    continue
                score = 1.0 if name.lower() == needle else 0.7 if name.lower().startswith(needle) else 0.4
                matches.append({**symbol, "score": score})
        matches.sort(key=lambda item: (-float(item["score"]), item["path"], item["start_line"]))
        return {"status": "success", "query": query, "matches": matches[: max(1, int(top_k))]}

    def _iter_files(self, roots: list[str | Path]):
        seen: set[Path] = set()
        for raw in roots:
            root = self._resolve(str(raw))
            candidates = [root] if root.is_file() else root.rglob("*") if root.is_dir() else []
            for path in candidates:
                if not path.is_file() or path in seen:
                    continue
                try:
                    relative_parts = path.resolve().relative_to(self.workspace_root).parts
                except ValueError:
                    relative_parts = path.parts
                if any(part in self.ignored_names for part in relative_parts):
                    continue
                if path.suffix.lower() not in self.extensions:
                    continue
                seen.add(path)
                yield path.resolve()

    def _extract_symbols(self, path: Path, text: str) -> list[Symbol]:
        suffix = path.suffix.lower()
        relative = self._relative(path)
        if suffix == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError:
                return []
            symbols: list[Symbol] = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    kind = "class" if isinstance(node, ast.ClassDef) else "function"
                    source = SourceRange(relative, int(node.lineno), int(getattr(node, "end_lineno", node.lineno)))
                    symbols.append(Symbol(node.name, kind, source))
            return symbols
        if suffix in {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"}:
            pattern = re.compile(
                r"^\s*(?:template\s*<[^>]+>\s*)?(?:[\w:<>~*&]+\s+)+(?P<name>[A-Za-z_]\w*(?:::\w+)*)\s*\([^;{}]*\)\s*(?:const\s*)?\{?\s*$"
            )
            symbols = []
            for line_no, line in enumerate(text.splitlines(), start=1):
                match = pattern.match(line)
                if match:
                    source = SourceRange(relative, line_no, line_no)
                    symbols.append(Symbol(match.group("name"), "function", source, line.strip()[:300]))
            return symbols
        if suffix in {".md", ".rst"}:
            symbols = []
            for line_no, line in enumerate(text.splitlines(), start=1):
                match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
                if match:
                    source = SourceRange(relative, line_no, line_no)
                    symbols.append(Symbol(match.group(2), f"heading_{len(match.group(1))}", source))
            return symbols
        return []

    def _check_read(self, path: Path) -> dict[str, str]:
        if self.permission_gate is None:
            return {"decision": "allow", "reason": "No permission gate configured."}
        return self.permission_gate.check_read_path(str(path))

    def _resolve(self, path: str) -> Path:
        candidate = Path(path).expanduser()
        return candidate.resolve() if candidate.is_absolute() else (self.workspace_root / candidate).resolve()

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.workspace_root).as_posix()
        except ValueError:
            return str(path.resolve())

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _language(path: Path) -> str:
        return {
            ".py": "python",
            ".c": "c",
            ".cc": "cpp",
            ".cpp": "cpp",
            ".cxx": "cpp",
            ".h": "cpp-header",
            ".hpp": "cpp-header",
            ".md": "markdown",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".tcl": "tcl",
        }.get(path.suffix.lower(), "text")

    @staticmethod
    def _symbol_dict(symbol: Symbol) -> dict[str, Any]:
        payload = asdict(symbol)
        source = payload.pop("range")
        payload.update(source)
        payload["citation"] = symbol.range.citation
        return payload

    def _load_manifest(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {"documents": {}}
        except (OSError, json.JSONDecodeError):
            return {"documents": {}}

    def _write_manifest(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.index_path.with_suffix(self.index_path.suffix + ".tmp")
        temporary.write_text(json.dumps(self._manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.index_path)
