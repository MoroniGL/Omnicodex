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

## Gemini Direct token offload

Large, explicitly approved read-only scopes can follow a separate bounded path:

```text
deterministic approved scope capture -> Gemini Direct HTTP -> compact EvidencePack
                                      -> premium parent verifies cited evidence
```

The capture is immutable and limited to approved repo-relative paths. Gemini
receives that captured scope only after the externalization gate accepts the
classification and request. It returns a compact EvidencePack; the parent still
opens cited ranges, runs the required validation, and makes the acceptance
decision. The worker does not invoke a nested Codex process and needs no WSL,
Ubuntu, Docker, or OS sandbox.

The premium parent must narrow scope using metadata before offload, without
ingesting the full heavy context. Only local deterministic code reads captured
files; the API model receives bytes and has no filesystem, shell, tools, MCP,
apps, or subagent capabilities. Every pack remains an untrusted source locator
until the premium parent verifies exact cited ranges. Workspace hashes cover the
captured files and approved directory membership, without reading other files.

`GEMINI_API_KEY` is the only credential input. `OMNICODEX_GEMINI_MODEL` is
optional and defaults to `gemini-3.5-flash-lite`. Local configuration status is
not connectivity or billing evidence. The optional future FreeLLMAPI adapter is
not an installation dependency.
