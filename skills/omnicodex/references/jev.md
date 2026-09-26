# Optional Jev: explicit provider, advisory decisions

Only use Jev after operator opt-in (`OMNI_JEV=1`), with a minimized state approved
for external transmission and tools available to this particular runtime.
Deterministic facts, permissions, retry limits and acceptance gates stay in code.
Jev never authorizes an action or replaces tests, review or the orchestrator.

Select the provider explicitly:
- Vercel: `--provider vercel`, `AI_GATEWAY_API_KEY`, model `typesafe-ai/jev`.
- Direct TypeSafe: `--provider typesafe` (default), `TYPESAFE_API_KEY` or legacy
  `JEV_API_KEY`, an account-visible model from `models`. Conflicting keys fail.

Do not send a Vercel key to TypeSafe. Never guess the provider from a key or retry
through another provider. No credential is bundled, persisted or automatically
loaded from `.env`. Key presence does not prove API access.

From the repository checkout:

```sh
python3 scripts/jev.py doctor --provider vercel
python3 scripts/jev_shadow.py --provider vercel
```

Both are offline. The second previews six fictional scenarios. A separate
operator-approved `--live` invocation consumes credits and records advice only;
it does not route actual workers. See `docs/jev-decision-layer.md` for PowerShell,
limits and receipts. A standalone skill installation does not install the helper.

Supported judgments: `route-task`, `retry-strategy`, `review-gate`,
`completion-check`. For custom state, validate privacy before using `--state-file`.
`--dry-run` previews the selected payload, so do not share private state output.
Boolean formats differ across providers and are normalized by the helper.
Missing metrics are unknown, not zero; no probability threshold proves completion.

On errors or unavailable access, retain the native Omni policy. This instruction
is not a runtime fallback implementation. Never repeat failed paid calls without
new evidence/authorization, and never replace a failed test with a Jev opinion.
