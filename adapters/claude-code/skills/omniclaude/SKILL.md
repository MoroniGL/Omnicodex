---
name: omniclaude
description: Route Claude Code work through focused Haiku, Sonnet, and Opus subagents while preserving quality and controlling context.
---

# OmniClaude routing

Keep the active parent model unchanged. This skill routes bounded phases to plugin
subagents; it does not pretend to mutate the model of the running conversation.

## Profiles

- **Economy**: use the parent directly for tiny work; delegate narrow research to
  `omniclaude:researcher` and normal implementation to `omniclaude:implementer`.
  Test a Haiku parent separately before recommending it as an Economy default.
- **Balanced**: recommended parent is Sonnet. Research goes to Haiku, implementation
  to Sonnet, and consequential independent review/debugging to Opus only when justified.
- **Quality**: recommended parent is Opus. Still delegate high-volume bounded work
  when doing so does not reduce acceptance quality.
- **Max**: Opus remains the control plane; spend additional context/review only for
  concrete risk. Max does not mean spawning Opus workers for every command.
- **Auto**: classify each phase by ambiguity, reversibility, blast radius,
  security/data-integrity risk, and verification cost, then choose a worker.

Do not create a subagent for each shell command. Use subagents when isolation
prevents search/log/file volume from polluting the parent context.

## Optional Jev

If the operator explicitly enabled Jev with `OMNI_JEV=1` and supplied
`JEV_API_KEY`, Jev may be consulted for narrow typed decisions: route selection,
retry strategy, review gating, or completion checks. It is not a coding model and
cannot replace Claude, tests, permissions, or human approval.

When this repository checkout is available, use the official helper at
`scripts/jev.py`. For a standalone plugin copy, Jev remains disabled unless the
operator supplies an equivalent reviewed helper/tool. Never transmit secrets or
large source dumps merely to save tokens.

## Acceptance

Every route preserves the original acceptance criteria. Record validation,
failures, unresolved risks, and which model/agent was requested. If runtime
metadata does not expose the actually used model, mark it unverified rather than
trusting a self-report.
