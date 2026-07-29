from __future__ import annotations

import importlib.util
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "file_safety.py"


def load_module():
    spec = importlib.util.spec_from_file_location("file_safety", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load file_safety module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AtomicWriteTests(unittest.TestCase):
    def test_atomic_write_bytes_replaces_complete_file_and_preserves_mode(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "state.bin"
            destination.write_bytes(b"old")
            destination.chmod(0o640)

            module.atomic_write_bytes(destination, b"new")

            self.assertEqual(destination.read_bytes(), b"new")
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o640)
            self.assertEqual(list(destination.parent.glob(".state.bin.*.tmp")), [])

    def test_failed_replace_preserves_old_file_and_removes_temporary(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "state.txt"
            destination.write_text("old", encoding="utf-8")

            with mock.patch.object(module.os, "replace", side_effect=OSError("failed")):
                with self.assertRaisesRegex(OSError, "failed"):
                    module.atomic_write_text(destination, "new")

            self.assertEqual(destination.read_text(encoding="utf-8"), "old")
            self.assertEqual(list(destination.parent.glob(".state.txt.*.tmp")), [])


class LockTests(unittest.TestCase):
    def test_file_lock_uses_injected_backend(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            calls: list[str] = []
            backend = module.LockBackend(
                lock=lambda handle: calls.append("lock"),
                unlock=lambda handle: calls.append("unlock"),
                would_block=(BlockingIOError,),
            )

            with module.file_lock(Path(directory) / ".lock", backend=backend):
                calls.append("body")

            self.assertEqual(calls, ["lock", "body", "unlock"])

    def test_timeout_reports_handoff_lock(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            backend = module.LockBackend(
                lock=lambda handle: (_ for _ in ()).throw(BlockingIOError()),
                unlock=lambda handle: None,
                would_block=(BlockingIOError,),
            )

            with self.assertRaisesRegex(TimeoutError, "handoff lock"):
                with module.file_lock(
                    Path(directory) / ".lock",
                    timeout_seconds=0.001,
                    backend=backend,
                ):
                    self.fail("lock should not be acquired")

    def test_selects_windows_backend_without_importing_fcntl(self) -> None:
        module = load_module()
        fake_msvcrt = mock.Mock()
        fake_msvcrt.LK_NBLCK = 1
        fake_msvcrt.LK_UNLCK = 2

        with mock.patch.object(module.importlib, "import_module") as import_module:
            import_module.return_value = fake_msvcrt
            module.select_lock_backend("win32")

        import_module.assert_called_once_with("msvcrt")

    def test_selects_posix_backend_without_importing_msvcrt(self) -> None:
        module = load_module()
        fake_fcntl = mock.Mock()
        fake_fcntl.LOCK_EX = 1
        fake_fcntl.LOCK_NB = 2
        fake_fcntl.LOCK_UN = 4

        with mock.patch.object(module.importlib, "import_module") as import_module:
            import_module.return_value = fake_fcntl
            module.select_lock_backend("darwin")

        import_module.assert_called_once_with("fcntl")


if __name__ == "__main__":
    unittest.main()
