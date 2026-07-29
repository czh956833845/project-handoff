from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "install_client_hook.py"


class InstallerCliTests(unittest.TestCase):
    def run_cli(
        self,
        action: str,
        client: str,
        scope: str,
        *,
        home: Path,
        project: Path,
        platform: str = "darwin",
        extra: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                action,
                "--client",
                client,
                "--scope",
                scope,
                "--home",
                str(home),
                "--project-root",
                str(project),
                "--skill-root",
                str(SKILL_ROOT),
                "--python-executable",
                sys.executable,
                "--platform",
                platform,
                *extra,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_user_scope_paths_and_lifecycle_for_json_clients(self) -> None:
        expected_relative = {
            "claude": Path(".claude/settings.json"),
            "gemini": Path(".gemini/settings.json"),
            "qwen": Path(".qwen/settings.json"),
        }
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for client, relative in expected_relative.items():
                with self.subTest(client=client):
                    home = base / client / "home"
                    project = base / client / "project"
                    home.mkdir(parents=True)
                    project.mkdir(parents=True)
                    target = home / relative

                    first = self.run_cli(
                        "install", client, "user", home=home, project=project
                    )
                    second = self.run_cli(
                        "install", client, "user", home=home, project=project
                    )
                    doctor = self.run_cli(
                        "doctor", client, "user", home=home, project=project
                    )
                    uninstall = self.run_cli(
                        "uninstall", client, "user", home=home, project=project
                    )
                    after = self.run_cli(
                        "doctor", client, "user", home=home, project=project
                    )

                    self.assertEqual(first.returncode, 0, first.stderr)
                    self.assertEqual(second.returncode, 0, second.stderr)
                    self.assertEqual(doctor.returncode, 0, doctor.stderr)
                    self.assertIn("installed", doctor.stdout)
                    self.assertEqual(uninstall.returncode, 0, uninstall.stderr)
                    self.assertEqual(after.returncode, 1)
                    self.assertIn("not installed", after.stdout)
                    self.assertTrue(target.exists())
                    document = json.loads(target.read_text(encoding="utf-8"))
                    self.assertNotIn(
                        "project-handoff",
                        json.dumps(document, ensure_ascii=False),
                    )

    def test_project_scope_paths_for_json_clients(self) -> None:
        expected_relative = {
            "claude": Path(".claude/settings.json"),
            "gemini": Path(".gemini/settings.json"),
            "qwen": Path(".qwen/settings.json"),
        }
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for client, relative in expected_relative.items():
                with self.subTest(client=client):
                    home = base / client / "home"
                    project = base / client / "project"
                    home.mkdir(parents=True)
                    project.mkdir(parents=True)

                    result = self.run_cli(
                        "install", client, "project", home=home, project=project
                    )

                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue((project / relative).is_file())
                    self.assertFalse((home / relative).exists())

    def test_json_install_preserves_unrelated_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            project = base / "project"
            target = home / ".gemini/settings.json"
            target.parent.mkdir(parents=True)
            project.mkdir()
            target.write_text(
                json.dumps(
                    {
                        "theme": "dark",
                        "hooks": {
                            "SessionStart": [
                                {"hooks": [{"type": "command", "command": "keep"}]}
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = self.run_cli(
                "install", "gemini", "user", home=home, project=project
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            document = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(document["theme"], "dark")
            self.assertEqual(
                document["hooks"]["SessionStart"][0]["hooks"][0]["command"],
                "keep",
            )

    def test_copilot_user_and_project_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for scope, relative, owner in (
                ("user", Path(".copilot/hooks/project-handoff.json"), "home"),
                ("project", Path(".github/hooks/project-handoff.json"), "project"),
            ):
                with self.subTest(scope=scope):
                    home = base / scope / "home"
                    project = base / scope / "project"
                    home.mkdir(parents=True)
                    project.mkdir(parents=True)
                    target = (home if owner == "home" else project) / relative

                    install = self.run_cli(
                        "install", "copilot", scope, home=home, project=project
                    )
                    doctor = self.run_cli(
                        "doctor", "copilot", scope, home=home, project=project
                    )

                    self.assertEqual(install.returncode, 0, install.stderr)
                    document = json.loads(target.read_text(encoding="utf-8"))
                    self.assertEqual(document["version"], 1)
                    self.assertIn("preCompact", document["hooks"])
                    self.assertEqual(doctor.returncode, 0, doctor.stderr)
                    uninstall = self.run_cli(
                        "uninstall", "copilot", scope, home=home, project=project
                    )
                    self.assertEqual(uninstall.returncode, 0, uninstall.stderr)
                    self.assertFalse(target.exists())

    def test_copilot_refuses_unrelated_dedicated_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            project = base / "project"
            target = home / ".copilot/hooks/project-handoff.json"
            target.parent.mkdir(parents=True)
            project.mkdir()
            original = b'{"version": 1, "hooks": {"sessionStart": []}}\n'
            target.write_bytes(original)

            result = self.run_cli(
                "install", "copilot", "user", home=home, project=project
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not managed", result.stderr)
            self.assertEqual(target.read_bytes(), original)

    def test_copilot_uses_platform_specific_command_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for platform, expected_field, absent_field in (
                ("darwin", "bash", "powershell"),
                ("win32", "powershell", "bash"),
            ):
                with self.subTest(platform=platform):
                    home = base / platform / "home"
                    project = base / platform / "project"
                    home.mkdir(parents=True)
                    project.mkdir(parents=True)

                    result = self.run_cli(
                        "install",
                        "copilot",
                        "user",
                        home=home,
                        project=project,
                        platform=platform,
                    )

                    self.assertEqual(result.returncode, 0, result.stderr)
                    document = json.loads(
                        (
                            home / ".copilot/hooks/project-handoff.json"
                        ).read_text(encoding="utf-8")
                    )
                    entry = document["hooks"]["preCompact"][0]
                    self.assertIn(expected_field, entry)
                    self.assertNotIn(absent_field, entry)
                    self.assertNotIn("command", entry)

    def test_invalid_client_scope_combination_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            project = base / "project"
            home.mkdir()
            project.mkdir()

            result = self.run_cli(
                "install", "claude", "cloud", home=home, project=project
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(home.iterdir()), [])
            self.assertEqual(list(project.iterdir()), [])

    def test_config_override_does_not_bypass_scope_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            project = base / "project"
            override = base / "must-not-exist.json"
            home.mkdir()
            project.mkdir()

            result = self.run_cli(
                "install",
                "qwen",
                "cloud",
                home=home,
                project=project,
                extra=("--config-file", str(override)),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(override.exists())

    def test_explicit_config_file_override_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            project = base / "project"
            override = base / "custom settings.json"
            home.mkdir()
            project.mkdir()

            result = self.run_cli(
                "install",
                "qwen",
                "user",
                home=home,
                project=project,
                extra=("--config-file", str(override)),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(override.is_file())
            self.assertEqual(list(home.iterdir()), [])


class CopilotCloudTests(InstallerCliTests):
    def test_cloud_scope_vendors_self_contained_relative_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            project = base / "project"
            home.mkdir()
            project.mkdir()

            install = self.run_cli(
                "install", "copilot", "cloud", home=home, project=project
            )

            self.assertEqual(install.returncode, 0, install.stderr)
            hook_file = project / ".github/hooks/project-handoff.json"
            runtime = project / ".github/hooks/project-handoff"
            expected_files = {
                "client_event_adapter.py",
                "precompact_checkpoint.py",
                "file_safety.py",
                ".project-handoff-runtime.json",
            }
            self.assertEqual(
                {path.name for path in runtime.iterdir()},
                expected_files,
            )
            document = json.loads(hook_file.read_text(encoding="utf-8"))
            command = document["hooks"]["preCompact"][0]["bash"]
            self.assertEqual(
                command,
                "python3 .github/hooks/project-handoff/"
                "client_event_adapter.py --client copilot",
            )
            self.assertNotIn("command", document["hooks"]["preCompact"][0])
            combined = hook_file.read_text(encoding="utf-8") + "".join(
                path.read_text(encoding="utf-8") for path in runtime.iterdir()
            )
            self.assertNotIn(str(SKILL_ROOT.resolve()), combined)
            self.assertNotIn(str(project.resolve()), combined)

    def test_cloud_reinstall_repairs_owned_files_and_doctor_verifies_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            project = base / "project"
            home.mkdir()
            project.mkdir()
            first = self.run_cli(
                "install", "copilot", "cloud", home=home, project=project
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            adapter = (
                project
                / ".github/hooks/project-handoff/client_event_adapter.py"
            )
            adapter.write_text("tampered", encoding="utf-8")

            broken = self.run_cli(
                "doctor", "copilot", "cloud", home=home, project=project
            )
            repaired = self.run_cli(
                "install", "copilot", "cloud", home=home, project=project
            )
            healthy = self.run_cli(
                "doctor", "copilot", "cloud", home=home, project=project
            )

            self.assertEqual(broken.returncode, 1)
            self.assertIn("outdated", broken.stdout)
            self.assertEqual(repaired.returncode, 0, repaired.stderr)
            self.assertNotEqual(adapter.read_text(encoding="utf-8"), "tampered")
            self.assertEqual(healthy.returncode, 0, healthy.stderr)

    def test_cloud_uninstall_removes_only_owned_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            project = base / "project"
            home.mkdir()
            project.mkdir()
            install = self.run_cli(
                "install", "copilot", "cloud", home=home, project=project
            )
            self.assertEqual(install.returncode, 0, install.stderr)
            runtime = project / ".github/hooks/project-handoff"
            unrelated = runtime / "keep.txt"
            unrelated.write_text("keep", encoding="utf-8")

            uninstall = self.run_cli(
                "uninstall", "copilot", "cloud", home=home, project=project
            )

            self.assertEqual(uninstall.returncode, 0, uninstall.stderr)
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")
            self.assertFalse(
                (project / ".github/hooks/project-handoff.json").exists()
            )
            for name in (
                "client_event_adapter.py",
                "precompact_checkpoint.py",
                "file_safety.py",
                ".project-handoff-runtime.json",
            ):
                self.assertFalse((runtime / name).exists())


class ClineInstallerTests(InstallerCliTests):
    def test_user_editor_and_project_scopes_install_owned_fallback_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for scope, directories in (
                ("user", (Path(".cline/hooks"),)),
                ("editor", (Path("Documents/Cline/Hooks"),)),
                (
                    "project",
                    (Path(".cline/hooks"), Path(".clinerules/hooks")),
                ),
            ):
                with self.subTest(scope=scope):
                    home = base / scope / "home"
                    project = base / scope / "project"
                    home.mkdir(parents=True)
                    project.mkdir(parents=True)

                    install = self.run_cli(
                        "install", "cline", scope, home=home, project=project
                    )
                    doctor = self.run_cli(
                        "doctor", "cline", scope, home=home, project=project
                    )

                    self.assertEqual(install.returncode, 0, install.stderr)
                    self.assertEqual(doctor.returncode, 0, doctor.stderr)
                    for relative in directories:
                        root = home if scope in {"user", "editor"} else project
                        hook_dir = root / relative
                        names = {path.name for path in hook_dir.iterdir()}
                        if relative == Path(".cline/hooks"):
                            self.assertEqual(
                                names,
                                {
                                    "TaskStart.py",
                                    "TaskResume.py",
                                    "TaskComplete.py",
                                    "SessionShutdown.py",
                                    "PreCompact.py",
                                },
                            )
                        else:
                            self.assertEqual(
                                names,
                                {
                                    "TaskStart",
                                    "TaskResume",
                                    "TaskComplete",
                                    "SessionShutdown",
                                    "PreCompact",
                                },
                            )
                        for hook in hook_dir.iterdir():
                            content = hook.read_text(encoding="utf-8")
                            self.assertIn("project-handoff:managed", content)
                            self.assertIn("client_event_adapter.py", content)
                            self.assertEqual(hook.stat().st_mode & 0o111, 0o111)

                    uninstall = self.run_cli(
                        "uninstall", "cline", scope, home=home, project=project
                    )
                    self.assertEqual(uninstall.returncode, 0, uninstall.stderr)
                    for relative in directories:
                        root = home if scope in {"user", "editor"} else project
                        hook_dir = root / relative
                        self.assertEqual(
                            list(hook_dir.iterdir()) if hook_dir.exists() else [],
                            [],
                        )

    def test_refuses_unrelated_hook_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            project = base / "project"
            hook = home / ".cline/hooks/TaskStart.py"
            hook.parent.mkdir(parents=True)
            hook.write_text("# unrelated\n", encoding="utf-8")
            project.mkdir()

            result = self.run_cli(
                "install", "cline", "user", home=home, project=project
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not managed", result.stderr)
            self.assertEqual(hook.read_text(encoding="utf-8"), "# unrelated\n")

    def test_force_replaces_unrelated_hook(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            project = base / "project"
            hook = home / ".cline/hooks/TaskStart.py"
            hook.parent.mkdir(parents=True)
            hook.write_text("# unrelated\n", encoding="utf-8")
            project.mkdir()

            result = self.run_cli(
                "install",
                "cline",
                "user",
                home=home,
                project=project,
                extra=("--force",),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("project-handoff:managed", hook.read_text(encoding="utf-8"))

    def test_windows_reports_upstream_file_hook_limitation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            project = base / "project"
            home.mkdir()
            project.mkdir()

            result = self.run_cli(
                "install",
                "cline",
                "user",
                home=home,
                project=project,
                platform="win32",
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Windows", result.stderr)
            self.assertEqual(list(home.iterdir()), [])

    def test_hooks_directory_override_is_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "home"
            project = base / "project"
            override = base / "custom-hooks"
            home.mkdir()
            project.mkdir()

            result = self.run_cli(
                "install",
                "cline",
                "user",
                home=home,
                project=project,
                extra=("--hooks-dir", str(override)),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((override / "TaskStart.py").is_file())
            self.assertEqual(list(home.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
