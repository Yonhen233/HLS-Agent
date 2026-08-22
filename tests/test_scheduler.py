import threading
import time

from dl_op_to_hls.core.scheduler import BoundedScheduler, SchedulerPolicy


def test_scheduler_bounds_parallel_tool_jobs():
    active = 0
    peak = 0
    lock = threading.Lock()

    def job():
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
    scheduler = BoundedScheduler(SchedulerPolicy(max_workers=4, max_parallel_llm_calls=1))
    order = []
    scheduler.run_independent({"first": lambda: order.append("first"), "second": lambda: order.append("second")}, kind="llm")
    assert order == ["first", "second"]


def test_scheduler_traces_batch_failure():
    events = []

    class Hooks:
        def emit(self, event, payload):
            events.append((event, payload))

    scheduler = BoundedScheduler(SchedulerPolicy(max_workers=1), hooks=Hooks())
    try:
        scheduler.run_independent({"bad": lambda: (_ for _ in ()).throw(ValueError("bad"))})
    except ValueError:
        pass
    else:
        raise AssertionError("Expected scheduler job failure")

    assert any(event == "SchedulerBatchFailed" for event, _ in events)
