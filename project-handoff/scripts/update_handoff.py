#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from file_safety import atomic_write_text, file_lock


REQUIRED_SECTIONS = (
    "Project goal",
    "Scope and boundaries",
    "Key decisions",
    "Completed work",
    "Verification evidence",
    "Current files",
    "Open items",
    "Next step",
)
ABSENT_REVISION = "absent"
REVISION_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SNAPSHOT_PATTERN = re.compile(
    r"^\d{8}T\d{6}\.\d{6}Z-[0-9a-f]{12}(?:-\d+)?\.md$"
)
HISTORY_LIMIT = 50


class HandoffConflictError(ValueError):
    pass


atomic_write = atomic_write_text
handoff_lock = file_lock


def revision_for_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def current_revision(destination: Path) -> str:
    if not destination.exists():
        return ABSENT_REVISION
    return revision_for_bytes(destination.read_bytes())


def validate_expected_revision(revision: str) -> None:
    if revision != ABSENT_REVISION and REVISION_PATTERN.fullmatch(revision) is None:
        raise ValueError("expected revision must be 'absent' or 64 lowercase hexadecimal characters")


def validate_content(content: str) -> None:
    headings = re.findall(r"^## ([^\r\n]+)\s*$", content, flags=re.MULTILINE)
    problems = []
    for section in REQUIRED_SECTIONS:
        count = headings.count(section)
        if count == 0:
            problems.append(f"missing required section: {section}")
        elif count > 1:
            problems.append(f"duplicate required section: {section}")
    if problems:
        raise ValueError("; ".join(problems))


def create_snapshot(history_dir: Path, old_bytes: bytes, revision: str) -> Path:
    history_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    stem = f"{timestamp}-{revision[:12]}"
    snapshot = history_dir / f"{stem}.md"
    suffix = 1
    while snapshot.exists():
        snapshot = history_dir / f"{stem}-{suffix}.md"
        suffix += 1
    atomic_write(snapshot, old_bytes.decode("utf-8"))
    return snapshot


def prune_history(history_dir: Path, keep: int = HISTORY_LIMIT) -> list[str]:
    if not history_dir.exists():
        return []
    snapshots = sorted(
        path
        for path in history_dir.iterdir()
        if path.is_file() and SNAPSHOT_PATTERN.fullmatch(path.name)
    )
    removed = []
    for snapshot in snapshots[:-keep] if keep > 0 else snapshots:
        snapshot.unlink()
        removed.append(snapshot.name)
    return removed


def update_handoff(
    project_root: Path,
    content_file: Path,
    expected_revision: str,
    *,
    lock_timeout_seconds: float = 10.0,
) -> Path:
    destination = project_root / "docs" / "project" / "HANDOFF.md"
    content = content_file.read_text(encoding="utf-8")
    validate_content(content)
    validate_expected_revision(expected_revision)
    lock_path = destination.parent / ".HANDOFF.lock"
    with handoff_lock(lock_path, timeout_seconds=lock_timeout_seconds):
        old_bytes = destination.read_bytes() if destination.exists() else None
        actual_revision = (
            revision_for_bytes(old_bytes) if old_bytes is not None else ABSENT_REVISION
        )
        if actual_revision != expected_revision:
            raise HandoffConflictError(
                "handoff conflict: current revision changed; reread HANDOFF.md and merge before retrying"
            )
        snapshot = None
        if old_bytes is not None:
            snapshot = create_snapshot(
                destination.parent / "handoff-history",
                old_bytes,
                actual_revision,
            )
        try:
            atomic_write(destination, content)
        except Exception:
            if snapshot is not None:
                snapshot.unlink(missing_ok=True)
            raise
        try:
            prune_history(destination.parent / "handoff-history")
        except OSError as error:
            print(f"warning: handoff updated but history pruning failed: {error}", file=sys.stderr)
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely inspect or update a project handoff.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    revision_parser = subparsers.add_parser("revision", help="Print the current handoff revision.")
    revision_parser.add_argument("--project-root", type=Path, required=True)

    update_parser = subparsers.add_parser("update", help="Replace the handoff if its revision matches.")
    update_parser.add_argument("--project-root", type=Path, required=True)
    update_parser.add_argument("--content-file", type=Path, required=True)
    update_parser.add_argument("--expected-revision", required=True)
    args = parser.parse_args(argv)
    destination = args.project_root / "docs" / "project" / "HANDOFF.md"
    if args.command == "revision":
        print(current_revision(destination))
        return 0
    try:
        destination = update_handoff(
            args.project_root,
            args.content_file,
            args.expected_revision,
        )
    except (OSError, TimeoutError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
