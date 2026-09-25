# Jev decision layer

Status: experimental and opt-in.

OmniCodex and OmniClaude use LLMs for planning, code, tool use, and review. Jev
occupies a different role: a fast typed decision boundary for questions with a
predefined answer space.

The integration targets TypeSafe AI's official API:

- `GET https://api.typesafe.ai/v1/models` discovers account-visible model names.
- `POST https://api.typesafe.ai/v1/systemone` accepts `state`, `model`, and
  named typed questions.

No model name is hardcoded because availability can change. Credentials are read
only from `JEV_API_KEY`. The repository never stores an API key.

## Intended decisions

- **route-task**: cheap worker, balanced worker, deep review, or escalation.
- **retry-strategy**: retry once, change strategy, escalate, or stop.
- **review-gate**: whether the supplied task/result warrants independent review.
- **completion-check**: whether supplied evidence is sufficient to report completion.

Jev does not change the running parent model and cannot replace tests, policy,
permissions, source inspection, or a human approval boundary.

## Privacy and cost boundary

A cheaper decision is not useful if it leaks unnecessary code or private data.
Send a compact state summary with identifiers and secrets removed. Prefer
deterministic code when the decision is already encoded in policy or test results.

The helper does not make a network request unless `OMNI_JEV=1` and
`JEV_API_KEY` are both present. `doctor` is offline. Use `--dry-run` to inspect
the outgoing request shape without authentication or network access.

## Evaluation

Before enabling Jev by default, compare with the same tasks without Jev and record:
quality/acceptance results, expensive-model calls, retries, elapsed time, input
tokens, Jev usage, and false route/review/completion decisions. Do not translate
API token savings directly into subscription-plan savings without direct evidence.
