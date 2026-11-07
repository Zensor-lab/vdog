# Agent instructions

Read `.agent/PROJECT.md`, the relevant specifications, assigned plan, and nearby
code before changing files. More specific directory instructions take precedence.
Use `docs/specs/` for requirements, `docs/plans/` for task plans, and `docs/tasks/`
for optional notes/reports. Create documents only when needed.

Keep `README.md` focused on the project: purpose, features, application setup,
usage, and project documentation. Maintain agent setup and operating guidance here.

## Template setup

1. Fill in [`.agent/PROJECT.md`](.agent/PROJECT.md) with your product, stack,
   working commands, and constraints.
2. Review [`opencode.jsonc`](opencode.jsonc). Replace the example provider endpoint,
   model, and limits, keeping model IDs synchronized across agent profiles.
3. Add your source, dependencies, tests, and CI. Add project documentation as needed.
4. Start `opencode` from the repository root and give `main/project-lead` a task.

## Layout

| Location | Purpose |
| --- | --- |
| `AGENTS.md` | Shared operating rules and delivery workflow |
| `.agent/PROJECT.md` | Project facts and commands to complete |
| `.opencode/agents/main/` | Primary project lead |
| `.opencode/agents/subagents/` | Specialist developers, reviewers, test engineer, reporter |
| `.opencode/skills/` | Worktree and Graphify workflows |
| `docs/specs/` | Accepted requirements, created when needed |
| `docs/plans/` | Task plans, created when needed |
| `docs/tasks/` | Optional task notes and reports, created when needed |

The documentation folders start empty. Put durable architecture decisions under
`docs/` when your project needs them; keep maintenance history out of the starter.

The included local model endpoint and limits are examples to adapt.

## Configuration validation and ESP32 setup

The configuration targets native OpenCode v2 and is validated with v2.2.6.
Check `opencode --version` before starting: this machine also has a v1 executable
on PATH. If needed, run `~/.opencode/bin/opencode2` (v2.2.6 here), or put the v2
installation's bin directory first on PATH in your own shell configuration. Use
the v2 executable for every command below; do not load this config with v1.

