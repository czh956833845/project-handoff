#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


PENDING_RELATIVE_PATH = Path("docs/project/.handoff-precompact-pending.json")
EMERGENCY_RELATIVE_DIRECTORY = Path("docs/project/handoff-emergency")


def atomic_write_bytes(destination: Path, content: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = destination.stat().st_mode & 0o7777 if destination.exists() else None
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if existing_mode is not None:
            temporary_path.chmod(existing_mode)
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


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


def choose_snapshot_path(
    project_root: Path, timestamp: datetime, revision: str
) -> Path:
    directory = project_root / EMERGENCY_RELATIVE_DIRECTORY
    stamp = timestamp.strftime("%Y%m%dT%H%M%S.%fZ")
    stem = f"{stamp}-{revision[:12]}"
    candidate = directory / f"{stem}.md"
    suffix = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{suffix}.md"
        suffix += 1
    return candidate


def capture(event: Mapping[str, Any]) -> Path | None:
    project_root = Path(require_string(event, "cwd")).expanduser().resolve()
    if not project_root.is_dir():
        raise ValueError("cwd is not a directory")

    trigger = event.get("trigger", event.get("trigger_reason"))
    if trigger not in {"manual", "auto"}:
        raise ValueError("PreCompact trigger must be manual or auto")

    handoff = project_root / "docs/project/HANDOFF.md"
    if not handoff.is_file():
        return None

    session_id = optional_string(event, "session_id")
    handoff_bytes = handoff.read_bytes()
    revision = hashlib.sha256(handoff_bytes).hexdigest()
    timestamp = datetime.now(timezone.utc)
    snapshot = choose_snapshot_path(project_root, timestamp, revision)
    atomic_write_bytes(snapshot, handoff_bytes)

    marker = {
        "captured_at": timestamp.isoformat().replace("+00:00", "Z"),
        "event": "PreCompact",
        "handoff_revision": revision,
        "project_root": str(project_root),
        "session_id": session_id,
        "snapshot_path": snapshot.relative_to(project_root).as_posix(),
        "trigger": trigger,
    }
    marker_bytes = (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode("utf-8")
    marker_path = project_root / PENDING_RELATIVE_PATH
    atomic_write_bytes(marker_path, marker_bytes)
    return marker_path


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
