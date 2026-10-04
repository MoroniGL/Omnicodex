---
name: omnicodex
description: Route OmniCodex work by task cost and risk; use bounded workers and token offload for large read-only context.
---

# OmniCodex

Keep planning, consequential decisions, and final acceptance with the active parent.
Optimize context and execution cost without weakening correctness, permissions,
tests, security, or evidence requirements.

Use the smallest useful path:

1. Tiny or tightly scoped work stays with the parent.
2. For substantial work, delegate bounded phases to the least expensive capable
   installed worker; load [routing details](references/routing.md) only when role
   or profile specifics are needed.
3. Before reading a large repository slice, diff, log, or document set into the
   parent context, consult [token offload](references/token-offload.md). Narrow
   scope with deterministic tools first, then automatically estimate and run the
   local gate. Invoke the optional read-only Gemini Direct provider only when the gate,
   workspace approval, and local prerequisites allow it; never use it as quota fallback.
4. For optional graph/index or large-output adapters, consult
   [efficiency adapters](references/efficiency.md) only when relevant.
5. Verify decisions against retrievable source or command evidence. A summary,
   model confidence, graph miss, or worker self-report is not final proof.

Keep task-specific material out of always-on instructions. Load supporting
references only when the current task needs them. Define completion in terms of
the requested change, relevant validation, inspected results, and unresolved risks.
