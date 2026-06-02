from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CandidateSandboxRule:
    name: str
    pattern: str
    message: str


class CandidateSandbox:
    """Pattern-based safety scanner for LLM-generated HLS C++ candidates."""

    RULES = [
        CandidateSandboxRule("system_call", r"\bsystem\s*\(", "system() is not allowed in HLS candidates."),
        CandidateSandboxRule("popen_call", r"\bpopen\s*\(", "popen() is not allowed in HLS candidates."),
        CandidateSandboxRule("process_spawn", r"\b(CreateProcess|ShellExecute|fork|execv|execl)\b", "Process spawning APIs are not allowed."),
        CandidateSandboxRule("file_io_include", r"#\s*include\s*[<\"](cstdlib|stdlib\.h|fstream|filesystem|windows\.h|unistd\.h)[>\"]", "Host file-system/OS includes are not allowed."),
        CandidateSandboxRule("network_include", r"#\s*include\s*[<\"](winsock2\.h|sys/socket\.h|netinet/in\.h)[>\"]", "Network includes are not allowed."),
        CandidateSandboxRule("inline_asm", r"\b(__asm__|asm)\s*(volatile)?\s*\(", "Inline assembly is not allowed."),
        CandidateSandboxRule("pragma_message", r"#\s*pragma\s+message\b", "Compiler message pragmas are not allowed in generated candidates."),
    ]

    def scan_candidate_payload(self, candidate: dict[str, Any]) -> dict[str, Any]:
        violations: list[dict[str, Any]] = []
        for file_item in candidate.get("files", []):
            relative_path = str(file_item.get("relative_path", ""))
            content = str(file_item.get("content", ""))
            violations.extend(self.scan_text(content, relative_path))
        return {"status": "invalid" if violations else "valid", "violations": violations}

    def scan_text(self, content: str, relative_path: str = "<candidate>") -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []
        for rule in self.RULES:
            for match in re.finditer(rule.pattern, content, flags=re.IGNORECASE):
                line_no = content.count("\n", 0, match.start()) + 1
                violations.append(
                    {
                        "rule": rule.name,
                        "message": rule.message,
                        "relative_path": relative_path,
                        "line": line_no,
                    }
                )
        return violations
