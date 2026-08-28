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
    """Pattern-based safety and HLS-feasibility scanner for LLM candidates.

    It is intentionally conservative: this scanner rejects known-invalid HLS
    constructs before expensive CSim/csynth.  Passing it is never evidence of
    numerical equivalence or resource feasibility.
    """

    RULES = [
        CandidateSandboxRule("system_call", r"\bsystem\s*\(", "system() is not allowed in HLS candidates."),
        CandidateSandboxRule("popen_call", r"\bpopen\s*\(", "popen() is not allowed in HLS candidates."),
        CandidateSandboxRule("process_spawn", r"\b(CreateProcess|ShellExecute|fork|execv|execl)\b", "Process spawning APIs are not allowed."),
        CandidateSandboxRule("file_io_include", r"#\s*include\s*[<\"](cstdlib|stdlib\.h|fstream|filesystem|windows\.h|unistd\.h)[>\"]", "Host file-system/OS includes are not allowed."),
        CandidateSandboxRule("network_include", r"#\s*include\s*[<\"](winsock2\.h|sys/socket\.h|netinet/in\.h)[>\"]", "Network includes are not allowed."),
        CandidateSandboxRule("inline_asm", r"\b(__asm__|asm)\s*(volatile)?\s*\(", "Inline assembly is not allowed."),
        CandidateSandboxRule(
            "dynamic_memory",
            r"\b(?:new\s+[A-Za-z_]|malloc\s*\(|calloc\s*\(|realloc\s*\(|free\s*\()",
            "Dynamic memory allocation is not synthesizable and is not allowed in HLS candidates.",
        ),
        CandidateSandboxRule("pragma_message", r"#\s*pragma\s+message\b", "Compiler message pragmas are not allowed in generated candidates."),
    ]

    def scan_candidate_payload(self, candidate: dict[str, Any], contract: dict[str, Any] | None = None) -> dict[str, Any]:
        violations: list[dict[str, Any]] = []
        contract = contract or {}
        for file_item in candidate.get("files", []):
            relative_path = str(file_item.get("relative_path", ""))
            content = str(file_item.get("content", ""))
            violations.extend(self.scan_text(content, relative_path))
            violations.extend(self.scan_hls_contract(content, relative_path, contract))
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

    def scan_hls_contract(self, content: str, relative_path: str, contract: dict[str, Any]) -> list[dict[str, Any]]:
        """Reject HLS directives known to be invalid or explosive for a task.

        ``m_axi`` requires a byte-aligned port in Vivado HLS 2018.3.  Complete
        partitioning of a large mutable feature map creates a register array
        and is exactly the failure mode observed in the real CIFAR candidate.
        The candidate may still partition compact constant weight arrays.
        """

        violations: list[dict[str, Any]] = []
        data_bitwidth = contract.get("data_bitwidth")
        if isinstance(data_bitwidth, int) and data_bitwidth > 0 and data_bitwidth % 8:
            for match in re.finditer(r"#\s*pragma\s+HLS\s+INTERFACE\s+m_axi\b", content, flags=re.IGNORECASE):
                violations.append(
                    self._contract_violation(
                        "non_byte_aligned_m_axi",
                        "m_axi is invalid for a non-byte-aligned fixed-point port in Vivado HLS 2018.3.",
                        relative_path,
                        content,
                        match.start(),
                    )
                )

        max_partition_elements = int(contract.get("max_complete_partition_elements", 256))
        mutable_arrays = self._mutable_array_sizes(content)
        pragma_pattern = r"#\s*pragma\s+HLS\s+ARRAY_PARTITION\s+variable\s*=\s*([A-Za-z_]\w*)\s+complete\b"
        for match in re.finditer(pragma_pattern, content, flags=re.IGNORECASE):
            variable = match.group(1)
            size = mutable_arrays.get(variable)
            if size is not None and size > max_partition_elements:
                violations.append(
                    self._contract_violation(
                        "large_mutable_complete_partition",
                        f"Complete partition of mutable array {variable}[{size}] exceeds the candidate contract limit {max_partition_elements}.",
                        relative_path,
                        content,
                        match.start(),
                    )
                )
        return violations

    @staticmethod
    def _mutable_array_sizes(content: str) -> dict[str, int]:
        """Find simple local C-style mutable arrays and their static element counts."""

        sizes: dict[str, int] = {}
        declaration = re.compile(
            r"(?m)^\s*(?!.*\bconst\b)(?:static\s+)?[A-Za-z_]\w*(?:\s*<[^;{}()]+>)?\s+([A-Za-z_]\w*)\s*((?:\[\s*\d+\s*\])+?)\s*;"
        )
        for match in declaration.finditer(content):
            dimensions = [int(value) for value in re.findall(r"\[\s*(\d+)\s*\]", match.group(2))]
            if dimensions:
                product = 1
                for value in dimensions:
                    product *= value
                sizes[match.group(1)] = product
        return sizes

    @staticmethod
    def _contract_violation(rule: str, message: str, relative_path: str, content: str, offset: int) -> dict[str, Any]:
        return {
            "rule": rule,
            "message": message,
            "relative_path": relative_path,
            "line": content.count("\n", 0, offset) + 1,
        }
