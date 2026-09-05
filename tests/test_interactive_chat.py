from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dl_op_to_hls.chat.loop import ChatTurnResult, InteractiveChat


def test_chat_turn_result_is_compact(tmp_path):
    state = SimpleNamespace(
        session_id="session_1",
        run_id="run_1",
        status="partial_success",
        selected_path="existing_hls_project_path",
        run_dir=tmp_path,
        todos=[SimpleNamespace(status="completed"), SimpleNamespace(status="skipped")],
        errors=[{"error_type": "VivadoNotFoundError"}],
    )

    result = ChatTurnResult.from_state(state).to_dict()

    assert result["todo_progress"] == {"completed": 1, "total": 2}
    assert "raw" not in str(result).lower()


def test_chat_reuses_session_and_handles_commands(monkeypatch):
    calls = []

    class FakeSessionManager:
        def get(self, session_id):
            return {"session_id": session_id, "status": "completed", "run_id": "run_1", "run_ids": ["run_1"], "summary": "ok"}

    class FakeAgent:
        session_manager = FakeSessionManager()

    class FakeState:
        session_id = "session_new"
        run_id = "run_new"
        status = "success"
        selected_path = "hls4ml_path"
        run_dir = Path("runs/run_new")
        todos = []
        errors = []

    def fake_run(message, **kwargs):
        calls.append((message, kwargs["session_id"]))
        return FakeState()

    monkeypatch.setattr("dl_op_to_hls.chat.loop.run_task_llm", fake_run)
    inputs = iter(["/status", "first request", "second request", "/exit"])
    output = []
    chat = InteractiveChat(FakeAgent(), session_id="session_old", input_fn=lambda _: next(inputs), output_fn=output.append)

    assert chat.run() == 0
    assert calls == [("first request", "session_old"), ("second request", "session_new")]
    assert any("session_old" in item for item in output)
