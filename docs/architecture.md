# Architecture

OmniCodex separates **policy**, **control plane**, **execution plane**, and **runtime capability**.

## Policy layer

The policy answers:
- Which profile is active?
- What kind of work is this?
- What quality/risk target applies?
- Which model should orchestrate?
- What is the minimum capable worker?
- What reasoning effort is justified?
- Should the task be decomposed?
- Is escalation justified?
- Can we de-escalate now?

## Control plane

The orchestrator owns decomposition, delegation, dependency tracking, acceptance, risk assessment, and escalation decisions.

Profile defaults:
- `economy`: Terra-first control plane; call Sol for consequential reasoning.
- `balanced`: Sol / Medium.
- `quality`: Sol / High.
- `max`: Astra.
- `auto`: choose dynamically from task complexity, blast radius, ambiguity and failure history.

The control plane should not perform bulk mechanical work merely because it is powerful.

## Execution plane

Proposed worker roles:
- `researcher` — Luna / Low
- `explorer` — Terra / Low-Medium
- `implementer` — Terra / Medium
- `planner` — Sol / Medium
- `reviewer` — Sol / Medium-High
- `debugger` — Sol / High when justified
- `escalation` — Astra / minimum necessary

## Runtime layer

The runtime adapter must discover what the current Codex environment actually supports: custom agents, per-agent models, reasoning configuration, delegation, plugins, and model availability.

Unsupported capabilities must fail transparently. These names are policy targets, not assumptions that every installation exposes identical identifiers.

## Safety invariant

Cost optimization may change *who* performs work, but not acceptance criteria. Required tests, security checks, correctness constraints and user requirements remain intact.
