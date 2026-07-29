#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from client_hook_config import (
    HookSpec,
    doctor_json_file,
    install_json_file,
    render_python_command,
    uninstall_json_file,
)
from file_safety import atomic_write_bytes, atomic_write_text


DEFAULT_SKILL_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_CLIENTS = ("claude", "gemini", "copilot", "cline", "qwen")
SUPPORTED_SCOPES = ("user", "project", "cloud", "editor")
COPILOT_MANAGED_ENV = {"PROJECT_HANDOFF_MANAGED": "1"}
VENDORED_FILES = (
    "client_event_adapter.py",
    "precompact_checkpoint.py",
    "file_safety.py",
)
RUNTIME_MANIFEST = ".project-handoff-runtime.json"
CLINE_MANAGED_MARKER = "# project-handoff:managed"
CLINE_HOOK_NAMES = (
    "TaskStart",
    "TaskResume",
    "TaskComplete",
    "SessionShutdown",
    "PreCompact",
)

JSON_PATHS = {
    "claude": {
        "user": Path(".claude/settings.json"),
        "project": Path(".claude/settings.json"),
    },
    "gemini": {
        "user": Path(".gemini/settings.json"),
        "project": Path(".gemini/settings.json"),
    },
    "qwen": {
        "user": Path(".qwen/settings.json"),
        "project": Path(".qwen/settings.json"),
    },
}

COPILOT_PATHS = {
    "user": Path(".copilot/hooks/project-handoff.json"),
    "project": Path(".github/hooks/project-handoff.json"),
    "cloud": Path(".github/hooks/project-handoff.json"),
}


def _json_spec(
    client: str,
    skill_root: Path,
    python_executable: str,
    platform: str,
) -> HookSpec:
    adapter = skill_root.resolve() / "scripts" / "client_event_adapter.py"
    if not adapter.is_file():
        raise ValueError(f"client event adapter not found: {adapter}")
    if client == "claude":
        return HookSpec(
            client=client,
            event="PreCompact",
            matcher="manual|auto",
            command=python_executable,
            args=(str(adapter), "--client", client),
            timeout=15,
        )
    if client == "gemini":
        return HookSpec(
            client=client,
            event="PreCompress",
            matcher="",
            command=render_python_command(
                python_executable, adapter, client, platform
            ),
            timeout=15000,
        )
    if client == "qwen":
        return HookSpec(
            client=client,
            event="PreCompact",
            matcher="manual|auto",
            command=render_python_command(
                python_executable, adapter, client, platform
            ),
            timeout=15000,
            shell="powershell" if platform == "win32" else "bash",
        )
    raise ValueError(f"unsupported JSON client: {client}")


def _resolve_target(
    client: str,
    scope: str,
    *,
    home: Path,
    project_root: Path,
    config_file: Path | None,
) -> Path:
    if client in JSON_PATHS:
        paths = JSON_PATHS[client]
        if scope not in paths:
            raise ValueError(f"{client} does not support {scope} scope")
        if config_file is not None:
            return config_file.expanduser()
        base = home if scope == "user" else project_root
        return base / paths[scope]
    if config_file is not None:
        raise ValueError("--config-file is supported only for settings.json clients")
    if client == "copilot":
        if scope not in COPILOT_PATHS:
            raise ValueError(f"copilot does not support {scope} scope")
        base = home if scope == "user" else project_root
        return base / COPILOT_PATHS[scope]
    if client == "cline":
        raise ValueError("Cline targets are resolved as hook directories")
    raise ValueError(f"unsupported client: {client}")


def _copilot_document(
    skill_root: Path,
    python_executable: str,
    platform: str,
) -> dict[str, Any]:
    adapter = skill_root.resolve() / "scripts" / "client_event_adapter.py"
    if not adapter.is_file():
        raise ValueError(f"client event adapter not found: {adapter}")
    command = render_python_command(
        python_executable, adapter, "copilot", platform
    )
    command_field = "powershell" if platform == "win32" else "bash"
    return {
        "version": 1,
        "hooks": {
            "preCompact": [
                {
                    "type": "command",
                    command_field: command,
                    "env": COPILOT_MANAGED_ENV,
                    "timeoutSec": 15,
                }
            ]
        },
    }


