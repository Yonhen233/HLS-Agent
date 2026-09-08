"""Test contracts and regression checks for test_sessions.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from concurrent.futures import ThreadPoolExecutor

from dl_op_to_hls.core.sessions import SessionManager


def _state(run_id: str, status: str = "initialized") -> dict:
    """Verify the _state contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        run_id: Value supplied by the caller and validated by the surrounding schema.
        status: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    return {"run_id": run_id, "task": {"task_type": "operator", "name": "dense"}, "status": status, "todos": []}


def test_session_checkpoint_interrupt_resume_and_rollback(tmp_path):
    """Verify the test_session_checkpoint_interrupt_resume_and_rollback contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    manager = SessionManager(tmp_path / "sessions")
    session = manager.create("start dense task", "session_demo")
    manager.bind_run(session["session_id"], "run_1")
    first = manager.create_checkpoint(
        session["session_id"],
        _state("run_1"),
        "planned",
        runtime={"run_budget": {"llm_calls": 2}},
    )
    second = manager.create_checkpoint(session["session_id"], _state("run_1", "partial_success"), "todo_boundary")

    manager.request_interrupt(session["session_id"], "pause now")
    assert manager.interrupt_requested(session["session_id"]) is True
    manager.mark_interrupted(session["session_id"], "pause now")
    manager.mark_running(session["session_id"])

    rolled_back = manager.rollback(session["session_id"], checkpoint_id=first["checkpoint_id"])
    assert rolled_back["checkpoint"]["checkpoint_id"] == first["checkpoint_id"]
    assert rolled_back["session"]["generation"] == 2
    assert second["checkpoint_id"] != first["checkpoint_id"]
    assert first["runtime"]["run_budget"]["llm_calls"] == 2


def test_session_supports_follow_up_and_retraction(tmp_path):
    """Verify the test_session_supports_follow_up_and_retraction contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    manager = SessionManager(tmp_path / "sessions")
    manager.create("first", "session_demo")
    manager.create("follow up", "session_demo")

    message = manager.retract_last_user_message("session_demo")
    session = manager.get("session_demo")

    assert message["content"] == "follow up"
    assert any(item["content"] == "follow up" and item["retracted"] for item in session["messages"])


def test_session_approval_is_scoped_to_tool_and_argument_hash(tmp_path):
    """Verify the test_session_approval_is_scoped_to_tool_and_argument_hash contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    manager = SessionManager(tmp_path / "sessions")
    manager.create("run", "session_demo")
    approval = manager.create_approval_request(
        "session_demo",
        tool_name="shell.run",
        args_hash="abc123",
        reason="Command requires approval",
    )
    manager.decide_approval("session_demo", approval["approval_id"], "approved")

    assert manager.approval_status("session_demo", "shell.run", "abc123") == "approved"
    assert manager.approval_status("session_demo", "shell.run", "different") is None


def test_message_ids_remain_monotonic_after_context_compaction(tmp_path):
    """Verify the test_message_ids_remain_monotonic_after_context_compaction contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    manager = SessionManager(tmp_path / "sessions")
    manager.create("first", "session_demo")
    for index in range(12):
        manager.append_message("session_demo", "assistant", f"message {index}")
    manager.compact_messages("session_demo", keep_recent=4)

    message = manager.append_message("session_demo", "user", "after compaction")

    assert message["message_id"] == "turn_0014"
    assert manager.get("session_demo")["next_message_seq"] == 15


def test_database_is_source_of_truth_across_manager_instances(tmp_path):
    """Verify the test_database_is_source_of_truth_across_manager_instances contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    sessions_root = tmp_path / "sessions"
    first = SessionManager(sessions_root)
    first.create("initial", "session_shared")
    checkpoint = first.create_checkpoint("session_shared", _state("run_shared"), "planned")

    projection = sessions_root / "session_shared" / "session.json"
    projection.write_text("{broken projection", encoding="utf-8")
    second = SessionManager(sessions_root)

    assert second.get("session_shared")["storage_backend"] == "sqlite"
    assert second.load_active_checkpoint("session_shared")["checkpoint_id"] == checkpoint["checkpoint_id"]
    second.append_message("session_shared", "assistant", "visible to every worker")
    assert first.get("session_shared")["messages"][-1]["content"] == "visible to every worker"
    assert "visible to every worker" in projection.read_text(encoding="utf-8")


def test_checkpoint_identity_is_scoped_to_session(tmp_path):
    """Verify the test_checkpoint_identity_is_scoped_to_session contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    manager = SessionManager(tmp_path / "sessions")
    manager.create("one", "session_one")
    manager.create("two", "session_two")

    first = manager.create_checkpoint("session_one", _state("run_one"), "planned")
    second = manager.create_checkpoint("session_two", _state("run_two"), "planned")

    assert first["checkpoint_id"] == "cp_000001"
    assert second["checkpoint_id"] == "cp_000001"
    assert manager.load_checkpoint("session_one", "cp_000001")["run_id"] == "run_one"
    assert manager.load_checkpoint("session_two", "cp_000001")["run_id"] == "run_two"


def test_concurrent_workers_preserve_message_order_and_single_use_approval(tmp_path):
    """Verify the test_concurrent_workers_preserve_message_order_and_single_use_approval contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    sessions_root = tmp_path / "sessions"
    first = SessionManager(sessions_root)
    second = SessionManager(sessions_root)
    first.create("initial", "session_concurrent")

    managers = [first, second] * 4
    with ThreadPoolExecutor(max_workers=4) as pool:
        messages = list(
            pool.map(
                lambda item: item[1].append_message(
                    "session_concurrent", "assistant", f"worker-{item[0]}"
                ),
                enumerate(managers),
            )
        )

    sequences = sorted(int(message["message_id"].split("_")[1]) for message in messages)
    assert sequences == list(range(2, 10))

    approval = first.create_approval_request(
        "session_concurrent",
        tool_name="shell.run",
        args_hash="single-use",
        reason="high-risk command",
        max_uses=1,
    )
    first.decide_approval("session_concurrent", approval["approval_id"], "approved")
    with ThreadPoolExecutor(max_workers=2) as pool:
        consumed = list(
            pool.map(
                lambda manager: manager.consume_approval(
                    "session_concurrent", "shell.run", "single-use"
                ),
                [first, second],
            )
        )

    assert consumed.count(True) == 1
    assert first.approval_status("session_concurrent", "shell.run", "single-use") == "consumed"
    events = first.list_events("session_concurrent")
    assert any(event["event"] == "SessionApprovalConsumed" for event in events)
