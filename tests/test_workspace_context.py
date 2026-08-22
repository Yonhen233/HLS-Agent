from __future__ import annotations

from dl_op_to_hls.core.permissions import PermissionGate
from dl_op_to_hls.core.workspace_context import WorkspaceContext


def _gate(root):
    return PermissionGate(
        {
            "filesystem": {
                "allowed_read_dirs": ["."],
                "allowed_write_dirs": ["./runs"],
                "denied_dirs": [],
            }
        },
        root,
    )


def test_incremental_mixed_workspace_index_and_citations(tmp_path):
    (tmp_path / "module.py").write_text("class Model:\n    def run(self):\n        return 1\n", encoding="utf-8")
    (tmp_path / "kernel.cpp").write_text("int dense(float x) {\n  return (int)x;\n}\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# Architecture\nThe dense path uses a verified report.\n", encoding="utf-8")
    context = WorkspaceContext(tmp_path, permission_gate=_gate(tmp_path))

    first = context.scan()
    second = context.scan()
    assert first["documents"] == 3
    assert first["changed"] == 3
    assert second["changed"] == 0
    assert context.symbol_search("Model")["matches"][0]["kind"] == "class"
    assert context.symbol_search("dense")["matches"][0]["path"] == "kernel.cpp"

    matches = context.search("verified report")["matches"]
    assert matches and matches[0]["citation"].startswith("notes.md:L")
    batch = context.read_batch([{"path": "module.py", "start_line": 1, "end_line": 2}])
    assert batch["documents"][0]["citation"] == "module.py:L1-L2"
    assert "class Model" in batch["documents"][0]["content"]


def test_workspace_context_rejects_read_outside_policy(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    context = WorkspaceContext(workspace, permission_gate=_gate(workspace))
    result = context.read_batch([{"path": str(outside)}])
    assert result["documents"][0]["status"] == "deny"
