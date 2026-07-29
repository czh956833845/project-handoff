from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "kimi_precompact_hook.py"
PENDING_PATH = Path("docs/project/.handoff-precompact-pending.json")


class KimiPreCompactHookCliTests(unittest.TestCase):
    def run_hook(self, payload: object | str) -> subprocess.CompletedProcess[str]:
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=raw,
            text=True,
            capture_output=True,
            check=False,
        )

    def create_project(self, root: Path, content: bytes = b"# Project handoff\n") -> Path:
        handoff = root / "docs/project/HANDOFF.md"
        handoff.parent.mkdir(parents=True)
        handoff.write_bytes(content)
        return handoff

    def test_auto_trigger_captures_exact_handoff_and_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            handoff_bytes = b"# Project handoff\n\n## Project goal\n\n- Preserve this.\n"
            self.create_project(project_root, handoff_bytes)
            payload = {
                "hook_event_name": "PreCompact",
                "session_id": "session-123",
                "cwd": str(project_root),
                "trigger": "auto",
                "token_count": 12345,
            }

            result = self.run_hook(payload)

            self.assertEqual(result.returncode, 0, result.stderr)
            marker_path = project_root / PENDING_PATH
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            self.assertEqual(marker["event"], "PreCompact")
            self.assertEqual(marker["trigger"], "auto")
            self.assertEqual(marker["session_id"], "session-123")
            self.assertEqual(marker["project_root"], str(project_root.resolve()))
            self.assertEqual(
                marker["handoff_revision"], hashlib.sha256(handoff_bytes).hexdigest()
            )
            self.assertTrue(marker["captured_at"].endswith("Z"))
            snapshot = project_root / marker["snapshot_path"]
            self.assertEqual(snapshot.read_bytes(), handoff_bytes)
            self.assertEqual(snapshot.parent, project_root / "docs/project/handoff-emergency")

    def test_manual_trigger_reason_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            self.create_project(project_root)

            result = self.run_hook(
                {
                    "hook_event_name": "PreCompact",
                    "session_id": "manual-session",
                    "cwd": str(project_root),
                    "trigger_reason": "manual",
                }
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            marker = json.loads((project_root / PENDING_PATH).read_text(encoding="utf-8"))
            self.assertEqual(marker["trigger"], "manual")

    def test_missing_handoff_skips_without_creating_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)

            result = self.run_hook(
                {
                    "hook_event_name": "PreCompact",
                    "session_id": "session-123",
                    "cwd": str(project_root),
                    "trigger": "auto",
                }
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((project_root / PENDING_PATH).exists())
            self.assertFalse((project_root / "docs/project/handoff-emergency").exists())

    def test_invalid_json_is_rejected(self) -> None:
        result = self.run_hook("not-json")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid event JSON", result.stderr)

    def test_wrong_event_is_rejected(self) -> None:
        result = self.run_hook(
            {"hook_event_name": "PostCompact", "cwd": "/tmp", "trigger": "auto"}
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected a PreCompact event", result.stderr)

    def test_invalid_trigger_is_rejected_without_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            self.create_project(project_root)

            result = self.run_hook(
                {
                    "hook_event_name": "PreCompact",
                    "cwd": str(project_root),
                    "trigger": "scheduled",
                }
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("manual or auto", result.stderr)
            self.assertFalse((project_root / PENDING_PATH).exists())

    def test_non_directory_cwd_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory) / "not-a-directory"
            file_path.write_text("x", encoding="utf-8")

            result = self.run_hook(
                {
                    "hook_event_name": "PreCompact",
                    "cwd": str(file_path),
                    "trigger": "auto",
                }
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("cwd is not a directory", result.stderr)

    def test_repeated_events_create_distinct_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            self.create_project(project_root)
            payload = {
                "hook_event_name": "PreCompact",
                "session_id": "session-123",
                "cwd": str(project_root),
                "trigger": "auto",
            }

            first = self.run_hook(payload)
            first_marker = json.loads(
                (project_root / PENDING_PATH).read_text(encoding="utf-8")
            )
            second = self.run_hook(payload)
            second_marker = json.loads(
                (project_root / PENDING_PATH).read_text(encoding="utf-8")
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertNotEqual(first_marker["snapshot_path"], second_marker["snapshot_path"])
            self.assertEqual(
                len(list((project_root / "docs/project/handoff-emergency").glob("*.md"))),
                2,
            )


class AtomicCaptureTests(unittest.TestCase):
    def load_module(self):
        spec = importlib.util.spec_from_file_location("kimi_precompact_hook", SCRIPT)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_failed_replace_preserves_old_marker_and_removes_temp_file(self) -> None:
        module = self.load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / ".handoff-precompact-pending.json"
            marker.write_bytes(b'{"old": true}\n')

            with mock.patch.object(module.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    module.atomic_write_bytes(marker, b'{"new": true}\n')

            self.assertEqual(marker.read_bytes(), b'{"old": true}\n')
            self.assertEqual(list(root.glob(".handoff-precompact-pending.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
