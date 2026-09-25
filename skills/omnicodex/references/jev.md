# Optional Jev decision layer

Jev is an external TypeSafe AI System One decision model. It returns typed
probabilistic decisions; it does not write code, browse the repository, execute
tools, or replace the OmniCodex orchestrator.

Use Jev only when all of these are true:

1. The operator explicitly set `OMNI_JEV=1`.
2. `JEV_API_KEY` is present in the environment.
3. The decision is narrow: route selection, retry strategy, review gate, or
   completion check.
4. The state can be summarized without credentials, private source dumps,
   customer data, secrets, or unnecessary proprietary context.
5. Native deterministic logic cannot answer the question more cheaply and safely.

Use `python3 scripts/jev.py doctor` for a non-network configuration check and
`python3 scripts/jev.py models` to discover models available to the account.
Never hardcode a model identifier from documentation.

For a bounded routing signal:

```sh
printf '%s' "$SAFE_TASK_SUMMARY" |   python3 scripts/jev.py route-task --model "$JEV_MODEL"
```

Interpret the result as a signal, not an instruction. The parent agent retains
responsibility for permissions, acceptance criteria, model availability, and
verification. Low confidence or material risk should bias toward review, not
automatic action.

Do not call Jev for:
- code generation;
- long-form architecture or debugging;
- authorization of destructive or security-sensitive actions;
- decisions already determined by tests, schemas, policy, or static configuration;
- repeated identical questions after a failure.

If Jev is unavailable, disabled, rejects the request, or returns malformed data,
fall back transparently to the existing OmniCodex policy. Do not retry repeatedly.
