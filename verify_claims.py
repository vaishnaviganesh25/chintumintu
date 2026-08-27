#!/usr/bin/env python
"""Check that every headline number in README.md is still true.

A README is the part of a project most likely to be believed and least likely to be
re-checked. This one carried a 0.9% dispute ceiling for a card-network programme that
had been retired for a year, a test count that contradicted itself twice on one screen,
and model metrics from a run two feature sets ago. None of it was dishonest; all of it
was stale, and stale is indistinguishable from dishonest to a reader who checks.

So the claims are re-derived here from the artifacts that produced them - the model
config, the evaluation report, and the policy constants - and compared against what the
README actually says. A mismatch fails the build.

    python verify_claims.py                     # check
    python verify_claims.py --verbose           # show every claim, not just failures
    python verify_claims.py --skip-test-counts  # skip the slow pytest collection

This reads the *shipped artifacts* rather than retraining: it answers "does the prose
match the model in models/", which is the question a reader has. Retraining is CI's job,
and the end-to-end workflow does it on every push to main.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from pathlib import Path

from merchant_policy import DISPUTE_RATIO_CEILING

ROOT = Path(__file__).resolve().parent
README = ROOT / "README.md"
CONFIG = ROOT / "models" / "model_config.json"
REPORT = ROOT / "reports" / "evaluation_report.txt"


@dataclass(frozen=True)
class Claim:
    """One assertion the README makes, and where the truth for it lives."""

    what: str
    expected: str          # rendered the way the README writes it
    source: str            # where it was derived from, for the failure message


def _from_report(pattern: str, report: str) -> str:
    """First capture group of `pattern` in the evaluation report."""
    match = re.search(pattern, report)
    if match is None:
        raise SystemExit(f"verify_claims: pattern not found in the evaluation report: {pattern}")
    return match.group(1)


def _rupees(value: float) -> str:
    return f"{round(value):,}"


def build_claims() -> list[Claim]:
    if not CONFIG.exists() or not REPORT.exists():
        raise SystemExit(
            "verify_claims: models/model_config.json and reports/evaluation_report.txt\n"
            "are both required. Run `python train_model.py` first."
        )
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    report = REPORT.read_text(encoding="utf-8")

    test = cfg["production_metrics"]["test"]
    rf = cfg["metrics"]["RandomForest"]
    xgb = cfg["metrics"]["XGBoost"]

    binary_cost = float(_from_report(r"block/allow at [\d.]+\s+Rs\.\s*([\d,]+)", report).replace(",", ""))
    three_cost = float(_from_report(r"accept / step-up / hold\s+Rs\.\s*([\d,]+)", report).replace(",", ""))

    claims = [
        Claim("test PR-AUC", f"{test['pr_auc']:.4f}",
              "model_config production_metrics.test.pr_auc"),
        Claim("calibrated threshold", f"{cfg['optimal_threshold']:.4f}",
              "model_config optimal_threshold"),
        Claim("test precision", f"{test['precision']:.4f}",
              "model_config production_metrics.test.precision"),
        Claim("test recall", f"{test['recall']:.4f}",
              "model_config production_metrics.test.recall"),
        Claim("Random Forest CV", f"{rf['cv_pr_auc_mean']:.4f} ± {rf['cv_pr_auc_std']:.4f}",
              "model_config metrics.RandomForest"),
        Claim("XGBoost CV", f"{xgb['cv_pr_auc_mean']:.4f} ± {xgb['cv_pr_auc_std']:.4f}",
              "model_config metrics.XGBoost"),
        Claim("XGBoost test PR-AUC", f"{xgb['test_calibrated_threshold']['pr_auc']:.4f}",
              "model_config metrics.XGBoost.test_calibrated_threshold"),
        Claim("dataset rows", f"{cfg['dataset']['rows']:,}", "model_config dataset.rows"),
        Claim("single-threshold cost", f"₹{_rupees(binary_cost)}",
              "evaluation report, policy table"),
        Claim("three-action cost", f"₹{_rupees(three_cost)}",
              "evaluation report, policy table"),
        Claim("saving over the single threshold", f"₹{_rupees(binary_cost - three_cost)}",
              "evaluation report, the two policy rows"),
        Claim("saving as a share",
              f"{round(100 * (binary_cost - three_cost) / binary_cost)}%",
              "evaluation report, the two policy rows"),
        Claim("challenge budget used",
              _from_report(r"Challenge budget used\s*:\s*([\d.]+)% of", report) + "% of payments",
              "evaluation report, budget line"),
        # Straight from the constant, not the report's two-decimal rendering of it:
        # the report prints "1.50%" where prose naturally writes "1.5%", and a
        # verifier that fails on trailing zeros trains people to ignore it.
        Claim("dispute ceiling", f"{DISPUTE_RATIO_CEILING * 100:g}%",
              "merchant_policy.DISPUTE_RATIO_CEILING"),
        Claim("covenant binding prevalence",
              _from_report(r"bind above ([\d.]+)% prevalence", report) + "%",
              "evaluation report, covenant paragraph"),
        Claim("ablation without account age",
              _from_report(r"without receiver VPA age\s+([\d.]+)", report),
              "evaluation report, ablation table"),
        Claim("ablation without either block",
              _from_report(r"without either\s+([\d.]+)", report),
              "evaluation report, ablation table"),
    ]

    # The split is this project's central methodological claim, so check the artifact
    # agrees with the prose rather than only that some number matches.
    if cfg["split"].get("group_aware"):
        claims.append(Claim("split grouping key", f"`{cfg['split']['grouped_on']}`",
                            "model_config split.grouped_on"))
    return claims


def count_tests() -> tuple[int, int] | None:
    """(all, not-slow) collected Python tests, or None if pytest cannot collect."""

    def collect(extra: list[str]) -> int | None:
        try:
            # Fixed argv, no shell, no caller-supplied component.
            out = subprocess.run(  # noqa: S603  # nosec B603
                [sys.executable, "-m", "pytest", "--collect-only", "-q", *extra],
                cwd=ROOT, capture_output=True, text=True, timeout=600, check=False,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        return sum(int(n) for n in re.findall(r"^tests[/\\].*: (\d+)$", out, re.M)) or None

    total, fast = collect([]), collect(["-m", "not slow"])
    return None if total is None or fast is None else (total, fast)


def main() -> int:
    # The claims include rupee figures, and a Windows console defaults to cp1252,
    # which cannot encode the sign. Without this the tool crashes on its own output.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Verify README claims against artifacts.")
    parser.add_argument("--verbose", action="store_true", help="print passing claims too")
    parser.add_argument("--skip-test-counts", action="store_true",
                        help="skip pytest collection, which is the slow part")
    args = parser.parse_args()

    readme = README.read_text(encoding="utf-8")
    claims = build_claims()

    if not args.skip_test_counts:
        counted = count_tests()
        if counted is not None:
            total, fast = counted
            claims += [
                Claim("Python tests, all", f"{total} tests", "pytest --collect-only"),
                Claim("Python tests, not slow", f"{fast} of them",
                      "pytest -m 'not slow' --collect-only"),
            ]

    failures = []
    for claim in claims:
        ok = claim.expected in readme
        if not ok:
            failures.append(claim)
        if args.verbose or not ok:
            print(f"  {'ok  ' if ok else 'MISS'}  {claim.what:<34} {claim.expected}")
            if not ok:
                print(f"          not in README.md - source: {claim.source}")

    print()
    if failures:
        print(f"{len(failures)} of {len(claims)} claims do not appear in README.md as written.")
        print("Either the prose is stale or the artifacts moved. Both are worth knowing.")
        return 1
    print(f"All {len(claims)} claims in README.md match the shipped artifacts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
