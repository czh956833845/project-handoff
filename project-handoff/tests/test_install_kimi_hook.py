from __future__ import annotations

import importlib.util
import json
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "install_kimi_hook.py"
BEGIN_MARKER = "# project-handoff:begin"
END_MARKER = "# project-handoff:end"


def read_toml_string(content: str, key: str) -> str:
    prefix = f"{key} = "
    line = next(line for line in content.splitlines() if line.startswith(prefix))
    return json.loads(line.removeprefix(prefix))


class InstallKimiHookCliTests(unittest.TestCase):
    def run_installer(
        self, config_file: Path, skill_root: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--config-file",
                str(config_file),
                "--skill-root",
                str(skill_root),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_creates_missing_config_with_precompact_hook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / ".kimi-code" / "config.toml"
            skill_root = root / "project-handoff"

            result = self.run_installer(config_file, skill_root)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), str(config_file))
            content = config_file.read_text(encoding="utf-8")
            self.assertEqual(content.count(BEGIN_MARKER), 1)
            self.assertEqual(content.count(END_MARKER), 1)
            self.assertEqual(content.count("[[hooks]]"), 1)
            self.assertEqual(read_toml_string(content, "event"), "PreCompact")
            self.assertEqual(read_toml_string(content, "matcher"), "manual|auto")
            self.assertIn("timeout = 15", content)
            expected_script = skill_root.resolve() / "scripts" / "kimi_precompact_hook.py"
            self.assertEqual(
                read_toml_string(content, "command"),
                f"python3 {shlex.quote(str(expected_script))}",
            )

    def test_preserves_unrelated_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "config.toml"
            existing = 'default_model = "kimi-for-coding"\n'
            config_file.write_text(existing, encoding="utf-8")

            result = self.run_installer(config_file, root / "skill")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(config_file.read_text(encoding="utf-8").startswith(existing))

    def test_replaces_managed_block_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "config.toml"
            config_file.write_text(
                f'before = true\n\n{BEGIN_MARKER}\nold = true\n{END_MARKER}\n\nafter = true\n',
                encoding="utf-8",
            )

            first = self.run_installer(config_file, root / "skill")
            first_content = config_file.read_text(encoding="utf-8")
            second = self.run_installer(config_file, root / "skill")
            second_content = config_file.read_text(encoding="utf-8")

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(first_content, second_content)
            self.assertEqual(second_content.count(BEGIN_MARKER), 1)
            self.assertEqual(second_content.count('event = "PreCompact"'), 1)
            self.assertNotIn("old = true", second_content)
            self.assertIn("before = true", second_content)
            self.assertIn("after = true", second_content)

    def test_rejects_malformed_markers_and_preserves_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "config.toml"
            old_content = f"keep = true\n{BEGIN_MARKER}\nunclosed = true\n"
            config_file.write_text(old_content, encoding="utf-8")

            result = self.run_installer(config_file, root / "skill")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("managed markers", result.stderr)
            self.assertEqual(config_file.read_text(encoding="utf-8"), old_content)

    def test_rejects_duplicate_marker_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "config.toml"
            old_content = (
                f"{BEGIN_MARKER}\na = 1\n{END_MARKER}\n"
                f"{BEGIN_MARKER}\nb = 2\n{END_MARKER}\n"
            )
            config_file.write_text(old_content, encoding="utf-8")

            result = self.run_installer(config_file, root / "skill")

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(config_file.read_text(encoding="utf-8"), old_content)

    def test_escapes_unusual_skill_path_as_valid_toml(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "config.toml"
            skill_root = root / 'skill "quoted"\\path'

            result = self.run_installer(config_file, skill_root)

            self.assertEqual(result.returncode, 0, result.stderr)
            content = config_file.read_text(encoding="utf-8")
            expected_script = skill_root.resolve() / "scripts" / "kimi_precompact_hook.py"
            self.assertEqual(
                read_toml_string(content, "command"),
                f"python3 {shlex.quote(str(expected_script))}",
            )

    def test_preserves_existing_file_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "config.toml"
            config_file.write_text("enabled = true\n", encoding="utf-8")
            config_file.chmod(0o640)

            result = self.run_installer(config_file, root / "skill")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(stat.S_IMODE(config_file.stat().st_mode), 0o640)


class AtomicInstallTests(unittest.TestCase):
    def test_failed_replace_preserves_config_and_removes_temp_file(self) -> None:
        spec = importlib.util.spec_from_file_location("install_kimi_hook", SCRIPT)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "config.toml"
            config_file.write_text("old = true\n", encoding="utf-8")

            with mock.patch.object(module.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    module.atomic_write(config_file, "new = true\n")

            self.assertEqual(config_file.read_text(encoding="utf-8"), "old = true\n")
            self.assertEqual(list(root.glob(".config.toml.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
