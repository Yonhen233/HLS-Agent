"""Small real-API probe for native CLI flags, tools, usage and session resume."""

import argparse
import json
import os
import uuid
from pathlib import Path

from run_claude_cli_comparison import (
    ROOT, DEFAULT_SUITE, claude_executable, run_process, summarize_claude_turn, write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    suite = json.loads(DEFAULT_SUITE.read_text(encoding="utf-8"))
    key = os.environ["CLAUDE_API_KEY"]
    env = os.environ.copy()
    env.update(ANTHROPIC_BASE_URL=suite["base_url"], ANTHROPIC_AUTH_TOKEN=key,
               ANTHROPIC_MODEL=suite["model"], ANTHROPIC_DEFAULT_SONNET_MODEL=suite["model"],
               CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
    session_id = str(uuid.uuid4())
    nonce = "probe-" + uuid.uuid4().hex[:12]
    prompts = [
        f"Read {ROOT / 'examples/relu_operator.json'} using the Read tool. Do not modify files.\n\n"
        f"Remember this marker in our conversation: {nonce}. Reply with the task op_type and this marker.",
        "What marker did I ask you to remember in the previous message? Reply only with that marker. Do not use tools.",
    ]
    summaries = []
    for number, prompt in enumerate(prompts, 1):
        command = [claude_executable(), "-p", "--output-format", "stream-json", "--verbose",
                   "--permission-mode", "bypassPermissions", "--model", suite["model"],
                   "--session-id" if number == 1 else "--resume", session_id,
                   "--add-dir", str(ROOT)]
        turn_dir = output / f"turn_{number:02d}"
        process = run_process(command, output, env, turn_dir, 120, [key], input_text=prompt)
        summary = summarize_claude_turn(turn_dir, process)
        summaries.append(summary)
        if process["status"] != "process_success":
            break
    passed = len(summaries) == 2 and all(
        turn.get("session_id") == session_id and not turn["is_error"]
        and nonce in str(turn.get("payload_result"))
        and turn["usage"].get("llm_calls", 0) for turn in summaries
    )
    report = {"passed": bool(passed), "session_id": session_id, "turns": summaries,
              "scope": "transport probe only; excluded from business benchmark"}
    write_json(output / "probe_result.json", report)
    print(json.dumps({"passed": bool(passed), "calls": [s["usage"].get("llm_calls") for s in summaries],
                      "tokens": [s["usage"].get("total_tokens") for s in summaries]}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
