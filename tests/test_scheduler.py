"""Test contracts and regression checks for test_scheduler.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

import threading
import time

from dl_op_to_hls.core.scheduler import BoundedScheduler, SchedulerPolicy


def test_scheduler_bounds_parallel_tool_jobs():
    """Verify the test_scheduler_bounds_parallel_tool_jobs contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    active = 0
    peak = 0
    lock = threading.Lock()

    def job():
        """Verify the job contract.

        The test should fail on a real contract regression rather than hide an unsupported path.

        Returns:
            The structured value promised by the function signature.
        """
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return "ok"

    scheduler = BoundedScheduler(SchedulerPolicy(max_workers=2, max_parallel_llm_calls=1))
    results = scheduler.run_independent({f"job_{index}": job for index in range(4)})

    assert len(results) == 4
    assert peak <= 2


def test_scheduler_serializes_llm_jobs():
    """Verify the test_scheduler_serializes_llm_jobs contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    scheduler = BoundedScheduler(SchedulerPolicy(max_workers=4, max_parallel_llm_calls=1))
    order = []
    scheduler.run_independent({"first": lambda: order.append("first"), "second": lambda: order.append("second")}, kind="llm")
    assert order == ["first", "second"]


def test_scheduler_traces_batch_failure():
    """Verify the test_scheduler_traces_batch_failure contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Returns:
        The structured value promised by the function signature.
    """
    events = []

    class Hooks:
        """Coordinate Hooks within the test_scheduler boundary.

        The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
        """
        def emit(self, event, payload):
            """Verify the emit contract.

            The test should fail on a real contract regression rather than hide an unsupported path.

            Args:
                event: Value supplied by the caller and validated by the surrounding schema.
                payload: Value supplied by the caller and validated by the surrounding schema.

            Returns:
                The structured value promised by the function signature.
            """
            events.append((event, payload))

    scheduler = BoundedScheduler(SchedulerPolicy(max_workers=1), hooks=Hooks())
    try:
        scheduler.run_independent({"bad": lambda: (_ for _ in ()).throw(ValueError("bad"))})
    except ValueError:
        pass
    else:
        raise AssertionError("Expected scheduler job failure")

    assert any(event == "SchedulerBatchFailed" for event, _ in events)
