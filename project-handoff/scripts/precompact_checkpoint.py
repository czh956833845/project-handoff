#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from file_safety import atomic_write_bytes, file_lock


PENDING_RELATIVE_PATH = Path("docs/project/.handoff-precompact-pending.json")
EMERGENCY_RELATIVE_DIRECTORY = Path("docs/project/handoff-emergency")


@dataclass(frozen=True)
class NormalizedEvent:
    client: str
    event_name: str
    trigger: str
    project_root: Path
    session_id: str | None = None
    timestamp: str | None = None


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


def _validate_event(event: NormalizedEvent) -> Path:
    if not event.client:
        raise ValueError("client must be a non-empty string")
    if not event.event_name:
        raise ValueError("event_name must be a non-empty string")
    if event.trigger not in {"manual", "auto"}:
        raise ValueError("pre-compaction trigger must be manual or auto")
    if event.session_id is not None and not isinstance(event.session_id, str):
        raise ValueError("session_id must be a string when present")
    if event.timestamp is not None and not isinstance(event.timestamp, str):
        raise ValueError("timestamp must be a string when present")
    project_root = event.project_root.expanduser().resolve()
    if not project_root.is_dir():
        raise ValueError("project root is not a directory")
    return project_root


def capture_checkpoint(event: NormalizedEvent) -> Path | None:
    project_root = _validate_event(event)
    handoff = project_root / "docs/project/HANDOFF.md"
    if not handoff.is_file():
        return None

    lock_path = project_root / "docs/project/.HANDOFF.lock"
    with file_lock(lock_path):
        if not handoff.is_file():
            return None
        handoff_bytes = handoff.read_bytes()
        revision = hashlib.sha256(handoff_bytes).hexdigest()
        captured_at = datetime.now(timezone.utc)
        snapshot = choose_snapshot_path(project_root, captured_at, revision)
        atomic_write_bytes(snapshot, handoff_bytes)

        marker = {
            "captured_at": captured_at.isoformat().replace("+00:00", "Z"),
            "client": event.client,
            "event": event.event_name,
            "event_timestamp": event.timestamp,
            "handoff_revision": revision,
            "project_root": str(project_root),
            "session_id": event.session_id,
            "snapshot_path": snapshot.relative_to(project_root).as_posix(),
            "trigger": event.trigger,
        }
        marker_bytes = (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        marker_path = project_root / PENDING_RELATIVE_PATH
        try:
            atomic_write_bytes(marker_path, marker_bytes)
        except Exception:
            snapshot.unlink(missing_ok=True)
            raise
    return marker_path
