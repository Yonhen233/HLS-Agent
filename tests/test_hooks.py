from dl_op_to_hls.core.hooks import HookManager


def test_hooks_emit_events():
    hooks = HookManager()
    seen = []
    hooks.register("RunStarted", lambda payload: seen.append(payload["event"]))
    hooks.emit("RunStarted", {"run_id": "r1"})
    assert seen == ["RunStarted"]

