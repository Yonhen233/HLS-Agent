"""Test contracts and regression checks for test_interactive_chat.py.

This module is part of the DL-to-HLS Agent Harness. It owns the boundary named by its path and should keep raw artifacts, structured state, permissions, and tool calls separated according to the project contracts.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dl_op_to_hls.chat.loop import ChatTurnResult, InteractiveChat


def test_chat_turn_result_is_compact(tmp_path):
    """Verify the test_chat_turn_result_is_compact contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        tmp_path: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    state = SimpleNamespace(
        session_id="session_1",
        run_id="run_1",
        status="partial_success",
        selected_path="existing_hls_project_path",
        run_dir=tmp_path,
        todos=[SimpleNamespace(status="completed"), SimpleNamespace(status="skipped")],
        errors=[{"error_type": "VivadoNotFoundError"}],
        artifacts={"run_dir": str(tmp_path)},
    )

    result = ChatTurnResult.from_state(state).to_dict()

    assert result["todo_progress"] == {"completed": 1, "total": 2}
    assert "raw" not in str(result).lower()


def test_chat_reuses_session_and_handles_commands(monkeypatch):
    """Verify the test_chat_reuses_session_and_handles_commands contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        monkeypatch: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    calls = []

    class FakeSessionManager:
        """Coordinate FakeSessionManager within the test_interactive_chat boundary.

        The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
        """
        def get(self, session_id):
            """Verify the get contract.

            The test should fail on a real contract regression rather than hide an unsupported path.

            Args:
                session_id: Value supplied by the caller and validated by the surrounding schema.

            Returns:
                The structured value promised by the function signature.
            """
            return {"session_id": session_id, "status": "completed", "run_id": "run_1", "run_ids": ["run_1"], "summary": "ok"}

    class FakeAgent:
        """Coordinate FakeAgent within the test_interactive_chat boundary.

        The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
        """
        session_manager = FakeSessionManager()

    class FakeState:
        """Coordinate FakeState within the test_interactive_chat boundary.

        The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
        """
        session_id = "session_old"
        run_id = "run_new"
        status = "success"
        selected_path = "hls4ml_path"
        artifacts = {"run_dir": "runs/run_new"}
        todos = []
        errors = []

    class FakeRuntime:
        """Coordinate FakeRuntime within the test_interactive_chat boundary.

        The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
        """
        def __init__(self, agent, *, session_id, user_id, project_id):
            """Verify the __init__ contract.

            The test should fail on a real contract regression rather than hide an unsupported path.

            Args:
                agent: Value supplied by the caller and validated by the surrounding schema.
                session_id: Value supplied by the caller and validated by the surrounding schema.
                user_id: Value supplied by the caller and validated by the surrounding schema.
                project_id: Value supplied by the caller and validated by the surrounding schema.

            Returns:
                The structured value promised by the function signature.
            """
            del agent, user_id, project_id
            self.session_id = session_id or "session_created"

        def run(self, message):
            """Verify the run contract.

            The test should fail on a real contract regression rather than hide an unsupported path.

            Args:
                message: Value supplied by the caller and validated by the surrounding schema.

            Returns:
                The structured value promised by the function signature.
            """
            calls.append((message, self.session_id))
            return FakeState()

    monkeypatch.setattr("dl_op_to_hls.chat.loop.LLMFirstRuntime", FakeRuntime)
    inputs = iter(["/status", "first request", "second request", "/exit"])
    output = []
    chat = InteractiveChat(FakeAgent(), session_id="session_old", input_fn=lambda _: next(inputs), output_fn=output.append)

    assert chat.run() == 0
    assert calls == [("first request", "session_old"), ("second request", "session_old")]
    assert any("session_old" in item for item in output)


def test_chat_keeps_session_id_when_runtime_fails(monkeypatch):
    """Verify the test_chat_keeps_session_id_when_runtime_fails contract.

    The test should fail on a real contract regression rather than hide an unsupported path.

    Args:
        monkeypatch: Value supplied by the caller and validated by the surrounding schema.

    Returns:
        The structured value promised by the function signature.
    """
    class FakeRuntime:
        """Coordinate FakeRuntime within the test_interactive_chat boundary.

        The class owns the state or policy described by its public methods. Use the class through those methods so schema validation, permissions, trace events, and evidence rules remain centralized.
        """
        def __init__(self, agent, *, session_id, user_id, project_id):
            """Verify the __init__ contract.

            The test should fail on a real contract regression rather than hide an unsupported path.

            Args:
                agent: Value supplied by the caller and validated by the surrounding schema.
                session_id: Value supplied by the caller and validated by the surrounding schema.
                user_id: Value supplied by the caller and validated by the surrounding schema.
                project_id: Value supplied by the caller and validated by the surrounding schema.

            Returns:
                The structured value promised by the function signature.
            """
            del agent, user_id, project_id
            self.session_id = session_id or "session_created"

        def run(self, message):
            """Verify the run contract.

            The test should fail on a real contract regression rather than hide an unsupported path.

            Args:
                message: Value supplied by the caller and validated by the surrounding schema.

            Returns:
                The structured value promised by the function signature.
            """
            del message
            raise RuntimeError("task interpretation failed")

    monkeypatch.setattr("dl_op_to_hls.chat.loop.LLMFirstRuntime", FakeRuntime)
    output = []
    inputs = iter(["request", "/exit"])
    chat = InteractiveChat(object(), input_fn=lambda _: next(inputs), output_fn=output.append)

    assert chat.run() == 0
    assert '"session_id": "session_created"' in "\n".join(output)
