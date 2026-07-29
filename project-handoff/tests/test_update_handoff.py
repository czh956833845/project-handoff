from __future__ import annotations

import importlib.util
import fcntl
import hashlib
import io
import subprocess
import sys
import tempfile
import unittest
import stat
from pathlib import Path
from contextlib import redirect_stderr
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "update_handoff.py"


def load_updater():
    spec = importlib.util.spec_from_file_location("update_handoff", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load update_handoff module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_handoff(marker: str = "initial") -> str:
    return f"""# Project handoff

Updated: {marker}

## Project goal

- Ship the handoff skill.

## Scope and boundaries

- Do not publish externally.

## Key decisions

- Use an atomic local replacement.

## Completed work

- {marker}

## Verification evidence

- Automated test fixture.

## Current files

- `project-handoff/SKILL.md`

## Open items

- None.

## Next step

- Continue.
"""


class UpdateHandoffCliTests(unittest.TestCase):
    def run_revision(self, project: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "revision",
                "--project-root",
                str(project),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def run_update(
        self,
        project: Path,
        content_file: Path,
        expected_revision: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "update",
                "--project-root",
                str(project),
                "--content-file",
                str(content_file),
                "--expected-revision",
                expected_revision,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_creates_handoff_with_all_required_sections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content_file = root / "prepared.md"
            content_file.write_text(valid_handoff(), encoding="utf-8")

            result = self.run_update(root, content_file, "absent")

            self.assertEqual(result.returncode, 0, result.stderr)
            destination = root / "docs" / "project" / "HANDOFF.md"
            self.assertEqual(destination.read_text(encoding="utf-8"), valid_handoff())

    def test_replaces_existing_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "docs" / "project" / "HANDOFF.md"
            destination.parent.mkdir(parents=True)
            destination.write_text(valid_handoff("old"), encoding="utf-8")
            content_file = root / "prepared.md"
            content_file.write_text(valid_handoff("new"), encoding="utf-8")

            expected = hashlib.sha256(valid_handoff("old").encode()).hexdigest()
            result = self.run_update(root, content_file, expected)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(destination.read_text(encoding="utf-8"), valid_handoff("new"))

    def test_preserves_existing_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "docs" / "project" / "HANDOFF.md"
            destination.parent.mkdir(parents=True)
            destination.write_text(valid_handoff("old"), encoding="utf-8")
            destination.chmod(0o640)
            content_file = root / "prepared.md"
            content_file.write_text(valid_handoff("new"), encoding="utf-8")

            expected = hashlib.sha256(valid_handoff("old").encode()).hexdigest()
            result = self.run_update(root, content_file, expected)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o640)

    def test_rejects_missing_required_section_and_preserves_old_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "docs" / "project" / "HANDOFF.md"
            destination.parent.mkdir(parents=True)
            old_content = valid_handoff("old")
            destination.write_text(old_content, encoding="utf-8")
            content_file = root / "prepared.md"
            content_file.write_text(
                valid_handoff("invalid").replace("## Next step", "## Later"),
                encoding="utf-8",
            )

            expected = hashlib.sha256(old_content.encode()).hexdigest()
            result = self.run_update(root, content_file, expected)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Next step", result.stderr)
            self.assertEqual(destination.read_text(encoding="utf-8"), old_content)

    def test_rejects_duplicate_required_section_and_preserves_old_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "docs" / "project" / "HANDOFF.md"
            destination.parent.mkdir(parents=True)
            old_content = valid_handoff("old")
            destination.write_text(old_content, encoding="utf-8")
            content_file = root / "prepared.md"
            content_file.write_text(
                valid_handoff("invalid") + "\n## Project goal\n\n- Duplicate.\n",
                encoding="utf-8",
            )

            expected = hashlib.sha256(old_content.encode()).hexdigest()
            result = self.run_update(root, content_file, expected)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Project goal", result.stderr)
            self.assertEqual(destination.read_text(encoding="utf-8"), old_content)

    def test_revision_reports_absent_for_missing_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_revision(Path(directory))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "absent")

    def test_revision_reports_sha256_for_existing_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "docs" / "project" / "HANDOFF.md"
            destination.parent.mkdir(parents=True)
            content = valid_handoff("existing")
            destination.write_text(content, encoding="utf-8")

            result = self.run_revision(root)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), hashlib.sha256(content.encode()).hexdigest())

    def test_rejects_stale_absent_revision_after_another_creator_wins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.md"
            second = root / "second.md"
            first.write_text(valid_handoff("first"), encoding="utf-8")
            second.write_text(valid_handoff("second"), encoding="utf-8")

            first_result = self.run_update(root, first, "absent")
            second_result = self.run_update(root, second, "absent")

            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            self.assertNotEqual(second_result.returncode, 0)
            self.assertIn("conflict", second_result.stderr.lower())
            self.assertEqual(
                (root / "docs" / "project" / "HANDOFF.md").read_text(encoding="utf-8"),
                valid_handoff("first"),
            )

    def test_rejects_second_agent_using_same_old_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "docs" / "project" / "HANDOFF.md"
            destination.parent.mkdir(parents=True)
            old = valid_handoff("old")
            destination.write_text(old, encoding="utf-8")
            expected = hashlib.sha256(old.encode()).hexdigest()
            first = root / "first.md"
            second = root / "second.md"
            first.write_text(valid_handoff("first"), encoding="utf-8")
            second.write_text(valid_handoff("second"), encoding="utf-8")

            first_result = self.run_update(root, first, expected)
            second_result = self.run_update(root, second, expected)

            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            self.assertNotEqual(second_result.returncode, 0)
            self.assertIn("reread", second_result.stderr.lower())
            self.assertEqual(destination.read_text(encoding="utf-8"), valid_handoff("first"))