def _copilot_cloud_document() -> dict[str, Any]:
    return {
        "version": 1,
        "hooks": {
            "preCompact": [
                {
                    "type": "command",
                    "bash": (
                        "python3 .github/hooks/project-handoff/"
                        "client_event_adapter.py --client copilot"
                    ),
                    "cwd": ".",
                    "env": COPILOT_MANAGED_ENV,
                    "timeoutSec": 15,
                }
            ]
        },
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON in {path}: {error.msg}") from error
    if not isinstance(document, dict):
        raise ValueError(f"invalid JSON in {path}: root must be an object")
    return document


def _is_managed_copilot_document(document: Mapping[str, Any]) -> bool:
    hooks = document.get("hooks")
    if not isinstance(hooks, dict) or set(hooks) != {"preCompact"}:
        return False
    entries = hooks["preCompact"]
    return (
        isinstance(entries, list)
        and len(entries) == 1
        and isinstance(entries[0], dict)
        and entries[0].get("env") == COPILOT_MANAGED_ENV
    )


def _write_copilot(path: Path, document: Mapping[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
    )


def _install_copilot(path: Path, expected: Mapping[str, Any]) -> None:
    if path.exists() and not _is_managed_copilot_document(_load_json(path)):
        raise ValueError(f"{path} exists and is not managed by project-handoff")
    _write_copilot(path, expected)


def _uninstall_copilot(path: Path) -> None:
    if not path.exists():
        return
    if not _is_managed_copilot_document(_load_json(path)):
        raise ValueError(f"{path} exists and is not managed by project-handoff")
    path.unlink()


def _doctor_copilot(path: Path, expected: Mapping[str, Any]) -> str:
    if not path.exists():
        return "not installed"
    document = _load_json(path)
    if not _is_managed_copilot_document(document):
        return "unmanaged"
    return "installed" if document == expected else "outdated"


def _cloud_runtime_directory(project_root: Path) -> Path:
    return project_root / ".github/hooks/project-handoff"


def _expected_runtime(skill_root: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
    scripts = skill_root.resolve() / "scripts"
    files: dict[str, bytes] = {}
    hashes: dict[str, str] = {}
    for name in VENDORED_FILES:
        source = scripts / name
        if not source.is_file():
            raise ValueError(f"cloud runtime source not found: {source}")
        content = source.read_bytes()
        files[name] = content
        hashes[name] = hashlib.sha256(content).hexdigest()
    manifest = {
        "schema_version": 1,
        "files": hashes,
    }
    return files, manifest


def _load_runtime_manifest(runtime: Path) -> dict[str, Any] | None:
    path = runtime / RUNTIME_MANIFEST
    if not path.exists():
        return None
    return _load_json(path)


def _is_owned_runtime_manifest(manifest: Mapping[str, Any]) -> bool:
    files = manifest.get("files")
    return (
        manifest.get("schema_version") == 1
        and isinstance(files, dict)
        and set(files) == set(VENDORED_FILES)
        and all(isinstance(value, str) for value in files.values())
    )


def _install_cloud_runtime(project_root: Path, skill_root: Path) -> None:
    runtime = _cloud_runtime_directory(project_root)
    if runtime.exists():
        manifest = _load_runtime_manifest(runtime)
        if manifest is None and any(runtime.iterdir()):
            raise ValueError(f"{runtime} exists and is not managed by project-handoff")
        if manifest is not None and not _is_owned_runtime_manifest(manifest):
            raise ValueError(f"{runtime} has an invalid project-handoff manifest")
    files, manifest = _expected_runtime(skill_root)
    for name, content in files.items():
        atomic_write_bytes(runtime / name, content)
    atomic_write_text(
        runtime / RUNTIME_MANIFEST,
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )


def _doctor_cloud_runtime(project_root: Path, skill_root: Path) -> str:
    runtime = _cloud_runtime_directory(project_root)
    manifest = _load_runtime_manifest(runtime)
    if manifest is None:
        return "not installed"
    if not _is_owned_runtime_manifest(manifest):
        return "unmanaged"
    expected_files, expected_manifest = _expected_runtime(skill_root)
    if manifest != expected_manifest:
        return "outdated"
    for name, expected in expected_files.items():
        path = runtime / name
        if not path.is_file() or path.read_bytes() != expected:
            return "outdated"
    return "installed"


def _validate_cloud_runtime_for_removal(project_root: Path) -> Path | None:
    runtime = _cloud_runtime_directory(project_root)
    if not runtime.exists():
        return None
    manifest = _load_runtime_manifest(runtime)
    if manifest is None or not _is_owned_runtime_manifest(manifest):
        raise ValueError(f"{runtime} is not managed by project-handoff")
    return runtime


def _remove_cloud_runtime(runtime: Path | None) -> None:
    if runtime is None:
        return
    for name in VENDORED_FILES:
        (runtime / name).unlink(missing_ok=True)
    (runtime / RUNTIME_MANIFEST).unlink(missing_ok=True)
    try:
        runtime.rmdir()
    except OSError:
        pass


def _cline_directories(
    scope: str,
    *,
    home: Path,
    project_root: Path,
    hooks_dir: Path | None,
) -> tuple[tuple[Path, bool], ...]:
    if hooks_dir is not None:
        return ((hooks_dir.expanduser(), True),)
    if scope == "user":
        return ((home / ".cline/hooks", True),)
    if scope == "editor":
        return ((home / "Documents/Cline/Hooks", False),)
    if scope == "project":
        return (
            (project_root / ".cline/hooks", True),
            (project_root / ".clinerules/hooks", False),
        )
    raise ValueError(f"cline does not support {scope} scope")


def _cline_hook_path(directory: Path, cli_style: bool, hook_name: str) -> Path:
    return directory / (f"{hook_name}.py" if cli_style else hook_name)


def _cline_wrapper(skill_root: Path) -> str:
    adapter = skill_root.resolve() / "scripts" / "client_event_adapter.py"
    if not adapter.is_file():
        raise ValueError(f"client event adapter not found: {adapter}")
    adapter_literal = repr(str(adapter))
    return (
        "#!/usr/bin/env python3\n"
        f"{CLINE_MANAGED_MARKER}\n"
        "import runpy\n"
        "import sys\n"
        f"adapter = {adapter_literal}\n"
        'sys.argv = [adapter, "--client", "cline"]\n'
        'runpy.run_path(adapter, run_name="__main__")\n'
    )


def _cline_paths(
    scope: str,
    *,
    home: Path,
    project_root: Path,
    hooks_dir: Path | None,
) -> tuple[Path, ...]:
    paths = []
    for directory, cli_style in _cline_directories(
        scope,
        home=home,
        project_root=project_root,
        hooks_dir=hooks_dir,
    ):
        paths.extend(
            _cline_hook_path(directory, cli_style, hook_name)
            for hook_name in CLINE_HOOK_NAMES
        )
    return tuple(paths)


def _is_managed_cline_hook(path: Path) -> bool:
    try:
        return CLINE_MANAGED_MARKER in path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def _execute_cline(
    action: str,
    scope: str,
    *,
    home: Path,
    project_root: Path,
    skill_root: Path,
    platform: str,
    hooks_dir: Path | None,
    force: bool,
) -> tuple[int, str]:
    if platform == "win32":
        raise ValueError(
            "Cline upstream currently does not support Windows file hooks"
        )
    paths = _cline_paths(
        scope,
        home=home,
        project_root=project_root,
        hooks_dir=hooks_dir,
    )
    expected = _cline_wrapper(skill_root)
    existing_unmanaged = [
        path for path in paths if path.exists() and not _is_managed_cline_hook(path)
    ]
    if existing_unmanaged and (action != "install" or not force):
        raise ValueError(
            f"{existing_unmanaged[0]} exists and is not managed by project-handoff"
        )
    if action == "install":
        for path in paths:
            atomic_write_text(path, expected)
            path.chmod(path.stat().st_mode | 0o111)
        return 0, f"installed: {len(paths)} Cline hooks\n"
    if action == "uninstall":
        for path in paths:
            path.unlink(missing_ok=True)
        return 0, f"uninstalled: {len(paths)} Cline hooks\n"
    installed = [
        path
        for path in paths
        if path.is_file()
        and path.read_text(encoding="utf-8") == expected
        and path.stat().st_mode & 0o111
    ]
    status = (
        "installed"
        if len(installed) == len(paths)
        else "not installed"
        if not any(path.exists() for path in paths)
        else "outdated"
    )
    return (0 if status == "installed" else 1), f"{status}: Cline hooks\n"


def execute(
    action: str,
    client: str,
    scope: str,
    *,
    home: Path,
    project_root: Path,
    skill_root: Path,
    python_executable: str,
    platform: str,
    config_file: Path | None = None,
    hooks_dir: Path | None = None,
    force: bool = False,
) -> tuple[int, str]:
    if client == "cline":
        return _execute_cline(
            action,
            scope,
            home=home,
            project_root=project_root,
            skill_root=skill_root,
            platform=platform,
            hooks_dir=hooks_dir,
            force=force,
        )
    target = _resolve_target(
        client,
        scope,
        home=home,
        project_root=project_root,
        config_file=config_file,
    )
    if client in JSON_PATHS:
        spec = _json_spec(client, skill_root, python_executable, platform)
        if action == "install":
            install_json_file(target, spec)
            return 0, f"installed: {target}\n"
        if action == "uninstall":
            uninstall_json_file(target, spec)
            return 0, f"uninstalled: {target}\n"
        status = doctor_json_file(target, spec)
        return (0 if status == "installed" else 1), f"{status}: {target}\n"

    if scope == "cloud":
        expected = _copilot_cloud_document()
        if action == "install":
            if target.exists() and not _is_managed_copilot_document(_load_json(target)):
                raise ValueError(f"{target} exists and is not managed by project-handoff")
            _install_cloud_runtime(project_root, skill_root)
            _write_copilot(target, expected)
            return 0, f"installed: {target}\n"
        if action == "uninstall":
            runtime = _validate_cloud_runtime_for_removal(project_root)
            _uninstall_copilot(target)
            _remove_cloud_runtime(runtime)
            return 0, f"uninstalled: {target}\n"
        config_status = _doctor_copilot(target, expected)
        runtime_status = _doctor_cloud_runtime(project_root, skill_root)
        status = (
            "installed"
            if config_status == "installed" and runtime_status == "installed"
            else "not installed"
            if config_status == "not installed" and runtime_status == "not installed"
            else "outdated"
        )
        return (0 if status == "installed" else 1), f"{status}: {target}\n"

    expected = _copilot_document(skill_root, python_executable, platform)
    if action == "install":
        _install_copilot(target, expected)
        return 0, f"installed: {target}\n"
    if action == "uninstall":
        _uninstall_copilot(target)
        return 0, f"uninstalled: {target}\n"
    status = _doctor_copilot(target, expected)
    return (0 if status == "installed" else 1), f"{status}: {target}\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install, inspect, or remove project-handoff client hooks."
    )
    parser.add_argument("action", choices=("install", "uninstall", "doctor"))
    parser.add_argument("--client", choices=SUPPORTED_CLIENTS, required=True)
    parser.add_argument("--scope", choices=SUPPORTED_SCOPES, required=True)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--skill-root", type=Path, default=DEFAULT_SKILL_ROOT)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--platform", default=sys.platform)
    parser.add_argument("--config-file", type=Path)
    parser.add_argument("--hooks-dir", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        code, message = execute(
            args.action,
            args.client,
            args.scope,
            home=args.home.expanduser(),
            project_root=args.project_root.expanduser(),
            skill_root=args.skill_root.expanduser(),
            python_executable=args.python_executable,
            platform=args.platform,
            config_file=args.config_file,
            hooks_dir=args.hooks_dir,
            force=args.force,
        )
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    sys.stdout.write(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
