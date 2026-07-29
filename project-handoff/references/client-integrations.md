# Client integrations

Use `scripts/install_client_hook.py` to install, inspect, or remove the
downloaded Skill's client hooks. The installer changes only the selected
client configuration. Pass explicit paths when automating or testing.

```bash
python3 project-handoff/scripts/install_client_hook.py install \
  --client claude --scope user

python3 project-handoff/scripts/install_client_hook.py doctor \
  --client claude --scope user

python3 project-handoff/scripts/install_client_hook.py uninstall \
  --client claude --scope user
```

All installers preserve unrelated settings, reject malformed configuration,
write atomically, and are safe to run repeatedly. `doctor` exits with status
zero only when the selected integration is current.

## Support matrix

| Client | Event | User scope | Project scope | Other scope | Platforms |
| --- | --- | --- | --- | --- | --- |
| Claude Code | `PreCompact` | `~/.claude/settings.json` | `.claude/settings.json` | — | macOS, Linux, Windows |
| Gemini CLI | `PreCompress` | `~/.gemini/settings.json` | `.gemini/settings.json` | — | macOS, Linux, Windows |
| GitHub Copilot | `preCompact` | `~/.copilot/hooks/project-handoff.json` | `.github/hooks/project-handoff.json` | Cloud repository bootstrap | macOS, Linux, Windows; Cloud is Linux |
| Cline | prepared `PreCompact`; lifecycle fallbacks | `~/.cline/hooks/` | `.cline/hooks/` and `.clinerules/hooks/` | editor: `~/Documents/Cline/Hooks/` | macOS and Linux; upstream file hooks do not support Windows |
| Qwen Code | `PreCompact` | `~/.qwen/settings.json` | `.qwen/settings.json` | — | macOS, Linux, Windows |

## Claude Code

Claude sends snake_case JSON with `hook_event_name: "PreCompact"`, `cwd`,
`session_id`, `trigger`, and optional custom instructions. The generated hook
uses Claude's exec form, so paths containing spaces do not pass through a
shell.

```bash
# All projects for the current user
python3 project-handoff/scripts/install_client_hook.py install \
  --client claude --scope user

# One project; run from that project or pass --project-root
python3 /path/to/project-handoff/scripts/install_client_hook.py install \
  --client claude --scope project --project-root /path/to/project
```

The adapter remains silent on stdout and returns a non-blocking success status.
Errors are written to stderr and mean that no recovery evidence was captured.

