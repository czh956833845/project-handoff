#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence


BEGIN_MARKER = "<!-- project-handoff:begin -->"
END_MARKER = "<!-- project-handoff:end -->"
DEFAULT_RULE_FILE = Path(__file__).resolve().parents[1] / "assets" / "global-AGENTS-rule.md"


def render_block(rule: str) -> str:
    return f"{BEGIN_MARKER}\n{rule.strip()}\n{END_MARKER}\n"


def merge_rule(existing: str, rule: str) -> str:
    begin_count = existing.count(BEGIN_MARKER)
    end_count = existing.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("invalid project-handoff managed markers")

    block = render_block(rule).rstrip()
    if begin_count == 0:
        prefix = existing.rstrip()
        return f"{prefix}\n\n{block}\n" if prefix else f"{block}\n"

    start = existing.index(BEGIN_MARKER)
    end = existing.index(END_MARKER, start) + len(END_MARKER)
    before = existing[:start].rstrip()
    after = existing[end:].lstrip()
    parts = [part for part in (before, block, after.rstrip()) if part]
    return "\n\n".join(parts) + "\n"


def atomic_write(destination: Path, content: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = destination.stat().st_mode & 0o7777 if destination.exists() else None
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
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


def install_rule(agents_file: Path, rule_file: Path) -> Path:
    existing = agents_file.read_text(encoding="utf-8") if agents_file.exists() else ""
    rule = rule_file.read_text(encoding="utf-8")
    atomic_write(agents_file, merge_rule(existing, rule))
    return agents_file


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the managed project-handoff global rule.")
    parser.add_argument("--agents-file", type=Path, required=True)
    parser.add_argument("--rule-file", type=Path, default=DEFAULT_RULE_FILE)
    args = parser.parse_args(argv)
    try:
        destination = install_rule(args.agents_file, args.rule_file)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
