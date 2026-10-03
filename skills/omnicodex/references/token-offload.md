# Token offload

Use this progressive workflow automatically when a large read-only repository
slice, diff, log, or document set would otherwise enter the premium parent's
context. The installed runtime is under `$CODEX_HOME/omnicodex/`. FreeLLMAPI is an
optional context reader: it never replaces the premium parent and is never an
OpenAI quota fallback.

## Preconditions

Offload only when all of these are true:

- The task is one of `repo_scout`, `bulk_file_read`, `log_distill`,
  `diff_analysis`, or `long_doc_digest`.
- The workspace is public or deliberately classified `approved_private`, and the
  user or workspace policy explicitly approves external offload.
- The narrowed scope has no credentials, `.env` data, private keys, auth material,
  sensitive dumps, binary files, or unrelated conversation/environment history.
- `FREELLMAPI_API_KEY` is nonempty in the local environment and a usable `codex`
  binary is available. `FREELLMAPI_BASE_URL` is optional and defaults to
  `http://127.0.0.1:3001/v1`.

If any condition is false, stay on the native premium-parent path. Do not ask for
offload merely because quota, rate limits, or allowance are exhausted.

## Automatic parent workflow

1. **Narrow.** Use targeted search, metadata, AST/symbol lookup, `git diff --stat`,
   line/byte counts, or an existing index before reading bodies. Select only the
   repo-relative files or directories needed for the bounded objective.
2. **Estimate.** Compute `estimated_chars`, `file_count`, `diff_lines`, `log_bytes`,
   and `search_hits` from deterministic metadata. Do not load the full candidate
   payload into the parent merely to estimate it.
3. **Gate.** Create a bounded request and run `dry-run`. This validates the request,
   captures the approved scope, replaces caller size/count estimates with the
   actual captured bytes, files, and lines, derives provider availability locally,
   calculates the profile threshold, and makes zero network requests. Callers
   never set `provider_available` themselves.
4. **Invoke once.** Only a `ready` result with route `free_context_worker` permits
   `run`. The runtime stages the immutable approved scope outside the repository
   and starts one isolated, read-only, no-web Codex subprocess with model `auto`.
   Its strict permission profile denies root access and permits only minimal Codex
   runtime paths plus that exact staged copy; model-initiated network access and
   escalation requests are denied. Current Codex treats the older `--sandbox`
   flag as an override, so the worker intentionally uses the custom profile
   without that flag.
   Do not retry with another provider or model.
5. **Validate locally.** Accept output only after schema, task kind, snapshot,
   token budget, captured-file subset, source existence, line bounds, and a second
   workspace fingerprint check all pass. The UTF-8 pack estimate plus the union of
   cited source ranges must also be smaller than the captured raw estimate. A
   failure recommends the native path; it
   does not make untrusted worker prose evidence.
6. **Open exact evidence.** Read only the cited repo-relative file/line ranges
   needed to verify claims. The EvidencePack summary is a locator, not proof.
7. **Continue on premium.** The parent retains planning, edits, consequential
   reasoning, test interpretation, final verification, and the response to the
   user. Record unknowns and reject stale or unsupported claims.

## Request file

The request is bounded JSON and contains no absolute workspace path. A typical
shape is:

```json
{
  "schema_version": 1,
  "task_kind": "repo_scout",
  "objective": "Locate the request validation and its direct callers.",
  "approved_paths": ["scripts", "tests/test_free_context_worker.py"],
  "data_classification": "public",
  "external_offload_approved": true,
  "metrics": {
    "schema_version": 1,
    "task_kind": "repo_scout",
    "estimated_chars": 80000,
    "file_count": 20,
    "diff_lines": 0,
    "log_bytes": 0,
    "search_hits": 12,
    "data_classification": "public",
    "external_offload_approved": true,
    "independent_units": 1
  }
}
```

Use forward-slash repo-relative paths. Never add secrets, file contents, an
absolute workspace path, or `provider_available`. Add `expected_snapshot` only
when pinning the request to a previously captured 64-character SHA-256 scope
fingerprint.

## Commands

`doctor` is offline and reports local prerequisites only. It does not probe the
gateway or verify the served provider/model.

```sh
python3 "$CODEX_HOME/omnicodex/scripts/free_context_worker.py" doctor
```

Run the zero-network gate before live execution:

```sh
python3 "$CODEX_HOME/omnicodex/scripts/free_context_worker.py" dry-run \
  --workspace /absolute/path/to/repo \
  --request /absolute/path/to/request.json \
  --profile balanced
```

If and only if that returns `status: ready` and route
`free_context_worker`, invoke one worker. An explicit artifact directory must be
new, outside the workspace, and beneath an existing non-link parent; omitting it
uses a private unique OS-temporary directory.

```sh
python3 "$CODEX_HOME/omnicodex/scripts/free_context_worker.py" run \
  --workspace /absolute/path/to/repo \
  --request /absolute/path/to/request.json \
  --profile balanced \
  --timeout 120
```

Use `--codex /absolute/path/to/codex` only for an explicit binary; otherwise
resolution is `OMNICODEX_CODEX_PATH`, then `PATH`. Never put the API key in a
request, command argument, prompt, receipt, or committed file.

## Result handling

- `fallback` / `native` with exit 0 means the gate declined, the key is missing,
  or Codex is unavailable. Continue natively; no worker started.
- `completed` with route `free_context_worker` means the local EvidencePack was
  accepted. Retrieve `evidence-pack.json` and `receipt.json` from the returned
  artifact directory, then inspect exact cited ranges in the original workspace.
- `blocked` or `needs_review` with route `free_context_worker` means a structurally
  valid pack was preserved but did not claim completion. Inspect its unknowns and
  cited evidence; do not represent the context task as completed.
- `failed` / `native` with nonzero exit means timeout, worker failure, invalid or
  oversized output, snapshot mismatch, or workspace mutation. Use the reason code
  diagnostically and continue natively only when still appropriate. Never accept
  the rejected pack or retry as quota fallback.

The receipt is routing telemetry. It distinguishes captured raw bytes, raw token
estimate, pack estimate, cited-evidence estimate, and their combined compact
handoff. `estimated_*` values are estimates;
`billing_verified`, `subscription_allowance_verified`, and `quota_fallback`
remain false unless a future independently verified mechanism changes the
contract. Served provider/model fields are populated only when reliable runtime
events expose them.

## EvidencePack contract

The canonical schema is
`$CODEX_HOME/omnicodex/schemas/evidence-pack.schema.json`. Completed findings use
concise claims and one or more approved repo-relative file/line references. Raw
source and logs stay in the original workspace; whole files and raw logs do not
belong in the pack. Risks, unknowns, and validation state must remain explicit.

Parallelize only genuinely independent read-only units. Never parallelize ordered
reasoning or writers against shared mutable state.

## Non-goals

This workflow does not install or operate a FreeLLMAPI gateway, externalize an
unapproved private workspace, send sensitive content, switch the parent model,
recover from OpenAI quota exhaustion, prove billing savings, or let free-model
reasoning replace premium-parent acceptance.
