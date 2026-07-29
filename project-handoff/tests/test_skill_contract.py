from __future__ import annotations

import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def test_skill_requires_first_action_for_every_project_workspace_task(self) -> None:
        content = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("every project-workspace task", content)
        self.assertIn("first project action", content)
        self.assertIn("After context compaction", content)

    def test_global_rule_requires_skill_but_excludes_pure_conversation(self) -> None:
        rule_file = SKILL_ROOT / "assets" / "global-AGENTS-rule.md"
        self.assertTrue(rule_file.exists(), "global rule asset must exist")
        content = rule_file.read_text(encoding="utf-8")
        normalized = content.lower()

        self.assertIn("$project-handoff", content)
        self.assertIn("before any project-specific", normalized)
        self.assertIn("Do not invoke", content)
        self.assertIn("pure conversation", content)

    def test_skill_requires_revision_aware_updates_and_conflict_merging(self) -> None:
        content = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("update_handoff.py revision", content)
        self.assertIn("--expected-revision", content)
        self.assertIn("handoff-history", content)
        self.assertIn("50", content)
        self.assertIn("reread", content.lower())
        self.assertIn("merge", content.lower())
        self.assertIn("Do not retry the old draft", content)

    def test_skill_defines_kimi_installation_and_recovery(self) -> None:
        content = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Kimi Code", content)
        self.assertIn("scripts/install_kimi_hook.py", content)
        self.assertIn("scripts/kimi_precompact_hook.py", content)
        self.assertIn("docs/project/handoff-emergency/", content)
        self.assertIn("docs/project/.handoff-precompact-pending.json", content)
        self.assertIn("return values", content)
        self.assertIn("After reading `docs/project/HANDOFF.md`", content)
        self.assertIn("referenced emergency snapshot", content)
        self.assertTrue((SKILL_ROOT / "scripts/install_kimi_hook.py").is_file())
        self.assertTrue((SKILL_ROOT / "scripts/kimi_precompact_hook.py").is_file())

    def test_skill_routes_five_client_installation_and_recovery(self) -> None:
        content = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("scripts/install_client_hook.py", content)
        for client in ("Claude", "Gemini", "Copilot", "Cline", "Qwen"):
            self.assertIn(client, content)
        self.assertIn("PreCompress", content)
        self.assertIn("not wired", content)
        self.assertIn("references/client-integrations.md", content)
        self.assertIn(".handoff-precompact-pending.json", content)
        self.assertIn("semantic", content.lower())

    def test_client_integration_reference_documents_scopes_and_limits(self) -> None:
        reference = SKILL_ROOT / "references/client-integrations.md"
        self.assertTrue(reference.is_file())
        content = reference.read_text(encoding="utf-8")

        for client in (
            "Claude Code",
            "Gemini CLI",
            "GitHub Copilot",
            "Cline",
            "Qwen Code",
        ):
            self.assertIn(client, content)
        for action in ("install", "doctor", "uninstall"):
            self.assertIn(action, content)
        self.assertIn("PreCompact", content)
        self.assertIn("PreCompress", content)
        self.assertIn("Cloud", content)
        self.assertIn("Windows", content)
        self.assertIn("not wired", content)

    def test_public_readme_describes_implemented_client_commands(self) -> None:
        readme = SKILL_ROOT.parent / "README.md"
        self.assertTrue(readme.is_file())
        content = readme.read_text(encoding="utf-8")

        self.assertIn("install_client_hook.py install", content)
        self.assertIn("install_client_hook.py doctor", content)
        self.assertIn("install_client_hook.py uninstall", content)
        for client in ("claude", "gemini", "copilot", "cline", "qwen"):
            self.assertIn(f"--client {client}", content)
        self.assertIn("--scope cloud", content)
        self.assertIn("Windows", content)


if __name__ == "__main__":
    unittest.main()
