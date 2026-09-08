"""core layer implementation for scheduler.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class SchedulerPolicy:
    """Coordinate SchedulerPolicy within the scheduler boundary.

    The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
    """
    max_workers: int = 2
    max_parallel_llm_calls: int = 1


class BoundedScheduler:
    """Small bounded scheduler; LLM calls remain serialized by policy."""

    def __init__(self, policy: SchedulerPolicy | None = None, hooks=None, run_id: str | None = None):
        """Implement the internal __init__ helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            policy: Value supplied by the caller and validated by the surrounding schema.
            hooks: Value supplied by the caller and validated by the surrounding schema.
            run_id: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.policy = policy or SchedulerPolicy()
        self.hooks = hooks
        self.run_id = run_id

    def run_independent(
        self,
        jobs: dict[str, Callable[[], Any]],
        *,
        kind: str = "tool",
    ) -> dict[str, Any]:
        """Execute run_independent at the scheduler boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            jobs: Value supplied by the caller and validated by the surrounding schema.
            kind: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if not jobs:
            return {}
        configured = self.policy.max_parallel_llm_calls if kind == "llm" else self.policy.max_workers
        worker_limit = max(1, min(configured, len(jobs)))
        self._emit("SchedulerBatchStarted", {"kind": kind, "job_count": len(jobs), "max_workers": worker_limit})
        results: dict[str, Any] = {}
        try:
            if worker_limit == 1:
                for name, job in jobs.items():
                    results[name] = job()
            else:
                with ThreadPoolExecutor(max_workers=worker_limit, thread_name_prefix="agent-tool") as executor:
                    futures = {executor.submit(job): name for name, job in jobs.items()}
                    for future in as_completed(futures):
                        results[futures[future]] = future.result()
        except Exception as exc:
            self._emit(
                "SchedulerBatchFailed",
                {"kind": kind, "job_count": len(jobs), "max_workers": worker_limit, "error_type": type(exc).__name__},
            )
            raise
        self._emit("SchedulerBatchFinished", {"kind": kind, "job_count": len(jobs), "max_workers": worker_limit})
        return results

    def apply_limits(self, *, max_workers: int | None = None, max_parallel_llm_calls: int | None = None) -> None:
        """Execute apply_limits at the scheduler boundary.

        This callable keeps structured inputs and outputs at a stable boundary so the surrounding Agent Harness can trace, validate, and recover the operation.

        Args:
            max_workers: Value supplied by the caller and validated by the surrounding schema.
            max_parallel_llm_calls: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        self.policy = SchedulerPolicy(
            max_workers=max(1, min(self.policy.max_workers, int(max_workers))) if max_workers is not None else self.policy.max_workers,
            max_parallel_llm_calls=(
                max(1, min(self.policy.max_parallel_llm_calls, int(max_parallel_llm_calls)))
                if max_parallel_llm_calls is not None
                else self.policy.max_parallel_llm_calls
            ),
        )

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        """Implement the internal _emit helper.

        Keep this helper focused on local normalization or calculation; callers should enforce public permission and evidence boundaries.

        Args:
            event: Value supplied by the caller and validated by the surrounding schema.
            payload: Value supplied by the caller and validated by the surrounding schema.

        Returns:
            The structured value promised by the function signature.
        """
        if self.hooks:
            self.hooks.emit(event, {"run_id": self.run_id, **payload})
