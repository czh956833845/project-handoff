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


if __name__ == "__main__":
    unittest.main()
