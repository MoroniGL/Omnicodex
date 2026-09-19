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

## Install

Requires Codex 0.153.4 or a compatible release and Python 3.11 or newer:

```sh
python3 scripts/install.py
```

The installer creates a timestamped backup, preserves the base `config.toml`, refuses differing destinations by default, and installs all four namespaced profiles, seven custom roles, and the routing skill. After reviewing a known OmniCodex update, use `--replace-existing`; every replaced file is backed up first.

Start a new CLI session with one of the static profiles:

```sh
codex --strict-config -p omnicodex-economy
codex --strict-config -p omnicodex-balanced
codex --strict-config -p omnicodex-quality
codex --strict-config -p omnicodex-max
```

Profiles apply to the new CLI process. They do not change an existing Desktop/IDE conversation or the global model selection. A trusted project `.codex/config.toml` has higher precedence and can override a profile. Inspect the effective static model layers from the directory where you intend to start Codex:

```sh
python3 scripts/install.py --inspect-profile omnicodex-balanced --cwd "$PWD"
```

Auto remains a dynamic routing policy in the `omnicodex` skill. Ask the active agent to use **OmniCodex Auto**; it classifies and delegates each phase but does not pretend to mutate the already-running parent model.

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

## Status

**Experimental — all static profiles and custom roles smoke-tested locally on Codex 0.153.4.**

Persisted read-only tests verified Economy, Balanced, Quality, and Max control planes plus all seven native custom roles. Models and efforts were confirmed in runtime turn records, including Sol/Medium delegation to Luna, Terra, Sol, and Astra without explicit spawn overrides. Auto dynamically selected Luna for a narrow read-only phase while correctly preserving the parent model. This does not establish quality or quota savings.

See [local installation, runtime evidence, limitations, and rollback](docs/local-validation.md).

See [routing policy](docs/routing.md), [profiles](docs/profiles.md), [architecture](docs/architecture.md), and [roadmap](docs/roadmap.md).

## Inspiration

OmniCodex was inspired by community work around selective Codex orchestration, including Sol Advisor. Its focus is configurable quality/cost profiles, adaptive routing, context budgeting, escalation, and automatic de-escalation.

## License

MIT. See [LICENSE](LICENSE).
