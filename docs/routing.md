# Routing policy

## Decision order

For every bounded unit of work:

1. Classify the work.
2. Estimate complexity and blast radius.
3. Select the cheapest capable route.
4. Execute and verify.
5. Diagnose failures before escalating.
6. Escalate only when capability is the blocker.
7. De-escalate after the difficult phase.

## Luna

Use for deterministic or tightly bounded work: search, reference lookup, extraction, log summarization, routine test/lint execution, repetitive edits and simple documentation.

Default reasoning: **Low**.

## Terra

Use for codebase exploration, normal implementation, ordinary bug fixes, tests, and small-to-medium refactors.

Default reasoning: **Medium**, with Low for straightforward exploration.

## Sol

Use for architecture, cross-module planning, consequential review, difficult debugging, concurrency, security-sensitive reasoning and complex data-consistency work.

Default reasoning: **Medium**. High requires a concrete reason.

## Astra

**Escalation only.** Use when lower tiers have encountered a genuine reasoning/capability barrier, or when exceptional technical risk justifies the additional cost.

Start with the minimum reasoning level capable of resolving the blocker.

## Escalation

Preferred ladder:

```
Luna -> Terra -> Sol -> Astra
```

Do not escalate merely because a task took time. First check missing context, documentation, tests, decomposition, and instruction quality.

## De-escalation

Routing is phase-specific, not session-specific.

Example:

```
Sol:   decide architecture
Terra: implement
Luna:  run bounded verification
Sol:   review only if risk warrants it
```

## Context budget

Search before reading broadly. Give expensive agents summaries plus critical files instead of indiscriminately forwarding the whole repository. Reuse previous findings and keep handoffs compact.

## Parallelism

Parallelize independent bounded investigations when useful. Avoid redundant expensive agents. Never launch multiple Astra workers against the same problem by default.

## Route transparency

Where practical, emit:

```
ROUTE
Task: <bounded task>
Selected: <tier / reasoning>
Reason: <short technical justification>
Action: ROUTE | ESCALATE | DE-ESCALATE
```

If runtime switching/delegation is unavailable, emit a MODEL CHANGE REQUEST rather than pretending the model changed.
