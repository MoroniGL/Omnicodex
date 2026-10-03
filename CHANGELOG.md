# Changelog

## Unreleased

- Add a live, optional FreeLLMAPI context worker through one ephemeral,
  read-only `codex exec` invocation with per-call provider configuration.
- Add bounded scope capture, privacy scanning, immutable staging, workspace
  staleness checks, strict EvidencePack validation, and compact receipts.
- Keep the premium parent authoritative and explicitly prohibit quota fallback,
  global provider replacement, sensitive externalization, and trust in worker
  model/prose self-reports.
- Package the worker runtime and document offline diagnostics, controlled live
  acceptance, telemetry limits, and benchmark requirements.

## 0.1.0-alpha.1 — experimental preview

- Combine the profile installer and local runtime work from PR #2 with the
  context-efficiency policies and offline tooling from PR #3.
- Ship Economy, Balanced, Quality, and Max profile templates and seven worker roles.
- Keep Auto as phase-specific delegation, not a fictional parent-model switch.
- Include the efficiency reference in installation, conflict checks, backups,
  and the per-file manifest; add regression coverage for the combined package.
- Add explicit validation provenance and remaining MCP/benchmark limitations.
- Publish only an experimental GitHub prerelease after automated source tests.

See [release notes](docs/releases/v0.1.0-alpha.1.md). Runtime metadata checks are
not provider attestation, and reduced subscription usage has not been measured.
