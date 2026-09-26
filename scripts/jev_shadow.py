#!/usr/bin/env python3
"""Six synthetic Jev cases, advisory only. Default is OFFLINE; --live opts in."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import secrets
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

if __package__:
    from . import jev
else:
    import jev

# Labels are hand-authored hypotheses, never sent to the service.
# Tests/completion facts intentionally duplicate deterministic checks to probe errors;
# production should resolve these facts in code rather than pay Jev for them.
CASES = (
    {"id": "bounded-lookup", "kind": "route-task", "state": {
        "scenario": "synthetic", "goal": "Locate a named function and return its path and line.",
        "scope": "Small repository; read-only exact-symbol lookup; no edits or sensitive data.",
    }, "expected": {"route": "cheap_worker"}},
    {"id": "auth-risk", "kind": "route-task", "state": {
        "scenario": "synthetic", "goal": "Review a proposed change to authentication and session permissions.",
        "evidence": "No tests or independent review yet. The change is available for review.",
    }, "expected": {"route": "deep_review", "needs_review": True}},
    {"id": "retry-exhausted", "kind": "retry-strategy", "state": {
        "scenario": "synthetic", "goal": "Fix a deterministic failing test.",
        "attempts": 3, "allowed_attempts": 3, "new_evidence": False,
        "last_results": "The same approach failed three times with the same error.",
    }, "expected": {"retry": "stop"}},
    {"id": "migration-review", "kind": "review-gate", "state": {
        "scenario": "synthetic", "change": "A migration irreversibly deletes customer records.",
        "evidence": "No recovery test or independent review has been performed.",
    }, "expected": {"needs_review": True}},
    {"id": "not-complete", "kind": "completion-check", "state": {
        "scenario": "synthetic", "goal": "Implement an endpoint and pass every required test.",
        "result": "The file exists, but the required integration test failed with exit 1.",
        "agent_claim": "Everything is done.",
    }, "expected": {"complete": False}},
    {"id": "complete-evidence", "kind": "completion-check", "state": {
        "scenario": "synthetic", "goal": "Fix one specific spelling error in README and change nothing else.",
        "evidence": "The final diff contains exactly the requested spelling fix. No other files changed. The final spelling check passed with exit 0. No edits followed the check.",
        "remaining_criteria": [],
    }, "expected": {"complete": True}},
)


def assessment(answers: dict[str, Any], expected: dict[str, Any]) -> dict[str, str]:
    """Exploratory bands, not calibrated probabilities or runtime acceptance gates."""
    results = {}
    for name, target in expected.items():
        answer = answers[name]
        if type(target) is bool:
            p = answer["probability"]
            agrees = p >= 0.8 if target else p <= 0.2
            contradicts = p <= 0.2 if target else p >= 0.8
            results[name] = "agrees" if agrees else ("disagrees" if contradicts else "uncertain")
        else:
            results[name] = "agrees" if answer["choice"] == target else "disagrees"
    return results


def _private_output(path: Path) -> Path:
    """New directory only; do not overwrite earlier runs or traverse known links."""
    path = path.absolute()
    for item in (path, *path.parents):
        jev._require(not item.is_symlink(), "output_symlink_refused")
    path.mkdir(parents=True, exist_ok=False, mode=0o700)
    return path


def _write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, indent=2, ensure_ascii=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def run(*, live: bool, limit: int, provider: str, model: str,
        output: Path | None, max_observed_cost: Decimal) -> dict[str, Any]:
    jev._require(1 <= limit <= len(CASES), "invalid_case_limit")
    jev._require(max_observed_cost.is_finite() and max_observed_cost > 0, "invalid_cost_stop")
    cases = CASES[:limit]
    payloads = [jev.build_payload(c["kind"], model, c["state"], provider) for c in cases]
    if not live:
        return {"mode": "offline_preview", "network_checked": False,
                "planned_requests": limit, "provider": provider,
                "cases": [{"id": c["id"], "payload": p} for c, p in zip(cases, payloads)],
                "notice": "No request made. Use --live plus OMNI_JEV=1 and the selected provider key."}

    jev.check_live_access(provider)  # Do not create output before credential/opt-in preflight.
    if output is None:
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
        output = Path(__file__).resolve().parents[1] / ".omnicodex/local/jev-shadow" / stamp
    folder = _private_output(output)
    _write_json(folder / "run.json", {
        "schema_version": 1, "mode": "synthetic_shadow_probe", "provider": provider,
        "model": model, "contract": jev.CONTRACT_VERSION, "planned_requests": limit,
        "max_observed_cost_usd": str(max_observed_cost), "observed_cost_stop_is_not_precharge_cap": True,
        "fixture_sha256": hashlib.sha256(jev._json_bytes(list(cases))).hexdigest(),
        "effect_on_routing": "none", "thresholds": "exploratory 0.2/0.8; not calibrated",
    })
    attempted = 0
    records = []
    known_cost = Decimal(0)
    cost_complete = True
    stop_reason = "all_cases_completed"
    with (folder / "receipts.jsonl").open("x", encoding="utf-8") as stream:
        os.chmod(folder / "receipts.jsonl", 0o600)
        for case in cases:
            attempted += 1
            try:
                receipt = jev.evaluate(case["kind"], case["state"], provider=provider, model=model)
                receipt.update({"case_id": case["id"], "assessment": assessment(receipt["answers"], case["expected"])})
                cost = receipt["gateway_cost_usd"]
                if cost is None:
                    cost_complete = False
                else:
                    known_cost += Decimal(cost)
            except (jev.JevError, OSError, ValueError, UnicodeError) as exc:
                receipt = {"case_id": case["id"], **jev.error_record(exc), "usage": None,
                           "gateway_cost_usd": None, "cost_of_failed_request_unknown": True}
                cost_complete = False
                stop_reason = "error_no_retry"
            records.append(receipt)
            stream.write(json.dumps(receipt, ensure_ascii=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            if stop_reason == "error_no_retry":
                break
            if not cost_complete:
                stop_reason = "missing_cost_stop"
                break
            if known_cost >= max_observed_cost:
                stop_reason = "observed_cost_limit_stop"
                break
    outcomes = [r for r in records if "error" not in r]
    totals = {k: sum(r["usage"][k] for r in outcomes) for k in ("input_tokens", "output_tokens")}
    report = {"schema_version": 1, "mode": "synthetic_shadow_probe", "provider": provider,
              "attempted_requests": attempted, "valid_responses": len(outcomes),
              "planned_requests": limit, "stop_reason": stop_reason,
              "known_cost_subtotal_usd": str(known_cost), "cost_accounting_complete": cost_complete,
              "total_observed_cost_usd": str(known_cost) if cost_complete else None,
              "observed_usage_valid_responses_only": totals, "action_executed": False,
              "results": records, "output_directory": str(folder),
              "limitations": "Synthetic labels only; not a live Omni routing comparison, calibrated accuracy, total-workflow latency, or subscription savings benchmark. Unknown costs are not zero. A request may exceed the observed-cost stop before returning."}
    _write_json(folder / "REPORT.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Authorize up to --limit sequential API requests.")
    parser.add_argument("--limit", type=int, choices=range(1, len(CASES) + 1), default=len(CASES))
    parser.add_argument("--provider", choices=tuple(jev.PROVIDERS), default="vercel")
    parser.add_argument("--model")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--max-observed-cost-usd", default="0.01")
    args = parser.parse_args(argv)
    try:
        cap = Decimal(args.max_observed_cost_usd)
        model = args.model if args.model is not None else ("typesafe-ai/jev" if args.provider == "vercel" else "")
        report = run(live=args.live, limit=args.limit, provider=args.provider, model=model,
                     output=args.out, max_observed_cost=cap)
        print(json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False))
        if args.live and report["stop_reason"] == "error_no_retry":
            return 2
        return 0
    except (jev.JevError, OSError, ValueError, InvalidOperation, UnicodeError) as exc:
        print(json.dumps(jev.error_record(exc)), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
