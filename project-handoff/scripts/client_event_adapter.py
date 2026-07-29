#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from precompact_checkpoint import NormalizedEvent, capture_checkpoint


SUPPORTED_CLIENTS = ("claude", "gemini", "copilot", "cline", "qwen")
CLINE_EVENT_NAMES = {
    "PreCompact": "PreCompact",
    "pre_compact": "PreCompact",
    "TaskStart": "TaskStart",
    "agent_start": "TaskStart",
    "TaskResume": "TaskResume",
    "agent_resume": "TaskResume",
    "TaskComplete": "TaskComplete",
    "agent_end": "TaskComplete",
    "SessionShutdown": "SessionShutdown",
    "session_shutdown": "SessionShutdown",
}


def _require_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string when present")
    return value


def _timestamp(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("timestamp")
    if value is None:
        return None
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError("timestamp must be a string or number when present")
    return str(value)


def _common_snake_case(
    client: str, payload: Mapping[str, Any], expected_event: str
) -> NormalizedEvent:
    actual_event = _require_string(payload, "hook_event_name")
    if actual_event != expected_event:
        raise ValueError(f"expected a {expected_event} event")
    trigger = _require_string(payload, "trigger")
    if trigger not in {"manual", "auto"}:
        raise ValueError("pre-compaction trigger must be manual or auto")
    return NormalizedEvent(
        client=client,
        event_name=actual_event,
        trigger=trigger,
        project_root=Path(_require_string(payload, "cwd")).expanduser().resolve(),
        session_id=_optional_string(payload, "session_id"),
        timestamp=_timestamp(payload),
    )


def _normalize_copilot(payload: Mapping[str, Any]) -> NormalizedEvent:
    if "hook_event_name" in payload:
        return _common_snake_case("copilot", payload, "PreCompact")
    trigger = _require_string(payload, "trigger")
    if trigger not in {"manual", "auto"}:
        raise ValueError("pre-compaction trigger must be manual or auto")
    return NormalizedEvent(
        client="copilot",
        event_name="preCompact",
        trigger=trigger,
        project_root=Path(_require_string(payload, "cwd")).expanduser().resolve(),
        session_id=_optional_string(payload, "sessionId"),
        timestamp=_timestamp(payload),
    )


def _normalize_cline(payload: Mapping[str, Any]) -> NormalizedEvent:
    hook_name = _require_string(payload, "hookName")
    event_name = CLINE_EVENT_NAMES.get(hook_name)
    if event_name is None:
        raise ValueError("expected a supported Cline lifecycle event")
    roots = payload.get("workspaceRoots")
    if (
        not isinstance(roots, list)
        or not roots
        or not isinstance(roots[0], str)
        or not roots[0]
    ):
        raise ValueError("workspaceRoots must contain a project path")
    return NormalizedEvent(
        client="cline",
        event_name=event_name,
        trigger="auto",
        project_root=Path(roots[0]).expanduser().resolve(),
        session_id=_optional_string(payload, "taskId"),
        timestamp=_timestamp(payload),
    )


def normalize_event(
    client: str, payload: Mapping[str, Any]
) -> NormalizedEvent:
    if client == "claude":
        return _common_snake_case(client, payload, "PreCompact")
    if client == "gemini":
        return _common_snake_case(client, payload, "PreCompress")
    if client == "copilot":
        return _normalize_copilot(payload)
    if client == "cline":
        return _normalize_cline(payload)
    if client == "qwen":
        return _common_snake_case(client, payload, "PreCompact")
    raise ValueError(f"unsupported client: {client}")


def success_payload(client: str) -> str:
    if client == "claude":
        return ""
    if client in {"gemini", "copilot", "qwen"}:
        return "{}\n"
    if client == "cline":
        reminder = (
            "Invoke project-handoff and read docs/project/HANDOFF.md before "
            "continuing project work."
        )
        return (
            json.dumps(
                {
                    "cancel": False,
                    "context": reminder,
                    "contextModification": reminder,
                },
                sort_keys=True,
            )
            + "\n"
        )
    raise ValueError(f"unsupported client: {client}")


def run(client: str, raw_stdin: str) -> tuple[int, str, str]:
    stdout = success_payload(client)
    try:
        payload = json.loads(raw_stdin)
        if not isinstance(payload, dict):
            raise ValueError("event JSON must be an object")
        capture_checkpoint(normalize_event(client, payload))
    except (json.JSONDecodeError, OSError, ValueError) as error:
        return 0, stdout, f"error: {error}\n"
    return 0, stdout, ""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture a project-handoff checkpoint for a client event."
    )
    parser.add_argument("--client", choices=SUPPORTED_CLIENTS, required=True)
    args = parser.parse_args(argv)
    code, stdout, stderr = run(args.client, sys.stdin.read())
    if stdout:
        sys.stdout.write(stdout)
    if stderr:
        sys.stderr.write(stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
