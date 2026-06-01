import json

from dl_op_to_hls.core.hooks import HookManager
from dl_op_to_hls.main_agent.todo import TodoManager


def _manager(tmp_path, hooks=None):
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True, exist_ok=True)
    return TodoManager(run_dir, hooks=hooks)


def test_todo_create_from_plan(tmp_path):
    manager = _manager(tmp_path)
    todo_list = manager.create_from_plan("r1", ["Validate task schema", "Check hls4ml support"], {"task_type": "operator", "name": "demo"})
    assert len(todo_list.items) == 2
    assert todo_list.items[1].dependencies == ["todo_001"]


def test_todo_dependency_blocked(tmp_path):
    manager = _manager(tmp_path)
    todo_list = manager.create_from_plan("r1", ["A", "B"], {"task_type": "operator", "name": "demo"})
    next_item = manager.get_next_ready_item(todo_list)
    assert next_item.id == "todo_001"
    manager.mark_started("todo_001")
    ready = manager.get_next_ready_item(todo_list)
    assert ready is None
    assert manager.todo_list.items[1].status == "blocked"


def test_todo_mark_started(tmp_path):
    manager = _manager(tmp_path)
    manager.create_from_plan("r1", ["A"], {"task_type": "operator", "name": "demo"})
    manager.mark_started("todo_001")
    assert manager.todo_list.items[0].status == "in_progress"


def test_todo_mark_completed(tmp_path):
    manager = _manager(tmp_path)
    manager.create_from_plan("r1", ["A"], {"task_type": "operator", "name": "demo"})
    manager.mark_completed("todo_001", {"status": "success"})
    assert manager.todo_list.items[0].status == "completed"


def test_todo_mark_skipped(tmp_path):
    manager = _manager(tmp_path)
    manager.create_from_plan("r1", ["A"], {"task_type": "operator", "name": "demo"})
    manager.mark_skipped("todo_001", "skip")
    assert manager.todo_list.items[0].status == "skipped"


def test_todo_trace_events(tmp_path):
    hooks = HookManager()
    events = []
    hooks.register("*", lambda payload: events.append(payload["event"]))
    manager = _manager(tmp_path, hooks=hooks)
    manager.create_from_plan("r1", ["A"], {"task_type": "operator", "name": "demo"})
    manager.mark_started("todo_001")
    manager.mark_completed("todo_001", {"status": "success"})
    assert "TodoCreated" in events
    assert "TodoStarted" in events
    assert "TodoCompleted" in events


def test_todo_saved_to_json(tmp_path):
    manager = _manager(tmp_path)
    manager.create_from_plan("r1", ["A"], {"task_type": "operator", "name": "demo"})
    path = manager.save("r1")
    payload = json.loads(open(path, encoding="utf-8").read())
    assert payload["run_id"] == "r1"

