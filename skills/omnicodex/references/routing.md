# OmniCodex routing details

Load this reference only when profile, worker, escalation, or delegation specifics
matter. The root skill intentionally stays small.

## Runtime evidence

Configured model names are targets, not proof of what a provider served. Prefer
runtime metadata when available and distinguish requested configuration, local
execution records, and provider responses. Missing metadata means unverified.

Use native custom-role/subagent selection when the current Codex runtime exposes
it. Do not invent tool arguments, bypass approvals, or launch an independent CLI
while claiming it was a child agent.

## Workflow boundaries

- Keep planning, dependency tracking, consequential decisions, and acceptance with
  the active parent.
- Delegate bounded work with explicit scope, constraints, acceptance criteria, and
  existing evidence instead of full conversation history.
- Parallelize only independent work. Ordered work or changes to the same mutable
  resource stay serialized.
- Escalate for a concrete capability barrier, unresolved ambiguity, or material
  risk, not merely elapsed time.
- Diagnose failures before retrying; do not repeat an identical failed action
  without a changed hypothesis or environment.
- Completion means the requested outcome is implemented when applicable, relevant
  validation is run, results are inspected, and material failures are surfaced.

## Installed worker targets

- luna-researcher: gpt-5.6-luna / low — bounded search and extraction.
- terra-explorer: gpt-5.6-terra / low — focused code mapping.
- terra-implementer: gpt-5.6-terra / medium — bounded implementation.
- sol-planner and sol-reviewer: gpt-5.6-sol / medium — consequential work.
- sol-debugger: gpt-5.6-sol / high — difficult debugging.
- astra-expert: gpt-6-astra / high — exceptional unresolved work.

These are currently shipped targets. Do not silently rewrite them because a newer
model exists. Verify runtime/account support and compare representative tasks first.

## Profiles

Economy uses Terra Medium control with Luna/Terra execution. Balanced uses Sol
Medium with bounded Luna/Terra workers. Quality uses Sol High with stronger
verification. Max uses Astra High while still delegating mechanical work when
safe. Auto keeps the running parent unchanged and routes phases by ambiguity,
reversibility, blast radius, data/security risk, and verification cost.

The profile name Max does not imply reasoning effort max.

## Model-family refresh

OpenAI's October 2026 GPT-6 guidance lists GPT-6 Astra for the hardest reasoning,
GPT-6.1 Sol for complex coding/research/computer use, and GPT-6 Luna for routine
repeatable work. Treat them as migration candidates, not automatic profile
changes. Benchmark quality, latency, context usage, and actual Codex availability
before updating shipped defaults.
