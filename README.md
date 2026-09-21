# OmniCodex

**Adaptive model routing and multi-agent orchestration for OpenAI Codex.**

> Use the right intelligence, at the right time.

OmniCodex is an experimental orchestration layer for Codex that routes work by **complexity, risk, quality target, and cost**. Instead of forcing one strategy on every user, OmniCodex provides selectable operating profiles.

## Profiles

| Profile | Control plane | Workers | Astra policy | Goal |
|---|---|---|---|---|
| `economy` | Terra, with Sol when needed | Luna + Terra | Emergency only | Maximize quota life |
| `balanced` | **Sol / Medium** | Luna + Terra | Exceptional escalation | Strong quality/usage balance |
| `quality` | **Sol / High** | Terra + Sol | Hard bugs / critical decisions | Favor quality |
| `max` | **Astra** | Terra + Sol + Astra | Liberal | Maximum capability |
| `auto` | Adaptive | Adaptive | Adaptive | Select profile from task risk/complexity |

**Proposed default: `balanced`.**

Even in `max`, the orchestrator should delegate deterministic work when doing so does not reduce quality. Astra does not need to run routine lint or mechanical searches merely because Astra is the control plane.

## Core model roles

```
Luna  -> high-volume bounded work
Terra -> exploration and implementation
Sol   -> orchestration, planning, review, hard reasoning
Astra -> maximum-capability orchestration or exceptional escalation
```

Routing is **phase-specific**. OmniCodex can escalate for a difficult decision and then de-escalate for implementation or verification.

## Control plane vs execution plane

The orchestrator should spend expensive intelligence on decomposition, delegation, acceptance, risk and escalation decisions. Workers perform the bulk of bounded execution.

A typical `balanced` task:

```
User request
    |
Sol / Medium orchestrator
    |
    +--> Luna / Low: bounded search and verification
    +--> Terra / Medium: exploration and implementation
    +--> Sol / High: difficult specialist work when justified
    +--> Astra: exceptional escalation
    |
Sol / Medium: acceptance
```

## Principles

- Preserve required quality; optimize waste, not correctness.
- Strong orchestration can coexist with cheaper execution.
- Decompose large tasks before routing.
- Escalate only for a concrete technical reason.
- De-escalate as soon as the expensive phase is complete.
- Keep expensive-model context narrow and relevant.
- Prefer bounded delegation over redundant parallel agents.
- Tests, review, security and correctness are never skipped to save usage.
- Never pretend the runtime switched models when it did not.

## Context & Token Efficiency

Optional, skill-guided adapters now complement model routing:

- **Context Mode:** bounded retrieval of large output, with raw evidence preserved.
- **codebase-memory-mcp:** structural discovery with worktree/index freshness and source checks.
- **Compact handoffs:** concise evidence reports without dropping failures or quality gates.

Native tools remain the fallback. No dependency is installed automatically, no
hooks are enabled, and no Codex/Claude configuration is overwritten. RTK rewriting
and persistent memory are follow-on work, not active features in this increment.

Read the [architecture and usage guide](docs/context-token-efficiency.md) and
[benchmark protocol](docs/efficiency-benchmark.md). The manifest is OmniCodex data,
not client configuration. With Python 3.11+ and no third-party Python dependencies:

```sh
python3 scripts/efficiency.py doctor
python3 scripts/efficiency.py plan --profile balanced --task structural
python3 -m unittest discover -s tests -v
```

Diagnostics check local binary presence and supplied capability evidence only.
Plans are **advisory dry runs**, not live MCP probes, model switches, or hook tests.
See the guide for explicit opt-in and a clearly labeled synthetic inventory example.

## Status

**v0.1.0 — experimental templates, routing skill, and offline efficiency tooling.**

The existing model/profile templates still require validation against the user's
actual Codex build and account. This increment does not repair or validate profile
activation and cross-model delegation. No live Codex/Claude integration test,
percentage saving, or extension of subscription allowance is claimed.

See [routing policy](docs/routing.md), [profiles](docs/profiles.md), [architecture](docs/architecture.md), and [roadmap](docs/roadmap.md).

## Inspiration

OmniCodex was inspired by community work around selective Codex orchestration, including Sol Advisor. Its focus is configurable quality/cost profiles, adaptive routing, context budgeting, escalation, and automatic de-escalation.

## License

MIT. See [LICENSE](LICENSE).
