# OmniCodex

**Cost-aware model routing and multi-agent orchestration for OpenAI Codex.**

> Use the right model for the right task.

OmniCodex is an experimental orchestration layer for Codex that routes work by **complexity, risk, and cost** instead of using the strongest model for every step.

## Core idea

```
Luna  -> high-volume bounded work
Terra -> exploration and implementation
Sol   -> planning, review, hard reasoning
Astra -> exceptional escalation only
```

The router also **de-escalates** after difficult work is complete. A task that needs Sol for architecture does not need Sol to run routine tests.

## Principles

- Cheapest capable model, not cheapest model at any cost.
- Decompose large tasks before routing.
- Escalate only for a concrete technical reason.
- De-escalate as soon as the expensive phase is complete.
- Keep expensive-model context narrow and relevant.
- Prefer bounded delegation over redundant parallel agents.
- Quality gates remain mandatory: tests, review, security and correctness are never skipped to save usage.

## Default roles

| Role | Default tier | Purpose |
|---|---|---|
| Researcher | Luna / Low | Search, references, logs, bounded extraction |
| Explorer | Terra / Low-Medium | Codebase exploration and mapping |
| Implementer | Terra / Medium | Normal implementation and refactoring |
| Planner | Sol / Medium | Architecture and cross-module planning |
| Reviewer | Sol / Medium | High-value review and risk analysis |
| Debugger | Sol / High | Difficult debugging |
| Escalation | Astra / minimum necessary | Exceptional unresolved work |

Model names and reasoning levels depend on what your Codex environment exposes. OmniCodex must not pretend a route exists when the runtime does not support it.

## Routing lifecycle

```
request
  |
decompose
  |
route cheapest capable worker
  |
execute + verify
  |
blocked? ---- yes ---> diagnose ---> escalate if justified
  |                                  |
  no                                 v
  |                              expensive phase
  v                                  |
de-escalate <-------------------------+
  |
finish
```

See [routing policy](docs/routing.md) and [architecture](docs/architecture.md).

## Status

**v0.1.0 — initial architecture.**

The first milestone is to validate Codex's currently supported custom-agent/plugin configuration and turn these policies into an installable package without relying on undocumented behavior.

## Inspiration

OmniCodex was inspired by community work around selective Codex orchestration, including Sol Advisor. OmniCodex focuses specifically on aggressive **cost-aware routing plus automatic de-escalation**.

## License

MIT. See [LICENSE](LICENSE).
