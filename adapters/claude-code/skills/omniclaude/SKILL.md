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

Require operator opt-in (`OMNI_JEV=1`) and an explicit provider:
- `--provider vercel` uses `AI_GATEWAY_API_KEY` and `typesafe-ai/jev`.
- `--provider typesafe` uses `TYPESAFE_API_KEY` or legacy `JEV_API_KEY`
  and an explicitly selected account-visible model.

Never send a Gateway key to direct TypeSafe or switch providers automatically.
Use only minimized state approved for external transmission. Jev advises on route,
retry, review and completion; it cannot replace tests, permissions or human approval.

When this repository checkout is available, use `scripts/jev.py` and consult
`docs/jev-decision-layer.md`. `scripts/jev_shadow.py` previews synthetic cases
without network access; `--live` separately authorizes up to six paid requests.
The probe never routes real workers. Errors require retaining the native policy,
not repeated calls or automatic acceptance. A probability is not proof of completion.

A standalone plugin copy does not bundle the helper. Keep Jev disabled unless the
operator supplies an equivalent reviewed helper/tool. No new hooks, MCP registration,
keys, model changes or global configuration are installed by this skill.

## Acceptance

Every route preserves the original acceptance criteria. Record validation,
failures, unresolved risks, and which model/agent was requested. If runtime
metadata does not expose the actually used model, mark it unverified rather than
trusting a self-report.