class AtomicWriteTests(unittest.TestCase):
    def test_failed_replace_preserves_old_file_and_removes_temp_file(self) -> None:
        module = load_updater()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "HANDOFF.md"
            destination.write_text("old", encoding="utf-8")

            with mock.patch.object(module.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    module.atomic_write(destination, "new")

            self.assertEqual(destination.read_text(encoding="utf-8"), "old")
            self.assertEqual(list(root.glob(".HANDOFF.md.*.tmp")), [])


class LockTests(unittest.TestCase):
    def test_lock_timeout_preserves_current_handoff(self) -> None:
        module = load_updater()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs" / "project"
            docs.mkdir(parents=True)
            destination = docs / "HANDOFF.md"
            old = valid_handoff("old")
            destination.write_text(old, encoding="utf-8")
            prepared = root / "prepared.md"
            prepared.write_text(valid_handoff("new"), encoding="utf-8")
            expected = hashlib.sha256(old.encode()).hexdigest()

            with (docs / ".HANDOFF.lock").open("a+") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    module.update_handoff(
                        root,
                        prepared,
                        expected,
                        lock_timeout_seconds=0.05,
                    )
                except Exception as error:
                    caught = error
                else:
                    caught = None

            self.assertIsInstance(caught, TimeoutError)
            self.assertIn("handoff lock", str(caught).lower())
            self.assertEqual(destination.read_text(encoding="utf-8"), old)


class HistorySnapshotTests(unittest.TestCase):
    def run_update(
        self,
        project: Path,
        content_file: Path,
        expected_revision: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "update",
                "--project-root",
                str(project),
                "--content-file",
                str(content_file),
                "--expected-revision",
                expected_revision,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_replacement_snapshots_exact_old_content_with_revision_in_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "docs" / "project" / "HANDOFF.md"
            destination.parent.mkdir(parents=True)
            old = valid_handoff("old")
            destination.write_text(old, encoding="utf-8")
            revision = hashlib.sha256(old.encode()).hexdigest()
            prepared = root / "prepared.md"
            prepared.write_text(valid_handoff("new"), encoding="utf-8")

            result = self.run_update(root, prepared, revision)

            self.assertEqual(result.returncode, 0, result.stderr)
            snapshots = list((destination.parent / "handoff-history").glob("*.md"))
            self.assertEqual(len(snapshots), 1)
            self.assertIn(revision[:12], snapshots[0].name)
            self.assertEqual(snapshots[0].read_bytes(), old.encode())

    def test_first_creation_does_not_create_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = root / "prepared.md"
            prepared.write_text(valid_handoff("first"), encoding="utf-8")

            result = self.run_update(root, prepared, "absent")

            self.assertEqual(result.returncode, 0, result.stderr)
            history = root / "docs" / "project" / "handoff-history"
            self.assertEqual(list(history.glob("*.md")) if history.exists() else [], [])

    def test_conflict_does_not_create_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "docs" / "project" / "HANDOFF.md"
            destination.parent.mkdir(parents=True)
            destination.write_text(valid_handoff("current"), encoding="utf-8")
            prepared = root / "prepared.md"
            prepared.write_text(valid_handoff("stale"), encoding="utf-8")

            result = self.run_update(root, prepared, "0" * 64)

            self.assertNotEqual(result.returncode, 0)
            history = destination.parent / "handoff-history"
            self.assertEqual(list(history.glob("*.md")) if history.exists() else [], [])

    def test_retains_newest_fifty_snapshots_and_ignores_unrelated_files(self) -> None:
        module = load_updater()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "docs" / "project" / "HANDOFF.md"
            destination.parent.mkdir(parents=True)
            destination.write_text(valid_handoff("version-0"), encoding="utf-8")

            for index in range(1, 52):
                prepared = root / "prepared.md"
                prepared.write_text(valid_handoff(f"version-{index}"), encoding="utf-8")
                module.update_handoff(
                    root,
                    prepared,
                    module.current_revision(destination),
                )

            history = destination.parent / "handoff-history"
            history.mkdir(exist_ok=True)
            unrelated = history / "notes.txt"
            unrelated.write_text("keep", encoding="utf-8")
            self.assertTrue(hasattr(module, "prune_history"))
            module.prune_history(history)
            snapshots = sorted(history.glob("*.md"))

            self.assertEqual(len(snapshots), 50)
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")
            self.assertFalse(
                any("version-0" in path.read_text(encoding="utf-8") for path in snapshots)
            )

    def test_snapshot_failure_preserves_current_handoff(self) -> None:
        module = load_updater()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "docs" / "project" / "HANDOFF.md"
            destination.parent.mkdir(parents=True)
            old = valid_handoff("old")
            destination.write_text(old, encoding="utf-8")
            prepared = root / "prepared.md"
            prepared.write_text(valid_handoff("new"), encoding="utf-8")

            with mock.patch.object(
                module,
                "create_snapshot",
                side_effect=OSError("snapshot failed"),
            ):
                with self.assertRaisesRegex(OSError, "snapshot failed"):
                    module.update_handoff(
                        root,
                        prepared,
                        hashlib.sha256(old.encode()).hexdigest(),
                    )

            self.assertEqual(destination.read_text(encoding="utf-8"), old)

    def test_current_replacement_failure_removes_transaction_snapshot(self) -> None:
        module = load_updater()
        real_atomic_write = module.atomic_write
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "docs" / "project" / "HANDOFF.md"
            destination.parent.mkdir(parents=True)
            old = valid_handoff("old")
            destination.write_text(old, encoding="utf-8")
            prepared = root / "prepared.md"
            prepared.write_text(valid_handoff("new"), encoding="utf-8")

            def fail_current(path: Path, content: str) -> None:
                if path == destination:
                    raise OSError("current replace failed")
                real_atomic_write(path, content)

            with mock.patch.object(module, "atomic_write", side_effect=fail_current):
                with self.assertRaisesRegex(OSError, "current replace failed"):
                    module.update_handoff(
                        root,
                        prepared,
                        hashlib.sha256(old.encode()).hexdigest(),
                    )

            history = destination.parent / "handoff-history"
            self.assertEqual(destination.read_text(encoding="utf-8"), old)
            self.assertEqual(list(history.glob("*.md")), [])

    def test_prune_failure_warns_but_keeps_successful_update(self) -> None:
        module = load_updater()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "docs" / "project" / "HANDOFF.md"
            destination.parent.mkdir(parents=True)
            old = valid_handoff("old")
            destination.write_text(old, encoding="utf-8")
            prepared = root / "prepared.md"
            new = valid_handoff("new")
            prepared.write_text(new, encoding="utf-8")
            stderr = io.StringIO()

            with mock.patch.object(module, "prune_history", side_effect=OSError("prune failed")):
                with redirect_stderr(stderr):
                    result = module.update_handoff(
                        root,
                        prepared,
                        hashlib.sha256(old.encode()).hexdigest(),
                    )

            self.assertEqual(result, destination)
            self.assertEqual(destination.read_text(encoding="utf-8"), new)
            self.assertIn("warning", stderr.getvalue().lower())
            self.assertIn("prune failed", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
