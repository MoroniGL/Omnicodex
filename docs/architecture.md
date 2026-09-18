# Architecture

OmniCodex separates **policy** from **runtime capability**.

## Policy layer

The policy answers:
- What kind of work is this?
- What is the minimum capable model tier?
- What reasoning effort is justified?
- Should the task be decomposed?
- Is escalation justified?
- Can we de-escalate now?

## Runtime layer

The runtime adapter must discover what the current Codex environment actually supports: custom agents, per-agent models, reasoning configuration, delegation, plugins, and model availability.

Unsupported capabilities must fail transparently.

## Proposed agents

- `researcher` — Luna / Low
- `explorer` — Terra / Low-Medium
- `implementer` — Terra / Medium
- `planner` — Sol / Medium
- `reviewer` — Sol / Medium
- `debugger` — Sol / High when justified
- `escalation` — Astra / minimum necessary

These are policy defaults, not assumptions that every Codex installation exposes these exact identifiers.

## Safety invariant

Cost optimization may change *who* performs work, but not the project's acceptance criteria. Required tests, security checks, correctness constraints and user requirements remain intact.
