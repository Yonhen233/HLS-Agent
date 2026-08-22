from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class SchedulerPolicy:
    max_workers: int = 2
    max_parallel_llm_calls: int = 1


class BoundedScheduler:
    """Small bounded scheduler; LLM calls remain serialized by policy."""

    def __init__(self, policy: SchedulerPolicy | None = None, hooks=None, run_id: str | None = None):
        self.policy = policy or SchedulerPolicy()
        self.hooks = hooks
        self.run_id = run_id

    def run_independent(
        self,
        jobs: dict[str, Callable[[], Any]],
        *,
        kind: str = "tool",
    ) -> dict[str, Any]:
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
        self.policy = SchedulerPolicy(
            max_workers=max(1, min(self.policy.max_workers, int(max_workers))) if max_workers is not None else self.policy.max_workers,
            max_parallel_llm_calls=(
                max(1, min(self.policy.max_parallel_llm_calls, int(max_parallel_llm_calls)))
                if max_parallel_llm_calls is not None
                else self.policy.max_parallel_llm_calls
            ),
        )

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.hooks:
            self.hooks.emit(event, {"run_id": self.run_id, **payload})