Official reference:
[Claude Code hooks](https://code.claude.com/docs/en/hooks).

## Gemini CLI

Gemini names the event `PreCompress`, not `PreCompact`. It sends snake_case
JSON containing `cwd`, `session_id`, `timestamp`, and a `manual` or `auto`
trigger. The event is advisory and asynchronous; it cannot block compression.

```bash
python3 project-handoff/scripts/install_client_hook.py install \
  --client gemini --scope user

python3 /path/to/project-handoff/scripts/install_client_hook.py install \
  --client gemini --scope project --project-root /path/to/project
```

The adapter prints exactly one valid JSON object (`{}`) to stdout. Never print
plain log text to Gemini stdout.

Official reference:
[Gemini CLI hooks](https://geminicli.com/docs/hooks/reference/).

## GitHub Copilot

Copilot supports two payload formats:

- `preCompact`: camelCase fields such as `sessionId` and `transcriptPath`;
- `PreCompact`: VS Code-compatible snake_case fields such as `session_id`.

The adapter accepts both. Local CLI installation can be user-level or
repository-level:

```bash
python3 project-handoff/scripts/install_client_hook.py install \
  --client copilot --scope user

python3 /path/to/project-handoff/scripts/install_client_hook.py install \
  --client copilot --scope project --project-root /path/to/project
```

Cloud Coding Agent cannot read a user's local Skill directory. Cloud scope
therefore vendors the three-file checkpoint runtime and an ownership manifest
under `.github/hooks/project-handoff/`:

```bash
python3 /path/to/project-handoff/scripts/install_client_hook.py install \
  --client copilot --scope cloud --project-root /path/to/project
```

Commit `.github/hooks/project-handoff.json` and the generated runtime directory
to the target repository. Cloud mode uses repository-relative paths and does
not include paths from the installer machine.

Official reference:
[GitHub Copilot hooks](https://docs.github.com/en/copilot/reference/hooks-reference).

## Cline

Cline needs an explicit compatibility warning. Its current official repository
defines a `PreCompact` payload and includes templates, but the file-hook
documentation marks the event as **coming soon** and the current SDK examples
state that it is **not wired**. Therefore project-handoff does not claim native
pre-compaction capture for current Cline releases.

The installer creates a prepared `PreCompact` wrapper plus currently wired
fallback wrappers for:

- `TaskStart`;
- `TaskResume`;
- `TaskComplete`;
- `SessionShutdown`.

These fallbacks capture the canonical handoff at lifecycle boundaries and
return context reminding Cline to invoke project-handoff and read
`docs/project/HANDOFF.md`. They reduce state loss but are not equivalent to a
true pre-compaction event.

```bash
# Cline CLI user hooks
python3 project-handoff/scripts/install_client_hook.py install \
  --client cline --scope user

# Cline editor global hooks
python3 project-handoff/scripts/install_client_hook.py install \
  --client cline --scope editor

# Both current CLI and legacy editor project locations
python3 /path/to/project-handoff/scripts/install_client_hook.py install \
  --client cline --scope project --project-root /path/to/project
```

An unrelated existing hook is preserved and stops installation. Use `--force`
only after reviewing that exact file. Cline's current file-hook documentation
states that Windows is not supported; the installer reports this instead of
generating a launcher that cannot run.

Official source evidence:
[Cline hook README](https://github.com/cline/cline/blob/main/.clinerules/hooks/README.md)
and
[Cline SDK hook examples](https://github.com/cline/cline/blob/main/sdk/examples/hooks/README.md).

## Qwen Code

Qwen sends snake_case `PreCompact` JSON with `cwd`, `session_id`, `timestamp`,
`trigger`, and `custom_instructions`. Its command hook supports an explicit
`bash` or `powershell` shell; the installer selects the current platform.

```bash
python3 project-handoff/scripts/install_client_hook.py install \
  --client qwen --scope user

python3 /path/to/project-handoff/scripts/install_client_hook.py install \
  --client qwen --scope project --project-root /path/to/project
```

The adapter returns one valid JSON object (`{}`) and never blocks compaction.

Official reference:
[Qwen Code hooks](https://qwenlm.github.io/qwen-code-docs/en/users/features/hooks/).

## Overrides for automation

The public installer accepts:

- `--home`: simulate or select the user home directory;
- `--project-root`: select the target project;
- `--skill-root`: select the downloaded Skill;
- `--python-executable`: select Python explicitly;
- `--platform`: deterministic platform generation for testing;
- `--config-file`: override a Claude, Gemini, or Qwen settings file;
- `--hooks-dir`: override a Cline hook directory.

These options are why the full suite can test every installer inside temporary
directories without registering hooks on the maintainer's computer.

## Recovery contract

Native adapters and Cline lifecycle fallbacks copy the exact canonical handoff
to `docs/project/handoff-emergency/` and then write
`docs/project/.handoff-precompact-pending.json`. The hook does not read the
conversation transcript and does not semantically rewrite `HANDOFF.md`.

On the next project turn:

1. invoke project-handoff;
2. read `docs/project/HANDOFF.md` completely;
3. read the pending marker and referenced emergency snapshot;
4. reconcile only missing state through the revision-aware updater;
5. remove or archive the marker after successful recovery.

The canonical handoff remains authoritative when it is demonstrably newer.
