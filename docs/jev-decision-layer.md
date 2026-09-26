# Jev: Vercel Gateway and direct TypeSafe

Experimental, opt-in, advisory only. The same repository helper supports OmniCodex
and the OmniClaude adapter. This does not install a plugin, change a parent model,
spawn workers, or connect hooks. The separate OmniClaude repository is not updated
by these files; a standalone plugin still needs a reviewed helper/tool.

## Select the provider explicitly

| Provider | Key in process environment | POST endpoint | Boolean wire format |
|---|---|---|---|
| `vercel` | `AI_GATEWAY_API_KEY` only | `https://ai-gateway.vercel.sh/v1/evaluate` | `boolean` / `probability` |
| `typesafe` (default) | `TYPESAFE_API_KEY`, or legacy `JEV_API_KEY` | `https://api.typesafe.ai/v1/systemone` | `noul` / `noul` |

Set `--provider vercel` for a Vercel key. `OMNI_JEV_PROVIDER` is an optional
explicit default for `jev.py`. Never infer a provider from a key. The two paths do
not retry or fall back to each other. Conflicting direct keys are rejected; a
legacy direct key identical to the configured Gateway key is rejected on the
direct path. No `.env` file is read and no key is persisted.

Vercel currently accepts only the documented `typesafe-ai/jev` evaluation model in
this adapter. `models --provider vercel` shows that configured identifier **offline**,
not account availability. Direct TypeSafe uses authenticated `GET /v1/models` and
requires an explicit `--model` returned by that account. Direct aliases may resolve
to another returned identifier; both identifiers are recorded without claiming
independent attestation. Vercel model mismatches fail validation.

`doctor` and every supported `--dry-run` are offline, including `models --dry-run`.
A decision dry run prints the selected state/payload; review its privacy before
sharing the terminal output. The synthetic runner preview contains only bundled
fictional scenarios.

## Windows / PowerShell

Use the existing PR #6 checkout; do not run `git clone` into it again. Fetch/pull
only after checking for local changes and confirming the intended feature branch.
Python 3.11+ is sufficient. No npm package, SDK, or additional Python dependency is
needed. The test never invokes Codex/Claude/Astra or changes their configurations.

In the same PowerShell session where the Gateway key was already configured:

```powershell
Set-Location -LiteralPath "$HOME\Omnicodex-Jev-Test"
$env:OMNI_JEV = "1"
python .\scripts\jev.py doctor --provider vercel
python .\scripts\jev_shadow.py --provider vercel
```

The second command previews six synthetic requests without network access. To run
at most six sequential requests (this consumes Gateway credits):

```powershell
python .\scripts\jev_shadow.py --provider vercel --live --limit 6
```

If the key is not in this session, enter it without embedding it in shell history:

```powershell
$secureKey = Read-Host "Vercel AI Gateway key" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $env:AI_GATEWAY_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    Remove-Variable secureKey, pointer -ErrorAction SilentlyContinue
}
```

This avoids plaintext command history, not plaintext process memory. Child
processes inherit environment variables. Do not use `setx`, print the environment,
commit keys, or send keys to chat. After testing, remove the variable when no longer
needed with `Remove-Item Env:AI_GATEWAY_API_KEY -ErrorAction SilentlyContinue`.

## Response and execution boundaries

`jev.py` supports `route-task`, `retry-strategy`, `review-gate`, `completion-check`.
Responses require the requested answer names, expected types, finite probabilities,
valid choices/distributions, a model, and nonnegative integer usage. Output
normalizes both APIs to booleans with `probability`, choices, snake_case usage, and
`gateway_cost_usd`. The direct API has no cost in this contract: use `null`, not an
invented zero or a price estimate. Choice confidence is distinct from probability;
missing Gateway confidence remains `null`.

State is at most 32 KiB (serialized UTF-8); responses at most 1 MiB. Windows UTF-8
BOM inputs are supported. Redirects, arbitrary endpoints, environment proxies,
automatic retries and cross-provider fallbacks are disabled. Transport errors
expose only a fixed error code and HTTP status, not response bodies or credentials.
Configured credentials embedded in state are rejected, but this is **not general
secret/PII detection**. Only transmit explicitly reviewed, minimized content.
The 30-second network timeout is not a whole-workflow or per-request wall-clock SLA.

The helper returns advice or an error. A host must explicitly keep its native
policy on errors; no auto-approval or fallback action is implemented here.
Permissions, failed tests, retry budgets, and final acceptance remain deterministic
host responsibilities. A high probability is not proof of completion.

## Six-case synthetic observation run

Cases cover a narrow lookup, authentication review, an exhausted retry budget,
a destructive migration, contradicted completion, and evidence-backed completion.
Hand-authored expected labels stay local. Exploratory 0.2/0.8 probability bands
produce `agrees`, `disagrees`, or `uncertain`; they are **not calibrated acceptance
thresholds**. Several deliberately obvious facts should be checked in code in a
real workflow, rather than delegated to Jev.

The default runner is offline. Live execution additionally requires `--live`,
`OMNI_JEV=1` and the correct key. Each invocation is capped at six requests, no
parallelism or retries; the first API/protocol error stops it. Missing returned
cost also stops further calls. `--max-observed-cost-usd` defaults to `0.01`: it stops
**subsequent** calls after observed spend reaches that amount, but is not a hard
precharge cap. One request can exceed it. Configure account budgets separately.

A new `.omnicodex/local/jev-shadow/<run>/` records configuration, sanitized per-case
receipts, and `REPORT.json`. Previous runs are never overwritten. Known symlinked
output paths are rejected. POSIX modes are restrictive; Windows access depends on
inherited NTFS ACLs. These checks are not race-proof filesystem sandboxing.
Receipts record IDs, typed answers, state hash, timing, usage, returned cost, and
assessment, not auth headers, raw server metadata or source files. Failed requests
may still cost money; unobserved costs remain unknown. Logging failure stops the
run; a partial JSONL is evidence, not a completed report.

A successful run proves only API-contract behavior on six examples. It does not
measure Omni task quality, native-router comparison, plan allowance, avoided LLM
calls, or total workload savings. No supplied user API result is represented as
an independently repeated test of this helper.

## Primary references (checked 2026-09-26)

- [Vercel evaluation HTTP API](https://vercel.com/docs/ai-gateway/modalities/evaluation)
- [Vercel Gateway authentication](https://vercel.com/docs/ai-gateway/authentication-and-byok)
- [TypeSafe OpenAPI schema](https://api.typesafe.ai/openapi.json)
