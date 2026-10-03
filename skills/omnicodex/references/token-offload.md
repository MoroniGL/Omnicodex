# Token offload

Use this workflow when large read-only context would otherwise be loaded into the
premium parent. Its purpose is to avoid unnecessary parent input, not to replace
the orchestrator and not to provide quota fallback.

## Order

1. Narrow scope with deterministic tools first: targeted search, metadata,
   AST/symbol lookup, git diff/stat, line counts, or existing indexes.
2. Estimate candidate context volume without loading the whole payload into the
   parent.
3. Use scripts/efficiency.py offload-plan. It returns native or
   free_context_worker and performs no network request.
4. External FreeLLMAPI offload requires explicit workspace approval and must not
   contain sensitive data. The first live worker is read-only.
5. Require a compact EvidencePack with claims plus retrievable file/line evidence,
   risks, unknowns, and validation state.
6. The parent re-opens exact evidence needed for consequential decisions and owns
   final acceptance.

## First-wave tasks

repo_scout, bulk_file_read, log_distill, diff_analysis, and long_doc_digest.

## Privacy

FreeLLMAPI can route to third-party providers. Public or deliberately approved
private workspaces may be eligible; sensitive content is never externalized.
Never send credentials, .env contents, private keys, full environment dumps, or
unrelated conversation history.

## EvidencePack

The canonical schema is schemas/evidence-pack.schema.json. Do not place whole
source files or raw logs inside the pack. Completed findings contain a concise
claim and one or more repo-relative file/line references. Raw evidence must remain
retrievable locally.

## Parallelism

Parallelize only independent read-only units. Do not parallelize ordered reasoning
or multiple writers against the same mutable resource.

## Measurement

offload-receipt compares a deterministic raw-context estimate with EvidencePack
size. It is routing telemetry, not billing. Live integration must record root and
worker usage separately when available.

## Non-goals

No OpenAI-quota fallback, no automatic private-workspace externalization, no
automatic provider installation in the offline gate, and no claim that free-model
reasoning replaces premium-parent acceptance.
