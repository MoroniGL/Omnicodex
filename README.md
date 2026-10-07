# OmniCodex

**Adaptive model routing and multi-agent orchestration for OpenAI Codex.**

> Use the right intelligence, at the right time.

**v0.1.0-alpha.2 — experimental public preview.** This version adds persistent
OmniCodex defaults, same-session profile controls, and optional Gemini Direct
context offload with source-linked EvidencePacks. It remains an alpha release,
not a subscription-savings or billing guarantee.

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

Use a compatible Codex CLI (the maintainer's Windows acceptance used **0.160.0**)
and **Python 3.11+**.

### Recommended Codex-assisted install

In Codex Desktop or CLI, give Codex the repository URL and ask it to install
OmniCodex. The intended flow is preview-first:

```sh
python3 scripts/setup.py
python3 scripts/setup.py --apply
```

The first command writes nothing. The second installs the four namespaced
profiles, seven custom agents, the routing skill, Gemini Direct offload runtime,
persistent Auto defaults, and the UserPromptSubmit session-control hook. Existing
unrelated config and hooks are preserved; changed OmniCodex-owned files require
`--replace-existing` after review. Codex may ask once to trust the local hook.
Restart a cached Desktop/IDE session after installation so it reloads
`CODEX_HOME`, guidance, and hooks.

For a fixed saved profile at install time:

```sh
python3 scripts/setup.py --profile balanced --apply
```

`scripts/install.py` remains available as the conservative **asset-only** entry
point; it intentionally does not activate persistent defaults or the session hook.
Review [installation and rollback](docs/local-validation.md) before replacing files.

Native OmniCodex installs and works without a Gemini key. There is no WSL,
Ubuntu, Docker, FreeLLMAPI Desktop, or second Codex installation requirement.
Gemini Direct offload is optional; missing configuration reports `NOT CONFIGURED`
and leaves native routing available.

Start a **new CLI session**:

```sh
codex --strict-config -p omnicodex-economy
codex --strict-config -p omnicodex-balanced
codex --strict-config -p omnicodex-quality
codex --strict-config -p omnicodex-max
```

Profiles do not silently change a running parent model. Inside an installed
Codex conversation, these ordinary messages control OmniCodex policy at prompt
boundaries:

```text
omni status
omni balanced
omni quality
omni reset
omni save quality
```

Use Codex's native `/model` selector when you want the parent model itself to
change in the same thread. To inspect candidate static model layers from the
intended working directory:

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

### Optional Gemini Direct context worker

For an explicitly approved public or private workspace, OmniCodex can send an
immutable bounded capture to Gemini Direct over HTTPS and receive a source-linked
EvidencePack. The premium parent still owns planning, implementation,
consequential decisions, evidence inspection, and acceptance.

This is not quota fallback. Small tasks stay native, sensitive content is
rejected, and the parent is never switched. Setup is environment only:

```sh
export GEMINI_API_KEY='set-locally-never-commit'
# Optional; defaults to gemini-3.5-flash-lite
export OMNICODEX_GEMINI_MODEL='gemini-3.5-flash-lite'
python3 "$CODEX_HOME/omnicodex/scripts/free_context_worker.py" doctor
```

`doctor` is offline: its JSON reports `native_status: "READY"` and
`free_context_offload: "READY"` or `"NOT CONFIGURED"`, plus provider/model
configuration. It does not probe connectivity or verify a served model. A
configured key is local configuration only. See the
[architecture and privacy contract](docs/context-token-efficiency.md) and the
[controlled acceptance procedure](docs/local-validation.md).

`omni status` includes the same offline Gemini Direct configuration distinction.
It does not claim the optional worker is connected or live.

`python scripts/validate_gemini.py` is the explicit live acceptance command. It
makes two requests only when local status is READY: a small connectivity probe
that leaves ordinary small work native, and a roughly 45k-token synthetic gate
case. `READY` remains local configuration only. The alpha.2 maintainer validation
did run successfully on Windows, but each installation still needs to validate
its own key, account, and model access; no billing or free-tier claim is implied.

## Validation and limitations

- GitHub Actions validates the full Python suite, compiles the scripts, and runs
  whitespace checks without making Gemini calls.
- Windows acceptance on Codex CLI 0.160.0 exercised persistent defaults,
  same-session profile control, installation, and Gemini Direct validation.
- A live Gemini Direct synthetic 180 KB case using `gemini-3.5-flash-lite`
  passed EvidencePack validation and reported roughly **99.6% estimated compact
  handoff reduction**. That is an estimated context reduction, not verified
  billing, free-tier eligibility, or subscription savings.
- A persisted Balanced session recorded Sol/Medium in the parent and Luna/Low
  and Terra/Medium in real sequential children. These are **local Codex records**,
  not an independent attestation of the provider-served model.
- Context Mode and codebase-memory-mcp were not configured in the latest Mac test.
  Live integration, quality comparisons, token/allowance savings, and cross-client
  compatibility remain unverified. No new Max/Astra probe is part of this release preparation.
- The Gemini Direct worker has comprehensive offline coverage. A real provider
  test must only be claimed when a configured key and connectivity validation ran;
  estimated context reduction is not verified billing or subscription savings.
- RTK automatic rewriting, persistent project memory, and automatic MCP setup are
  not implemented. Claude Code cannot use these Codex model/profile files as-is.

See the [release notes](docs/releases/v0.1.0-alpha.2.md), [routing policy](docs/routing.md),
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
