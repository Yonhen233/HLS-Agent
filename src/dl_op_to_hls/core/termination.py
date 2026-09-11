"""Terminal outcomes are independent of implementation paths.

Legacy path values are accepted on read only, for historical traces/checkpoints.
"""

from __future__ import annotations

from typing import Any


def terminal_outcome(state: Any) -> str | None:
    """Return the explicit terminal outcome, with read-only legacy migration."""
    get = state.get if isinstance(state, dict) else lambda key, default=None: getattr(state, key, default)
    return get("terminal_outcome") or ("blocked" if get("selected_path") == "unsupported_path" else None)


def is_blocked(state: Any) -> bool:
    """Return whether the runtime ended at a capability gate."""
    return terminal_outcome(state) == "blocked"
