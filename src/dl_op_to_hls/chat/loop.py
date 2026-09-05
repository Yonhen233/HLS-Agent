from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..main_agent.agent import MainAgent
from ..main_agent.llm_runtime import LLMFirstRuntime


@dataclass
class ChatTurnResult:
    """Compact terminal-facing projection of a full AgentState."""

    session_id: str
    run_id: str
    status: str
    selected_path: str | None
    summary_path: str
    completed_todos: int
    total_todos: int
    errors: list[dict]

    @classmethod
    def from_state(cls, state) -> "ChatTurnResult":
        todos = list(getattr(state, "todos", []) or [])
        return cls(
            session_id=str(getattr(state, "session_id", None) or ""),
            run_id=str(state.run_id),
            status=str(state.status),
            selected_path=getattr(state, "selected_path", None),
            summary_path=str(Path(state.artifacts.get("run_dir", f"runs/{state.run_id}")) / "summary.md"),
            completed_todos=sum(item.status in {"completed", "completed_with_warning"} for item in todos),
            total_todos=len(todos),
            errors=list(getattr(state, "errors", []) or [])[-3:],
        )

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "status": self.status,
            "selected_path": self.selected_path,
            "summary_path": self.summary_path,
            "todo_progress": {"completed": self.completed_todos, "total": self.total_todos},
            "errors": self.errors,
        }


class InteractiveChat:
    """Run multiple natural-language turns against one durable Agent session."""

    def __init__(
        self,
        agent: MainAgent | None = None,
        *,
        session_id: str | None = None,
        user_id: str = "local-user",
        project_id: str | None = None,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ):
        self.agent = agent or MainAgent()
        self.session_id = session_id
        self.user_id = user_id
        self.project_id = project_id
        self.input_fn = input_fn
        self.output_fn = output_fn

    def run(self) -> int:
        self.output_fn("DL-Operator-to-HLS Agent chat. 输入 /help 查看命令，输入 /exit 退出。")
        if self.session_id:
            self._show_session("已加载会话")
        while True:
            try:
                message = self.input_fn("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                self.output_fn("\n会话已退出。")
                return 0
            if not message:
                continue
            if message in {"/quit", "/exit"}:
                self.output_fn("会话已退出。")
                return 0
            if message == "/help":
                self._print_help()
                continue
            if message in {"/session", "/status"}:
                self._show_session("当前会话")
                continue
            if message.startswith("/"):
                self.output_fn(f"未知命令：{message}。输入 /help 查看可用命令。")
                continue
            self._run_turn(message)

    def _run_turn(self, message: str) -> None:
        runtime = LLMFirstRuntime(
            self.agent,
            session_id=self.session_id,
            user_id=self.user_id,
            project_id=self.project_id,
        )
        try:
            state = runtime.run(message)
            # Keep the session even when a later initialization stage raises.
            result = ChatTurnResult.from_state(state)
            self.output_fn(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            if result.errors:
                self.output_fn("本轮存在错误，完整详情已保存到 state.json 和 trace.jsonl。")
        except Exception as exc:
            self.output_fn(json.dumps({
                "status": "error",
                "session_id": runtime.session_id,
                "error_type": type(exc).__name__,
                "message": str(exc),
            }, ensure_ascii=False, indent=2))
        finally:
            # Runtime creates the session before task interpretation; preserve it
            # even when interpretation fails before an AgentState exists.
            self.session_id = runtime.session_id

    def _show_session(self, prefix: str) -> None:
        if not self.session_id:
            self.output_fn(f"{prefix}：尚未创建。")
            return
        try:
            session = self.agent.session_manager.get(self.session_id)
        except KeyError:
            self.output_fn(f"{prefix}：{self.session_id} 不存在。")
            return
        self.output_fn(json.dumps({
            "session_id": session.get("session_id"),
            "status": session.get("status"),
            "run_id": session.get("run_id"),
            "run_ids": session.get("run_ids", []),
            "summary": session.get("summary", ""),
        }, ensure_ascii=False, indent=2))

    def _print_help(self) -> None:
        self.output_fn(
            "可用命令：\n"
            "  /status 或 /session  查看当前持久化会话\n"
            "  /help                查看帮助\n"
            "  /exit 或 /quit      退出聊天，之后可用 --session-id 恢复\n"
            "普通文本会作为新的用户请求提交给同一个 Agent session。"
        )
