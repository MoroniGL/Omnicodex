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

## Status

**Experimental — Balanced routing smoke-tested locally on Codex 0.153.4.**

A persisted read-only test verified native role loading: Sol/Medium orchestrated Luna/Low and Terra/Medium, with the models and efforts confirmed in runtime turn records. The other five roles have only static validation. This does not establish quality or quota savings.

See [local installation, runtime evidence, limitations, and rollback](docs/local-validation.md).

See [routing policy](docs/routing.md), [profiles](docs/profiles.md), [architecture](docs/architecture.md), and [roadmap](docs/roadmap.md).

## Inspiration

OmniCodex was inspired by community work around selective Codex orchestration, including Sol Advisor. Its focus is configurable quality/cost profiles, adaptive routing, context budgeting, escalation, and automatic de-escalation.

## License

MIT. See [LICENSE](LICENSE).
