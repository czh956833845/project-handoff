# Mandatory project handoff

For every project-workspace task, you MUST invoke `$project-handoff` as the first workflow skill.

Treat the request as a project-workspace task when both conditions are true:

1. The active workspace contains project evidence such as a Git repository, project instruction file, source tree, package manifest, build configuration, or existing `docs/project/HANDOFF.md`.
2. The user asks you to inspect, plan, change, build, test, review, diagnose, or resume that project.

Before any project-specific tool call, edit, plan, diagnosis, or implementation reasoning:

1. Invoke `$project-handoff`.
2. Resolve the project root.
3. Read `docs/project/HANDOFF.md` completely if it exists.
4. Create it from the Skill template if it does not exist.
5. Continue with other skills and project work only afterward.

After context compaction, repeat the read step as the first project action before continuing.

Do not invoke `$project-handoff` for pure conversation unrelated to project inspection or changes, including simple translation, general knowledge, time or weather lookup, and casual discussion. A filesystem current directory by itself does not make a conversational request project work.
