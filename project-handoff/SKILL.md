---
name: project-handoff
description: Maintain a durable `docs/project/HANDOFF.md` checkpoint for Codex or Kimi Code project work. Invoke for every project-workspace task when starting or resuming work, and refresh after important phases, before pauses or handoffs, before detectable context compaction, and after compaction so goals, boundaries, decisions, completed work, evidence, active files, open items, and the next action survive context loss. Do not invoke for pure conversation unrelated to project inspection or changes.
---

# Project Handoff

Keep one concise, truthful source of current project state at `docs/project/HANDOFF.md`.

For every project-workspace task, use this as the first workflow skill. The global Codex instruction owns mandatory routing; this skill owns what to read, create, and refresh after invocation.

## Start or resume work

1. Resolve the project root. Prefer the Git top-level directory; otherwise use the active workspace root.
2. As the first project action, check `docs/project/HANDOFF.md` before any project-specific tool call, edit, plan, diagnosis, or implementation reasoning.
3. If it exists, read it completely. Compare drift-prone claims with current repository evidence when cheap to verify.
4. If it does not exist, copy the structure from `assets/HANDOFF.template.md`, replace `Unknown` with known facts, and create it with the atomic updater before substantial implementation.
5. If the handoff conflicts with current repository evidence, report the conflict and repair the handoff before continuing.

After context compaction, make reading the existing handoff the first project action. Do not edit files, run project-changing tools, or continue implementation reasoning first.

## Refresh checkpoints

Refresh the handoff:

- after an important phase produces a durable result;
- after tests, builds, reviews, or deployments materially change the evidence;
- before pausing, ending, or handing off the task;
- immediately before compaction when the client exposes an upcoming-compaction signal;
- immediately after compaction, after reading it, if the recovered state reveals stale information.

Treat a feature completion, resolved defect, accepted decision, completed investigation, or changed blocker as an important phase. Do not update after every conversational turn.

Codex clients may compact without exposing advance notice. Never claim that a pre-compaction refresh happened without a signal. Use phase-end and pause checkpoints as the required fallback.

## Install Kimi Code integration

When configuring this Skill for Kimi Code CLI, inspect the target configuration and run:

```bash
python3 <skill-directory>/scripts/install_kimi_hook.py \
  --config-file ~/.kimi-code/config.toml \
  --skill-root <skill-directory>
```

The installer atomically creates or updates one managed Kimi `PreCompact` hook for both `manual` and `auto` compaction. It preserves content outside `# project-handoff:begin` and `# project-handoff:end`, rejects malformed or duplicated managed markers, and is safe to run repeatedly.

The installed hook invokes `scripts/kimi_precompact_hook.py`. Kimi Code ignores `PreCompact` return values, so the hook never claims that it semantically refreshed the canonical handoff. Instead, when `docs/project/HANDOFF.md` exists under the event `cwd`, it writes the current bytes atomically to `docs/project/handoff-emergency/` and then atomically writes `docs/project/.handoff-precompact-pending.json`. A project without a handoff is left unchanged. Hook errors are fail-open and must be reported as missing recovery evidence, not as a completed checkpoint.

## Recover after Kimi compaction

After reading `docs/project/HANDOFF.md` as the first project action, check `docs/project/.handoff-precompact-pending.json` before continuing any project reasoning or mutation. If the marker exists:

1. Read it completely and verify that its `project_root` matches the active project.
2. Read the referenced emergency snapshot completely.
3. Compare the snapshot revision and content with the canonical handoff.
4. Recover any missing current state into the canonical handoff through the revision-aware updater; never overwrite a newer canonical decision blindly.
5. Only after recovery succeeds, archive or remove the pending marker so the same compaction event is not recovered twice.

Treat the canonical handoff as authoritative when it is demonstrably newer. Treat the emergency snapshot as recovery evidence, not as a second canonical handoff.

## Prepare the document

Rewrite the eight current-state sections as the latest truth:

- `Project goal`
- `Scope and boundaries`
- `Key decisions`
- `Completed work`
- `Verification evidence`
- `Current files`
- `Open items`
- `Next step`

Keep every heading exactly once as a level-two Markdown heading. Keep `Recent updates` to at most 10 short milestone entries, newest first. Remove superseded detail instead of accumulating a transcript.

Follow these evidence rules:

- Distinguish completed, locally verified, externally verified, planned, and blocked work.
- Record concrete commands and outcomes for verification claims.
- Use repository-relative paths when possible.
- Write `Unknown` when a fact cannot be established.
- Name one immediately executable action under `Next step`.
- Never place secrets, tokens, credentials, or unnecessary personal data in the handoff.

## Update atomically

Before reading the handoff for an update, capture the revision that the draft will be based on:

```bash
python3 <skill-directory>/scripts/update_handoff.py revision \
  --project-root <project-root>
```

The command prints a SHA-256 revision or `absent`. Then read `HANDOFF.md` completely and prepare the replacement Markdown in a separate file, preferably under a temporary directory. Capturing the revision before the read is conservative: any concurrent change afterward makes the update conflict instead of allowing stale content to overwrite it.

Review the complete draft, then run:

```bash
python3 <skill-directory>/scripts/update_handoff.py update \
  --project-root <project-root> \
  --content-file <prepared-markdown> \
  --expected-revision <captured-revision>
```

Resolve `<skill-directory>` from the loaded skill location. Do not assemble the Markdown through shell interpolation.

The updater validates all required headings, holds a persistent exclusive lock, verifies that the current revision still matches, saves the displaced version, and atomically replaces the current handoff. It preserves existing permissions and retains the newest 50 previous versions under `docs/project/handoff-history/`.

If the updater reports a conflict, another agent changed the handoff after the captured revision. Do not retry the old draft with the new revision. Rerun the revision command, reread the current handoff, merge both agents' decisions, completed work, evidence, active files, and open items into a new draft, and submit that draft with the newly captured revision.

If validation, locking, snapshot creation, or replacement fails, stop and report the error; the previous handoff remains authoritative. A pruning warning means the current handoff was updated successfully but more than 50 history files may remain temporarily.

## Finish a refresh

1. Read back `docs/project/HANDOFF.md`.
2. Confirm the eight required sections reflect the latest state.
3. Confirm evidence is inspectable and the next step is executable.
4. Continue project work only after the refreshed handoff is valid.
