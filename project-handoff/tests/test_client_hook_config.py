from __future__ import annotations

import copy
import importlib.util
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "client_hook_config.py"


def load_module():
    scripts = str(SKILL_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("client_hook_config", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load client_hook_config module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def managed_count(document: dict) -> int:
    count = 0
    for groups in document.get("hooks", {}).values():
        for group in groups:
            for hook in group.get("hooks", []):
                if hook.get("name") == "project-handoff":
                    count += 1
                elif hook.get("statusMessage") == "project-handoff checkpoint":
                    count += 1
    return count


class CommandRenderingTests(unittest.TestCase):
    def test_posix_command_quotes_spaces_and_non_ascii(self) -> None:
        module = load_module()
        command = module.render_python_command(
            "/opt/Python 3/python3",
            Path("/tmp/技能 目录/client_event_adapter.py"),
            "gemini",
            "darwin",
        )

        self.assertEqual(
            command,
            "'/opt/Python 3/python3' '/tmp/技能 目录/client_event_adapter.py' "
            "--client gemini",
        )

    def test_windows_command_uses_double_quotes_not_posix_quotes(self) -> None:
        module = load_module()
        command = module.render_python_command(
            r"C:\Program Files\Python\python.exe",
            Path(r"C:\Users\Example User\skill\client_event_adapter.py"),
            "qwen",
            "win32",
        )

        self.assertEqual(
            command,
            '"C:\\Program Files\\Python\\python.exe" '
            '"C:\\Users\\Example User\\skill\\client_event_adapter.py" '
            "--client qwen",
        )
        self.assertNotIn("'", command)

    def test_windows_command_escapes_powershell_variable_characters(self) -> None:
        module = load_module()
        command = module.render_python_command(
            r"C:\Users\$cash\Python\python.exe",
            Path(r"C:\Users\$cash\skill\client_event_adapter.py"),
            "qwen",
            "win32",
        )

        self.assertEqual(
            command,
            '"C:\\Users\\`$cash\\Python\\python.exe" '
            '"C:\\Users\\`$cash\\skill\\client_event_adapter.py" '
            "--client qwen",
        )


class JsonMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self.spec = self.module.HookSpec(
            client="gemini",
            event="PreCompress",
            matcher="manual|auto",
            command="python adapter.py --client gemini",
            timeout=15000,
        )

    def test_install_preserves_unrelated_configuration_and_input(self) -> None:
        existing = {
            "theme": "dark",
            "hooks": {
                "PreCompress": [
                    {
                        "matcher": "manual",
                        "hooks": [
                            {
                                "type": "command",
                                "name": "unrelated",
                                "command": "keep-me",
                            }
                        ],
                    }
                ],
                "SessionStart": [{"hooks": [{"type": "command", "command": "start"}]}],
            },
        }
        before = copy.deepcopy(existing)

        merged = self.module.install_json_hook(existing, self.spec)

        self.assertEqual(existing, before)
        self.assertEqual(merged["theme"], "dark")
        self.assertEqual(merged["hooks"]["SessionStart"], existing["hooks"]["SessionStart"])
        self.assertEqual(
            merged["hooks"]["PreCompress"][0],
            existing["hooks"]["PreCompress"][0],
        )
        self.assertEqual(managed_count(merged), 1)

    def test_install_is_idempotent_and_replaces_one_managed_hook(self) -> None:
        first = self.module.install_json_hook({}, self.spec)
        updated_spec = self.module.HookSpec(
            client="gemini",
            event="PreCompress",
            matcher="manual|auto",
            command="python new-adapter.py --client gemini",
            timeout=20000,
        )

        second = self.module.install_json_hook(first, updated_spec)

        self.assertEqual(managed_count(second), 1)
        managed = second["hooks"]["PreCompress"][0]["hooks"][0]
        self.assertEqual(managed["command"], updated_spec.command)
        self.assertEqual(managed["timeout"], 20000)

    def test_duplicate_managed_hooks_are_rejected(self) -> None:
        installed = self.module.install_json_hook({}, self.spec)
        duplicate = copy.deepcopy(installed)
        duplicate["hooks"]["PreCompress"].append(
            copy.deepcopy(installed["hooks"]["PreCompress"][0])
        )

        with self.assertRaisesRegex(ValueError, "multiple"):
            self.module.install_json_hook(duplicate, self.spec)

    def test_uninstall_removes_only_managed_hook(self) -> None:
        existing = {
            "other": True,
            "hooks": {
                "PreCompress": [
                    {
                        "matcher": "manual",
                        "hooks": [
                            {
                                "type": "command",
                                "name": "unrelated",
                                "command": "keep",
                            }
                        ],
                    }
                ]
            },
        }
        installed = self.module.install_json_hook(existing, self.spec)

        removed = self.module.uninstall_json_hook(installed, self.spec)

        self.assertEqual(removed, existing)

    def test_claude_uses_supported_status_message_identity(self) -> None:
        spec = self.module.HookSpec(
            client="claude",
            event="PreCompact",
            matcher="manual|auto",
            command="/usr/bin/python3",
            args=("/skill/client_event_adapter.py", "--client", "claude"),
            timeout=15,
        )

        installed = self.module.install_json_hook({}, spec)
        handler = installed["hooks"]["PreCompact"][0]["hooks"][0]

        self.assertNotIn("name", handler)
        self.assertEqual(handler["statusMessage"], "project-handoff checkpoint")
        self.assertEqual(handler["args"], list(spec.args))


class JsonFileTests(unittest.TestCase):
    def test_round_trip_is_atomic_and_preserves_permissions(self) -> None:
        module = load_module()
        spec = module.HookSpec(
            client="qwen",
            event="PreCompact",
            matcher="manual|auto",
            command="python adapter.py --client qwen",
            timeout=15000,
            shell="bash",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text('{"locale": "zh-CN"}\n', encoding="utf-8")
            path.chmod(0o640)

            module.install_json_file(path, spec)

            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["locale"], "zh-CN")
            self.assertEqual(managed_count(document), 1)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
            self.assertTrue(path.read_bytes().endswith(b"\n"))

    def test_malformed_json_is_rejected_without_changes(self) -> None:
        module = load_module()
        spec = module.HookSpec(
            client="gemini",
            event="PreCompress",
            matcher="manual|auto",
            command="python adapter.py --client gemini",
            timeout=15000,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            original = b"{broken\n"
            path.write_bytes(original)

            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                module.install_json_file(path, spec)

            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
