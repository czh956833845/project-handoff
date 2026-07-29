#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from file_safety import atomic_write_bytes
from precompact_checkpoint import (
    EMERGENCY_RELATIVE_DIRECTORY,
    PENDING_RELATIVE_PATH,
    NormalizedEvent,
    capture_checkpoint,
    choose_snapshot_path,
)


def parse_event(raw: str) -> dict[str, Any]:
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid event JSON: {error.msg}") from error
    if not isinstance(event, dict) or event.get("hook_event_name") != "PreCompact":
        raise ValueError("expected a PreCompact event")
    return event


def require_string(event: Mapping[str, Any], key: str) -> str:
    value = event.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def optional_string(event: Mapping[str, Any], key: str) -> str | None:
    value = event.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string when present")
    return value


def capture(event: Mapping[str, Any]) -> Path | None:
    project_root = Path(require_string(event, "cwd")).expanduser().resolve()
    if not project_root.is_dir():
        raise ValueError("cwd is not a directory")

    trigger = event.get("trigger", event.get("trigger_reason"))
    if trigger not in {"manual", "auto"}:
        raise ValueError("PreCompact trigger must be manual or auto")

    session_id = optional_string(event, "session_id")
    timestamp = optional_string(event, "timestamp")
    return capture_checkpoint(
        NormalizedEvent(
            client="kimi",
            event_name="PreCompact",
            trigger=trigger,
            project_root=project_root,
            session_id=session_id,
            timestamp=timestamp,
        )
    )


def main() -> int:
    try:
        event = parse_event(sys.stdin.read())
        capture(event)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
