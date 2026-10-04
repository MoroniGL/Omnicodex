# Changelog

## Unreleased

## 0.1.0-alpha.2 — experimental preview

- Add persistent OmniCodex defaults and startup guidance for new Codex sessions.
- Add same-session `omni ...` profile controls through a bounded UserPromptSubmit
  hook while keeping parent-model changes on Codex's native `/model` control.
- Add direct Gemini context offload: deterministic approved scope capture,
  structured EvidencePacks, exact source ranges, local validation, and native
  fail-closed routing without WSL, FreeLLMAPI, or a nested Codex worker.
- Add one preview-first `scripts/setup.py --apply` path that installs assets,
  persistent defaults, and the session-control hook while preserving unrelated
  user configuration and hooks.
- Keep Gemini optional: missing `GEMINI_API_KEY` leaves native OmniCodex ready.
  External context is never used as OpenAI quota fallback.
- Add live Windows acceptance tooling and comprehensive provider/privacy tests.
  Estimated handoff reduction is not a billing or free-tier guarantee.

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
