#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Sequence


BEGIN_MARKER = "# project-handoff:begin"
END_MARKER = "# project-handoff:end"
DEFAULT_SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_FILE = Path.home() / ".kimi-code" / "config.toml"


def toml_basic_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_block(skill_root: Path) -> str:
    hook = skill_root.resolve() / "scripts" / "kimi_precompact_hook.py"
    command = f"python3 {shlex.quote(str(hook))}"
    return (
        f"{BEGIN_MARKER}\n"
        "[[hooks]]\n"
        'event = "PreCompact"\n'
        'matcher = "manual|auto"\n'
        f"command = {toml_basic_string(command)}\n"
        "timeout = 15\n"
        f"{END_MARKER}\n"
    )


def merge_config(existing: str, block: str) -> str:
    begin_count = existing.count(BEGIN_MARKER)
    end_count = existing.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("invalid project-handoff managed markers")

    if begin_count == 0:
        if not existing:
            return block
        separator = "" if existing.endswith("\n\n") else "\n" if existing.endswith("\n") else "\n\n"
        return f"{existing}{separator}{block}"

    start = existing.index(BEGIN_MARKER)
    end = existing.index(END_MARKER, start) + len(END_MARKER)
    if end < len(existing) and existing[end] == "\n":
        end += 1
    return f"{existing[:start]}{block}{existing[end:]}"


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


def install_hook(config_file: Path, skill_root: Path) -> Path:
    existing = config_file.read_text(encoding="utf-8") if config_file.exists() else ""
    atomic_write(config_file, merge_config(existing, render_block(skill_root)))
    return config_file


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the managed Kimi PreCompact hook.")
    parser.add_argument("--config-file", type=Path, default=DEFAULT_CONFIG_FILE)
    parser.add_argument("--skill-root", type=Path, default=DEFAULT_SKILL_ROOT)
    args = parser.parse_args(argv)
    try:
        destination = install_hook(args.config_file.expanduser(), args.skill_root.expanduser())
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
