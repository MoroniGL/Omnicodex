# OmniCodex

**Adaptive model routing and multi-agent orchestration for OpenAI Codex.**

> Use the right intelligence, at the right time.

**v0.1.0-alpha.1 — experimental public preview.** This version combines the
installer/profile work from [PR #2](https://github.com/MoroniGL/Omnicodex/pull/2)
and the optional context-efficiency work from
[PR #3](https://github.com/MoroniGL/Omnicodex/pull/3).
It is not a stable release or a demonstrated subscription-savings guarantee.

OmniCodex separates orchestration from bounded execution and routes work by
complexity, risk, and cost without lowering the task's acceptance criteria.

## Profiles

| Profile | Orchestrator target | Delegation policy |
|---|---|---|
| `economy` | Terra / Medium | Luna/Terra first; escalate consequential work |
| `balanced` | **Sol / Medium** | Luna/Terra execute bounded work; exceptional Astra |
| `quality` | Sol / High | Terra/Sol workers; Astra for justified hard blockers |
| `max` | **Astra / High** | Strong control plane with bounded work still delegated |
| `auto` | Existing parent stays unchanged | Skill selects workers by phase; not a fifth static profile |

Balanced is the recommended starting profile. The name `max` does not set the
reasoning effort to `max`: the shipped Max profile requests `high`.
Model availability and configuration support depend on the installed Codex and account.

## Install or update

Use a compatible Codex CLI (the maintainer's smoke tests used **0.153.4**) and
**Python 3.11+**. Check `python3 --version`; some Macs have an older default Python.
Use an already installed compatible interpreter where necessary.

From a checkout of this version:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/install.py
```

The installer installs four namespaced profiles, seven custom agents, and both
routing-skill files, including `references/efficiency.md`. It checks conflicts
before writing, creates a private backup, records asset hashes, and preserves the
base `config.toml`. After reviewing an update, explicitly allow replacement with:

```sh
python3 scripts/install.py --replace-existing
```

This installs OmniCodex assets only. It does not install or register optional MCP
servers, change hooks, or switch the model of an already-running conversation.
Review [installation and rollback](docs/local-validation.md) before replacing files.

Start a **new CLI session**:

```sh
codex --strict-config -p omnicodex-economy
codex --strict-config -p omnicodex-balanced
codex --strict-config -p omnicodex-quality
codex --strict-config -p omnicodex-max
```

Profiles do not change an existing Desktop/IDE task. To inspect candidate static
model layers from the intended working directory:

```sh
python3 scripts/install.py --inspect-profile omnicodex-balanced --cwd "$PWD"
```

That inspection is not execution telemetry: it does not establish project trust,
CLI overrides, Desktop selection, or the server's actually served model.
Ask the active agent to use **OmniCodex Auto** for phase-specific worker selection;
Auto does not silently change the parent's model.

## Context & Token Efficiency

The routing skill can use **already approved and available** Context Mode or
codebase-memory-mcp tools. It requires capability checks, source/index freshness,
retrievable raw evidence, and compact handoffs that preserve failures and risks.
Without those providers it uses native tools. These are skill-guided policies,
not an automatic command interceptor or an MCP transport implementation.

```sh
python3 scripts/efficiency.py doctor
python3 scripts/efficiency.py plan --profile balanced --task structural
```

`doctor` is a read-only baseline diagnostic. `plan` is an advisory dry run using
supplied evidence. Neither proves live MCP access or changes a model.
Read the [efficiency architecture](docs/context-token-efficiency.md) and
[benchmark protocol](docs/efficiency-benchmark.md).

## Validation and limitations

- The maintainer reported 26 passing efficiency tests on macOS with Python 3.12.14.
- A persisted Balanced session recorded Sol/Medium in the parent and Luna/Low
  and Terra/Medium in real sequential children. These are **local Codex records**,
  not an independent attestation of the provider-served model.
- PR #2 contains an earlier, broader maintainer-reported smoke test of all static
  profiles and seven roles, including Max. It also discloses a planner sentinel
  output mismatch. Do not treat routing metadata as proof of task quality.
- The combined source is checked by automated Python tests, including installation
  of the efficiency reference. CI does not make paid model calls.
- Context Mode and codebase-memory-mcp were not configured in the latest Mac test.
  Live integration, quality comparisons, token/allowance savings, and cross-client
  compatibility remain unverified. No new Max/Astra probe is part of this release preparation.
- RTK automatic rewriting, persistent project memory, and automatic MCP setup are
  not implemented. Claude Code cannot use these Codex model/profile files as-is.

See the [release notes](docs/releases/v0.1.0-alpha.1.md), [routing policy](docs/routing.md),
[profiles](docs/profiles.md), [architecture](docs/architecture.md), and [roadmap](docs/roadmap.md).

## Principles

Use the least expensive capable worker, not the weakest model regardless of risk.
Keep planning and acceptance with the chosen orchestrator. Avoid unnecessary
subagents, broad context dumps, repeated failed work, and stacked output compression.
Never weaken permissions, security, tests, or acceptance criteria to save usage.
Never claim model switching from configuration or a worker's self-report alone.

## Inspiration and license

Inspired by selective Codex orchestration, including Sol Advisor. Optional upstream
tools remain separate projects; their benchmark claims are not OmniCodex results.
MIT; see [LICENSE](LICENSE).
