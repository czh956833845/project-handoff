from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "precompact_checkpoint.py"


def load_module():
    scripts = str(SKILL_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("precompact_checkpoint", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load precompact_checkpoint module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CheckpointTests(unittest.TestCase):
    def test_captures_exact_snapshot_and_complete_marker(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            handoff = root / "docs/project/HANDOFF.md"
            handoff.parent.mkdir(parents=True)
            handoff.write_bytes("目标\n".encode("utf-8"))
            event = module.NormalizedEvent(
                client="claude",
                event_name="PreCompact",
                trigger="auto",
                project_root=root,
                session_id="session-1",
                timestamp="2026-07-29T12:00:00Z",
            )

            marker_path = module.capture_checkpoint(event)

            self.assertIsNotNone(marker_path)
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            snapshot = root / marker["snapshot_path"]
            self.assertEqual(snapshot.read_bytes(), handoff.read_bytes())
            self.assertEqual(marker["client"], "claude")
            self.assertEqual(marker["event"], "PreCompact")
            self.assertEqual(marker["trigger"], "auto")
            self.assertEqual(marker["session_id"], "session-1")
            self.assertEqual(marker["event_timestamp"], "2026-07-29T12:00:00Z")
            self.assertEqual(marker["project_root"], str(root.resolve()))
            self.assertEqual(
                marker["handoff_revision"],
                module.hashlib.sha256(handoff.read_bytes()).hexdigest(),
            )
            self.assertTrue(marker["captured_at"].endswith("Z"))

    def test_missing_handoff_leaves_project_unchanged(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event = module.NormalizedEvent(
                client="qwen",
                event_name="PreCompact",
                trigger="manual",
                project_root=root,
            )

            marker_path = module.capture_checkpoint(event)

            self.assertIsNone(marker_path)
            self.assertEqual(list(root.iterdir()), [])

    def test_rejects_invalid_trigger_before_writing(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event = module.NormalizedEvent(
                client="gemini",
                event_name="PreCompress",
                trigger="threshold",
                project_root=root,
            )

            with self.assertRaisesRegex(ValueError, "manual or auto"):
                module.capture_checkpoint(event)

            self.assertEqual(list(root.iterdir()), [])

    def test_marker_failure_removes_new_snapshot(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            handoff = root / "docs/project/HANDOFF.md"
            handoff.parent.mkdir(parents=True)
            handoff.write_text("state", encoding="utf-8")
            event = module.NormalizedEvent(
                client="copilot",
                event_name="preCompact",
                trigger="auto",
                project_root=root,
            )
            real_write = module.atomic_write_bytes
            calls = 0

            def fail_marker(path: Path, content: bytes) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("marker failed")
                real_write(path, content)

            with mock.patch.object(module, "atomic_write_bytes", side_effect=fail_marker):
                with self.assertRaisesRegex(OSError, "marker failed"):
                    module.capture_checkpoint(event)

            emergency = root / "docs/project/handoff-emergency"
            self.assertEqual(list(emergency.glob("*.md")), [])
            self.assertFalse(
                (root / "docs/project/.handoff-precompact-pending.json").exists()
            )

    def test_capture_holds_the_shared_handoff_lock(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            handoff = root / "docs/project/HANDOFF.md"
            handoff.parent.mkdir(parents=True)
            handoff.write_text("state", encoding="utf-8")
            observed: list[Path] = []

            @contextmanager
            def record_lock(path: Path):
                observed.append(path)
                yield

            event = module.NormalizedEvent(
                client="claude",
                event_name="PreCompact",
                trigger="auto",
                project_root=root,
            )
            with mock.patch.object(module, "file_lock", side_effect=record_lock):
                module.capture_checkpoint(event)

            self.assertEqual(
                observed,
                [root.resolve() / "docs/project/.HANDOFF.lock"],
            )


if __name__ == "__main__":
    unittest.main()
