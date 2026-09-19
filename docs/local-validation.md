# Local installation and runtime validation

Validated with Codex CLI **0.153.4** on macOS. This is a routing smoke test, not a quality or quota-savings benchmark. See Issue #1.

## Installation layout

| Repository source | Personal destination |
|---|---|
| `agents/*.toml` | `$CODEX_HOME/agents/*.toml` (default `~/.codex/agents/`) |
| `profiles/*.config.toml` | `$CODEX_HOME/omnicodex-<profile>.config.toml` |
| `skills/omnicodex/SKILL.md` | `~/.agents/skills/omnicodex/SKILL.md` |

Run `python3 scripts/install.py`. Before writing, the installer backs up the existing `config.toml` and any destination files to a private, timestamped directory. It refuses conflicting destinations instead of overwriting them unless a reviewed update explicitly uses `--replace-existing`. It records hashes and whether each destination already existed. The seven agent definitions use the supported standalone schema (`name`, `description`, `developer_instructions`, `model`, `model_reasoning_effort`). The routing skill needs YAML `name` and `description` frontmatter to be discoverable.

Keep the existing `config.toml` unchanged. The namespaced profile avoids replacing an existing `balanced` profile. Select it for a new CLI session:

```sh
codex --strict-config -p omnicodex-balanced
```

The profile invokes the installed routing skill. Its primary model is `gpt-5.6-sol` / `medium`, with `gpt-5.6-terra` / `medium` as the fallback worker. Native named roles select their own explicit model and effort. Astra is reserved for exceptional escalation in Balanced.

Profiles do not reconfigure already-running sessions. Desktop model selections can override file defaults. This validation establishes CLI behavior; it does not establish that Desktop automatically selects this named profile.

Official Codex precedence is CLI flags, trusted project `.codex/config.toml`, selected profile, user `config.toml`, managed/system configuration, then built-in defaults. Use `python3 scripts/install.py --inspect-profile omnicodex-balanced --cwd "$PWD"` to report the user/profile/project model layers. CLI `-m` and `-c` remain higher priority and cannot be inferred by that static check.

Auto is intentionally not installed as a fifth static profile. It is the dynamic policy in the routing skill: classify each phase, select a native role, verify runtime metadata when exposed, and de-escalate after the phase. It cannot mutate the model of an already-running parent thread.

## Controlled runtime test

Start a persisted, read-only run with the selected profile. Ask it to create exactly two children using native `agent_type`, `fork_turns="none"`, and no explicit model/reasoning spawn arguments:

- `luna-researcher`: extract IDs and a currency from a small JSON fixture.
- `terra-implementer`: independently compute its count, signed sum, and largest item.

Wait for completion. Compare the child relationship and stored model/effort in the local runtime state with each rollout's `turn_context.payload.model` and `turn_context.payload.effort`. Also inspect the actual spawn arguments. A requested setting or an agent's self-report is not runtime proof.

The complete 0.153.4 test observed:

| Role | Actual runtime model | Actual effort | Result |
|---|---|---|---|
| Economy primary | `gpt-5.6-terra` | `medium` | Completed |
| Balanced primary | `gpt-5.6-sol` | `medium` | Completed |
| Quality primary | `gpt-5.6-sol` | `high` | Completed |
| Max primary | `gpt-6-astra` | `high` | Completed |
| `luna-researcher` | `gpt-5.6-luna` | `low` | Completed |
| `terra-explorer` | `gpt-5.6-terra` | `low` | Completed |
| `terra-implementer` | `gpt-5.6-terra` | `medium` | Completed |
| `sol-planner` | `gpt-5.6-sol` | `medium` | Completed |
| `sol-reviewer` | `gpt-5.6-sol` | `medium` | Completed |
| `sol-debugger` | `gpt-5.6-sol` | `high` | Completed |
| `astra-expert` | `gpt-6-astra` | `high` | Completed |

The full role test created exactly seven child threads through native `agent_type`. Spawn calls did not include model or reasoning overrides. Persisted thread metadata and every `turn_context` matched the selected role file, including the minimal explicit Astra escalation probe. Native role loading worked; no explicit-routing fallback was needed. Six sentinel tasks matched exactly. The planner returned the numeric fixture sequence instead of the requested fixed planning sentinel, but its runtime model/effort and completion were verified; this is a task-output mismatch rather than a routing mismatch.

An Auto probe used a Balanced parent, explicitly disclosed that it could not mutate that parent, classified a narrow read-only task, and selected `luna-researcher`. The child ran as Luna/Low and returned the expected result. No `omnicodex-auto.config.toml` was created.

Runtime state and rollout formats are internal and may change. The installed app-server can generate its own protocol schema. In this version, `app-server` rejects `--profile`; validate the named profile through `codex exec --strict-config -p omnicodex-balanced` instead. The app-server `skills/list` endpoint can independently confirm skill discovery.

## Checks and rollback

```sh
python3.12 -m unittest discover -s tests -v
git diff --check
```

CI validates declarative assets and checks whitespace against the changed commit range. No production application, build pipeline, network service, browser UI, or production deployment is added. Paid runtime smoke tests remain local and explicit. CI success alone does not prove model routing.

For rollback, remove only files introduced by this installation whose current hashes still match the install manifest. Restore backed-up files only if they were actually replaced. Preserve subsequent user edits and unrelated configuration. Since this procedure leaves the base `config.toml` unchanged, restoring it is unnecessary unless it was separately changed.

Official references: [Custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents) and [configuration samples](https://developers.openai.com/codex/config-sample).
