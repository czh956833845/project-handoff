#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from file_safety import atomic_write_text


MANAGED_NAME = "project-handoff"
MANAGED_STATUS_MESSAGE = "project-handoff checkpoint"


@dataclass(frozen=True)
class HookSpec:
    client: str
    event: str
    matcher: str
    command: str
    timeout: int
    args: tuple[str, ...] = ()
    shell: str | None = None


def _windows_quote(argument: str) -> str:
    if '"' in argument:
        raise ValueError('Windows command arguments cannot contain a double quote')
    escaped = argument.replace("`", "``").replace("$", "`$")
    if (
        not argument
        or any(character.isspace() for character in argument)
        or "$" in argument
        or "`" in argument
    ):
        return f'"{escaped}"'
    return escaped


def render_python_command(
    python_executable: str,
    adapter: Path,
    client: str,
    platform: str,
) -> str:
    arguments = (python_executable, str(adapter), "--client", client)
    if platform == "win32":
        return " ".join(_windows_quote(argument) for argument in arguments)
    return shlex.join(arguments)


def _is_managed_handler(handler: Mapping[str, Any]) -> bool:
    return (
        handler.get("name") == MANAGED_NAME
        or handler.get("statusMessage") == MANAGED_STATUS_MESSAGE
    )


def _managed_handler(spec: HookSpec) -> dict[str, Any]:
    handler: dict[str, Any] = {
        "type": "command",
        "command": spec.command,
        "timeout": spec.timeout,
    }
    if spec.client == "claude":
        handler["statusMessage"] = MANAGED_STATUS_MESSAGE
        if spec.args:
            handler["args"] = list(spec.args)
    else:
        handler["name"] = MANAGED_NAME
    if spec.shell is not None:
        handler["shell"] = spec.shell
    return handler


def _document_copy(document: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(document, Mapping):
        raise ValueError("settings JSON must be an object")
    result = copy.deepcopy(dict(document))
    hooks = result.get("hooks")
    if hooks is None:
        result["hooks"] = {}
    elif not isinstance(hooks, dict):
        raise ValueError("settings hooks must be an object")
    return result


def _event_groups(document: dict[str, Any], event: str) -> list[Any]:
    hooks = document["hooks"]
    groups = hooks.get(event)
    if groups is None:
        return []
    if not isinstance(groups, list):
        raise ValueError(f"hooks.{event} must be an array")
    return groups


def _remove_managed_from_groups(
    groups: list[Any],
) -> tuple[list[dict[str, Any]], int]:
    cleaned_groups: list[dict[str, Any]] = []
    count = 0
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("hook matcher groups must be objects")
        handlers = group.get("hooks")
        if not isinstance(handlers, list):
            raise ValueError("hook matcher group hooks must be an array")
        cleaned_handlers = []
        for handler in handlers:
            if not isinstance(handler, dict):
                raise ValueError("hook handlers must be objects")
            if _is_managed_handler(handler):
                count += 1
            else:
                cleaned_handlers.append(handler)
        if cleaned_handlers:
            cleaned_group = copy.deepcopy(group)
            cleaned_group["hooks"] = cleaned_handlers
            cleaned_groups.append(cleaned_group)
    return cleaned_groups, count


def install_json_hook(
    document: Mapping[str, Any], spec: HookSpec
) -> dict[str, Any]:
    result = _document_copy(document)
    groups = _event_groups(result, spec.event)
    cleaned_groups, count = _remove_managed_from_groups(groups)
    if count > 1:
        raise ValueError("multiple project-handoff hooks found; remove duplicates manually")
    managed_group: dict[str, Any] = {"hooks": [_managed_handler(spec)]}
    if spec.matcher:
        managed_group["matcher"] = spec.matcher
    cleaned_groups.append(managed_group)
    result["hooks"][spec.event] = cleaned_groups
    return result


def uninstall_json_hook(
    document: Mapping[str, Any], spec: HookSpec
) -> dict[str, Any]:
    result = _document_copy(document)
    groups = _event_groups(result, spec.event)
    cleaned_groups, _ = _remove_managed_from_groups(groups)
    if cleaned_groups:
        result["hooks"][spec.event] = cleaned_groups
    else:
        result["hooks"].pop(spec.event, None)
    if not result["hooks"]:
        result.pop("hooks")
    return result


def inspect_json_hook(document: Mapping[str, Any], spec: HookSpec) -> str:
    result = _document_copy(document)
    groups = _event_groups(result, spec.event)
    _, count = _remove_managed_from_groups(groups)
    if count == 0:
        return "not installed"
    if count > 1:
        return "ambiguous"
    expected = install_json_hook(uninstall_json_hook(result, spec), spec)
    return "installed" if result == expected else "outdated"


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON in {path}: {error.msg}") from error
    if not isinstance(document, dict):
        raise ValueError(f"invalid JSON in {path}: root must be an object")
    return document


def write_json_file(path: Path, document: Mapping[str, Any]) -> None:
    content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, content)


def install_json_file(path: Path, spec: HookSpec) -> Path:
    write_json_file(path, install_json_hook(load_json_file(path), spec))
    return path


def uninstall_json_file(path: Path, spec: HookSpec) -> Path:
    if not path.exists():
        return path
    write_json_file(path, uninstall_json_hook(load_json_file(path), spec))
    return path


def doctor_json_file(path: Path, spec: HookSpec) -> str:
    if not path.exists():
        return "not installed"
    return inspect_json_hook(load_json_file(path), spec)