Follow the [official migration guide](https://opencode.ai/docs/migrate-v1/).
Providers use `providers`, `package`, and `settings`; the title agent's model is
set under `agents.title.model`. Profiles use ordered `permissions` rules with
`action`, `resource`, and `effect`. Later matching rules take precedence;
`shell` and `subagent` replace the v1 `bash` and `task` actions/tools.
`experimental.subagent_depth: 2` enables lead → developer → reviewer nesting.
The shared `external_directory` rule preserves prompts for access outside the
project. Keep permissions and delegation allowlists intact when editing profiles.

Use `opencode debug --help` to confirm diagnostics for the installed v2 release.
For v2.2.6, run `opencode debug config --standalone` and
`opencode debug agents --standalone`. Inspect configuration sources, all thirteen
project profiles, model IDs, modes, and ordered permission rules. The v1
`debug agent <id>` and `debug skill` commands are unavailable in v2.2.6; use the
v2 API for skill discovery: after starting a v2 session, run
`opencode api skill.list` against its initialized runtime and confirm `graphify`
and `using-git-worktrees` point to this repository. A one-shot standalone skill
request can return an empty list before initialization; that is insufficient
evidence that skills are missing. See the [API reference](https://opencode.ai/docs/api)
and `opencode api --help` for the installed release.
Use standalone diagnostics to avoid reloading an active background service.
Run `git diff --check` after edits. The starter has no application test suite;
missing application checks remain unverified. Discovery and configuration checks
do not verify model inference or live delegation.

Skills remain in `.opencode/skills/` and instructions remain in `AGENTS.md`.
This template defines no plugins, MCP servers, server API integrations,
or terminal UI settings to migrate. V1 plugin implementations need porting to
the v2 API if added later; a generated, ignored `.opencode/package.json` containing
`@opencode-ai/plugin` is local v1 tooling state, not a template dependency.
V2 terminal preferences belong in the user's global `~/.config/opencode/cli.json`.
Global configuration may contribute plugins, providers, and MCP servers; verify
those separately without treating them as template dependencies.

For ESP32 firmware, route work to `subagents/esp32-developer` and its matching
`subagents/esp32-reviewer`. They support existing PlatformIO projects using
Arduino or ESP-IDF. Fill in `.agent/PROJECT.md` with the exact chip/board,
framework/platform versions, supported `platformio.ini` environments, wiring,
and build/test commands. Identify authorized device operations and device/port
when hardware checks are needed. Build and host-test results are separate from
hardware verification. See the [PlatformIO test command reference](https://docs.platformio.org/en/latest/core/userguide/cmd_test.html)
for build-only and device test options. This template does not include firmware,
board defaults, or a PlatformIO installation.

## Shared rules

- Keep changes within scope; preserve public interfaces, architecture, security,
  dependencies, and framework choices unless the task authorizes a change.
- Preserve unrelated work. Never commit secrets, personal data, generated outputs,
  or unrelated lockfiles. Do not switch or pull the user's active branch.
- Add meaningful tests when behavior changes; add regression coverage for defects
  where practical. Run the project profile's checks and report unavailable checks.
- Update relevant project documentation and README when behavior, setup, interfaces,
  or structure changes. Avoid repeating shared rules across documents.
- Use native OpenCode `subagent` for delegation; never launch another CLI process or
  shell relay. Keep decisions about product scope and cross-stack contracts with
  the Orchestrator. Stop at the assigned task or milestone boundary.

## Roles and permissions

`main/project-lead` is the primary agent and Orchestrator. Definitions belong in
`.opencode/agents/main/` or `.opencode/agents/subagents/`, with explicit `mode` and
ordered `permissions` frontmatter. Keep profile model IDs synchronized with
`opencode.jsonc`; `experimental.subagent_depth: 2` supports
lead → developer → reviewer.

| Task area | Developer | Reviewer |
| --- | --- | --- |
| Python | `subagents/python-developer` | `subagents/python-reviewer` |
| React/TypeScript | `subagents/react-developer` | `subagents/react-reviewer` |
| Rust | `subagents/rust-developer` | `subagents/rust-reviewer` |
| Go | `subagents/go-developer` | `subagents/go-reviewer` |
| ESP32/PlatformIO (C/C++) | `subagents/esp32-developer` | `subagents/esp32-reviewer` |

Split mixed-stack work when independently reviewable. The lead may invoke all twelve
subagents; developers may invoke only their matching reviewer. Reviewers, test
engineer, and reporter may not delegate. Do not substitute a reviewer for a developer.

Reviewers never edit or commit and use shell only to inspect diffs, history, and
existing evidence. They must not run checks, install dependencies, contact external
services, or manage worktrees. Test engineer may run documented checks without
fix/update flags, dependency installation, or tracked-file changes. Reporter has
no shell and may edit only its assigned `docs/tasks/<task>-report.md`. Shell access
is not a read-only sandbox; these boundaries apply to shell as well as edit tools.

## Plan and implementation

Before implementation delegation, the Orchestrator prepares a self-contained plan
with goal, necessary background, exact scope/non-goals, constraints, affected
files/interfaces, ordered steps, required checks, observable acceptance criteria,
documentation updates, and expected handoff. Include only necessary context and
links so the plan is the developer's compact authoritative briefing.

The Orchestrator fetches `origin/main` and creates `opencode/<short-task-name>`
from the refreshed ref in its own planning worktree. If fetch or ref resolution
fails, report the blocker; do not use stale local `main`. Commit the plan under
`docs/plans/`, then detach the planning worktree to release the branch. Supply the
plan path, commit, branch, base revision, bounded scope, and expected evidence.
For a named branch update, fetch its remote counterpart when available, commit
the plan there, and release that branch; do not rebase, merge, or rewrite history
unless requested.

Developers follow `.opencode/skills/using-git-worktrees/SKILL.md`. Use the exact
supplied branch with its committed plan in an isolated worktree; do not create
another branch or worktree inside an existing worktree. Reviewers inspect the
same developer worktree. Read-only and documentation-only work needs no new
worktree. Do not remove worktrees or alter the user's branch without permission.

Developers implement every applicable criterion, run relevant checks, and delegate
review of non-trivial code changes to their matching reviewer from that worktree.
Evaluate every finding, fix confirmed defects, rerun checks, and request a fresh
review. Repeat until approval or a scope/design/unresolved-risk decision needs
the Orchestrator. Update the plan with completed work, review outcome, checks,
risks, and next steps. Create a local handoff commit without pushing; return the
exact branch, commit, worktree, and plan path with acceptance evidence.

## Verification and delivery

Every review checks acceptance criteria and any report claims against actual
source and evidence. Actionable findings include severity (`BLOCKER`, `HIGH`,
`MEDIUM`, `LOW`), file/line, failure condition, impact/violated requirement, fix,
and verification. Verdicts are `approve`, `approve with notes`, or `changes requested`.
Missing evidence is never a passed criterion.

The Orchestrator independently invokes `subagents/test-engineer` with the plan,
worktree, changed files, and command/review evidence. Outcomes are `VERIFIED`,
`REWORK REQUIRED`, or `UNVERIFIED`. For an optional report, assign
`subagents/reporter` an exact report path and source/command/review evidence;
a matching reviewer checks its claims. Developers own other documentation.
Return confirmed defects and missing evidence for rework before signoff.

The Orchestrator reviews the exact handoff commit in its own detached review
worktree under `.worktrees/`, compares it against the refreshed base, and runs
required checks. Never use the user's or developer's checkout for this final
handoff review. Return issues to the developer for fixes and repeated review.

Only the Orchestrator may push the accepted branch and create the PR using `gh`.
Commit/push only as needed for delivery; include change, checks, review outcome,
risks, and follow-up in the PR description. Report authentication, remote, or
branch-protection blockers rather than bypassing them. Developers never push or
perform PR actions. Do not merge without user direction.

## Optional graph context

For broad discovery, use `.opencode/skills/graphify/SKILL.md` when useful. Prefer
bounded queries of a relevant worktree-local graph, verify findings in current
source, and fall back to targeted `rg` for missing/stale graphs or poor results.
Required context and known files can be read directly. Role permissions still
apply; reporter consumes supplied excerpts without shell.

[Graphify](https://github.com/Graphify-Labs/graphify) provides a reusable local
code graph for focused repository discovery. With Python 3.10+ and uv:

```sh
uv tool install graphifyy
graphify --version
# From a populated implementation worktree:
graphify extract . --code-only --no-cluster
graphify query "How does authentication reach storage?" --budget 1500
```

The package is `graphifyy`; the executable is `graphify`. The included
[Graphify skill](.opencode/skills/graphify/SKILL.md) covers queries, refreshes,
fallbacks, and role boundaries. No upstream installer, plugin, or hook is required.
Code-only indexing runs locally without an API key and skips docs/media; read
specifications and plans directly. Generated `graphify-out/` directories are ignored.
The empty starter has no application code to index. Performance gains depend on
the project and are unmeasured here.
