from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "install_global_rule.py"
BEGIN_MARKER = "<!-- project-handoff:begin -->"
END_MARKER = "<!-- project-handoff:end -->"


class InstallGlobalRuleCliTests(unittest.TestCase):
    def run_installer(
        self, agents_file: Path, rule_file: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--agents-file",
                str(agents_file),
                "--rule-file",
                str(rule_file),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_creates_missing_agents_file_with_managed_rule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents_file = root / "config" / "AGENTS.md"
            rule_file = root / "rule.md"
            rule_file.write_text("# Required rule\n\nInvoke `$project-handoff`.\n", encoding="utf-8")

            result = self.run_installer(agents_file, rule_file)

            self.assertEqual(result.returncode, 0, result.stderr)
            content = agents_file.read_text(encoding="utf-8")
            self.assertIn(BEGIN_MARKER, content)
            self.assertIn("Invoke `$project-handoff`.", content)
            self.assertIn(END_MARKER, content)

    def test_preserves_unrelated_global_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents_file = root / "AGENTS.md"
            agents_file.write_text("# Existing\n\nKeep this rule.\n", encoding="utf-8")
            rule_file = root / "rule.md"
            rule_file.write_text("# Handoff\n\nUse the skill.\n", encoding="utf-8")

            result = self.run_installer(agents_file, rule_file)

            self.assertEqual(result.returncode, 0, result.stderr)
            content = agents_file.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("# Existing\n\nKeep this rule.\n"))
            self.assertIn("# Handoff", content)

    def test_replaces_existing_managed_block_without_duplication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents_file = root / "AGENTS.md"
            agents_file.write_text(
                f"Before\n\n{BEGIN_MARKER}\nold rule\n{END_MARKER}\n\nAfter\n",
                encoding="utf-8",
            )
            rule_file = root / "rule.md"
            rule_file.write_text("new rule\n", encoding="utf-8")

            result = self.run_installer(agents_file, rule_file)

            self.assertEqual(result.returncode, 0, result.stderr)
            content = agents_file.read_text(encoding="utf-8")
            self.assertEqual(content.count(BEGIN_MARKER), 1)
            self.assertEqual(content.count(END_MARKER), 1)
            self.assertNotIn("old rule", content)
            self.assertIn("new rule", content)
            self.assertIn("Before", content)
            self.assertIn("After", content)

    def test_rejects_malformed_marker_state_and_preserves_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents_file = root / "AGENTS.md"
            old_content = f"Existing\n{BEGIN_MARKER}\nunclosed\n"
            agents_file.write_text(old_content, encoding="utf-8")
            rule_file = root / "rule.md"
            rule_file.write_text("new rule\n", encoding="utf-8")

            result = self.run_installer(agents_file, rule_file)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("managed markers", result.stderr)
            self.assertEqual(agents_file.read_text(encoding="utf-8"), old_content)


class AtomicInstallTests(unittest.TestCase):
    def test_failed_replace_preserves_agents_file_and_removes_temp_file(self) -> None:
        spec = importlib.util.spec_from_file_location("install_global_rule", SCRIPT)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents_file = root / "AGENTS.md"
            agents_file.write_text("old instructions\n", encoding="utf-8")

            with mock.patch.object(module.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    module.atomic_write(agents_file, "new instructions\n")

            self.assertEqual(agents_file.read_text(encoding="utf-8"), "old instructions\n")
            self.assertEqual(list(root.glob(".AGENTS.md.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
