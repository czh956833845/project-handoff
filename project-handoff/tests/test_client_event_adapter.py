from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "client_event_adapter.py"


def load_module():
    scripts = str(SKILL_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("client_event_adapter", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load client_event_adapter module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class NormalizationTests(unittest.TestCase):
    def test_normalizes_all_official_payload_shapes(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = str(Path(directory))
            cases = [
                (
                    "claude",
                    {
                        "hook_event_name": "PreCompact",
                        "cwd": root,
                        "trigger": "manual",
                        "session_id": "c",
                    },
                    ("PreCompact", "manual", "c"),
                ),
                (
                    "gemini",
                    {
                        "hook_event_name": "PreCompress",
                        "cwd": root,
                        "trigger": "auto",
                        "session_id": "g",
                        "timestamp": "2026-07-29T12:00:00Z",
                    },
                    ("PreCompress", "auto", "g"),
                ),
                (
                    "copilot",
                    {
                        "cwd": root,
                        "trigger": "auto",
                        "sessionId": "cp",
                        "timestamp": 1785326400000,
                    },
                    ("preCompact", "auto", "cp"),
                ),
                (
                    "copilot",
                    {
                        "hook_event_name": "PreCompact",
                        "cwd": root,
                        "trigger": "manual",
                        "session_id": "cp2",
                    },
                    ("PreCompact", "manual", "cp2"),
                ),
                (
                    "cline",
                    {
                        "hookName": "pre_compact",
                        "workspaceRoots": [root],
                        "taskId": "cl",
                        "timestamp": "2026-07-29T12:00:00Z",
                        "preCompact": {"contextSize": 9000},
                    },
                    ("PreCompact", "auto", "cl"),
                ),
                (
                    "qwen",
                    {
                        "hook_event_name": "PreCompact",
                        "cwd": root,
                        "trigger": "auto",
                        "session_id": "q",
                    },
                    ("PreCompact", "auto", "q"),
                ),
            ]

            for client, payload, expected in cases:
                with self.subTest(client=client, session=expected[2]):
                    event = module.normalize_event(client, payload)
                    self.assertEqual(
                        (event.event_name, event.trigger, event.session_id),
                        expected,
                    )
                    self.assertEqual(event.project_root, Path(root).resolve())

    def test_cline_accepts_legacy_pascal_case_event_name(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            event = module.normalize_event(
                "cline",
                {
                    "hookName": "PreCompact",
                    "workspaceRoots": [directory],
                    "taskId": "legacy",
                },
            )

            self.assertEqual(event.event_name, "PreCompact")
            self.assertEqual(event.trigger, "auto")

    def test_cline_accepts_wired_lifecycle_fallback_events(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            for hook_name, expected_event in (
                ("agent_start", "TaskStart"),
                ("agent_resume", "TaskResume"),
                ("agent_end", "TaskComplete"),
                ("session_shutdown", "SessionShutdown"),
            ):
                with self.subTest(hook_name=hook_name):
                    event = module.normalize_event(
                        "cline",
                        {
                            "hookName": hook_name,
                            "workspaceRoots": [directory],
                            "taskId": "task",
                        },
                    )
                    self.assertEqual(event.event_name, expected_event)
                    self.assertEqual(event.trigger, "auto")

    def test_rejects_wrong_events_and_invalid_roots(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            invalid_cases = [
                ("claude", {"hook_event_name": "PostCompact", "cwd": directory}),
                ("gemini", {"hook_event_name": "PreCompact", "cwd": directory}),
                ("qwen", {"hook_event_name": "PreCompress", "cwd": directory}),
                ("cline", {"hookName": "pre_compact", "workspaceRoots": []}),
                ("copilot", {"cwd": directory, "trigger": "scheduled"}),
            ]
            for client, payload in invalid_cases:
                with self.subTest(client=client, payload=payload):
                    with self.assertRaises(ValueError):
                        module.normalize_event(client, payload)

    def test_rejects_unsupported_client(self) -> None:
        module = load_module()
        with self.assertRaisesRegex(ValueError, "unsupported client"):
            module.normalize_event("cursor", {})


class RuntimeTests(unittest.TestCase):
    def test_success_responses_match_client_contracts(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            handoff = root / "docs/project/HANDOFF.md"
            handoff.parent.mkdir(parents=True)
            handoff.write_text("state", encoding="utf-8")
            payloads = {
                "claude": {
                    "hook_event_name": "PreCompact",
                    "cwd": str(root),
                    "trigger": "auto",
                },
                "gemini": {
                    "hook_event_name": "PreCompress",
                    "cwd": str(root),
                    "trigger": "auto",
                },
                "copilot": {
                    "cwd": str(root),
                    "trigger": "manual",
                    "sessionId": "cp",
                },
                "cline": {
                    "hookName": "pre_compact",
                    "workspaceRoots": [str(root)],
                    "taskId": "cl",
                },
                "qwen": {
                    "hook_event_name": "PreCompact",
                    "cwd": str(root),
                    "trigger": "manual",
                },
            }
            expected_stdout = {
                "claude": "",
                "gemini": "{}\n",
                "copilot": "{}\n",
                "cline": module.success_payload("cline"),
                "qwen": "{}\n",
            }
            for client, payload in payloads.items():
                with self.subTest(client=client):
                    code, stdout, stderr = module.run(client, json.dumps(payload))
                    self.assertEqual(code, 0)
                    self.assertEqual(stdout, expected_stdout[client])
                    self.assertEqual(stderr, "")

    def test_errors_are_fail_open_and_keep_valid_stdout(self) -> None:
        module = load_module()
        for client in ("claude", "gemini", "copilot", "cline", "qwen"):
            with self.subTest(client=client):
                code, stdout, stderr = module.run(client, "not-json")
                self.assertEqual(code, 0)
                self.assertEqual(stdout, module.success_payload(client))
                self.assertIn("error:", stderr)

    def test_cli_reads_stdin_and_writes_only_client_json_to_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = {
                "hook_event_name": "PreCompress",
                "cwd": directory,
                "trigger": "auto",
            }
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--client", "gemini"],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "{}\n")
            self.assertEqual(result.stderr, "")

    def test_cline_response_requests_handoff_recovery(self) -> None:
        module = load_module()
        response = json.loads(module.success_payload("cline"))

        self.assertFalse(response["cancel"])
        self.assertIn("project-handoff", response["context"])
        self.assertEqual(response["context"], response["contextModification"])


if __name__ == "__main__":
    unittest.main()
