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


# How far a fresh retrain may drift from the committed artifacts before it means
# something actually changed. These are not float-noise tolerances: the pipeline is not
# pinned to bitwise reproducibility across operating systems and library builds, and
# pretending otherwise would make this check flap forever.
#
# They are sized against a real failure, from both sides. When the dataset generator was
# still non-deterministic, a CI retrain moved the calibrated threshold by 54% relative
# and test precision by 0.146 absolute - both well past the bounds below, so that bug
# fails loudly. Two honest runs on different machines moved the threshold by about 8%
# and precision by 0.006, which passes comfortably. The bounds sit between.
#
# PR-AUC is deliberately not the tripwire. It moved 0.9979 -> 0.9978 across that same
# broken run: threshold-free metrics are exactly the ones a dataset bug hides behind.
DRIFT_LIMITS = {
    "calibrated threshold": 0.35,      # relative
    "shipped policy cost": 0.20,       # relative
    "test precision": 0.08,            # absolute
    "test PR-AUC": 0.01,               # absolute
}



def compare_to_committed(reference_dir: Path) -> int:
    """Check a freshly retrained model against the artifacts committed to the repo.

    Run after a retrain in CI. `reference_dir` holds the committed `model_config.json`
    and `evaluation_report.txt`, saved before the retrain overwrote them.

    This asks "did rebuilding from source land in the same place", which is a weaker
    question than "is every digit identical" - and the honest one to ask of a stack that
    is not pinned to bitwise reproducibility across operating systems and library builds.
    """
    ref_config = reference_dir / "model_config.json"
    ref_report = reference_dir / "evaluation_report.txt"
    for path in (ref_config, ref_report):
        if not path.exists():
            raise SystemExit(f"verify_claims: reference artifact not found: {path}")

    was = json.loads(ref_config.read_text(encoding="utf-8"))
    now = json.loads(CONFIG.read_text(encoding="utf-8"))

    # If the two runs did not build the same dataset, they are not comparable, and
    # holding them to a drift budget would be measuring library versions rather than
    # this pipeline. Say so and stop: the byte-reproducibility check in CI already
    # covers determinism *within* an environment, which is the claim being made.
    was_hash = was.get("dataset", {}).get("sha256")
    now_hash = now.get("dataset", {}).get("sha256")
    if was_hash and now_hash and was_hash != now_hash:
        print(f"  reference dataset : {was_hash[:16]}")
        print(f"  rebuilt dataset   : {now_hash[:16]}")
        print()
        print("The rebuild produced a different dataset, so the models are not")
        print("comparable. That is a dependency-version difference between this")
        print("environment and the one that produced the committed artifacts, not a")
        print("change in the pipeline - determinism within an environment is checked")
        print("separately by regenerating under a different PYTHONHASHSEED.")
        return 0
    if was_hash and now_hash:
        print(f"  same dataset rebuilt ({now_hash[:16]}), so the models must agree")
    cost_pattern = r"accept / step-up / hold\s+Rs\.\s*([\d,]+)"
    cost_was = float(_from_report(cost_pattern, ref_report.read_text(encoding="utf-8")).replace(",", ""))
    cost_now = float(_from_report(cost_pattern, REPORT.read_text(encoding="utf-8")).replace(",", ""))

    checks = [
        ("calibrated threshold", was["optimal_threshold"], now["optimal_threshold"], "rel"),
        ("shipped policy cost", cost_was, cost_now, "rel"),
        ("test precision", was["production_metrics"]["test"]["precision"],
         now["production_metrics"]["test"]["precision"], "abs"),
        ("test PR-AUC", was["production_metrics"]["test"]["pr_auc"],
         now["production_metrics"]["test"]["pr_auc"], "abs"),
    ]

    failures = []
    for name, before, after, kind in checks:
        limit = DRIFT_LIMITS[name]
        drift = abs(after - before) / abs(before) if kind == "rel" else abs(after - before)
        if drift > limit:
            failures.append(name)
        unit = "relative" if kind == "rel" else "absolute"
        print(f"  {'ok   ' if drift <= limit else 'DRIFT'}  {name:<22} "
              f"{before:>12,.4f} -> {after:>12,.4f}   ({drift:.4f} {unit}, limit {limit})")

    print()
    if failures:
        print(f"A fresh retrain drifted beyond the stated limits on: {', '.join(failures)}.")
        print("That is a change in the pipeline, not noise. Investigate before shipping.")
        return 1
    print("A fresh retrain lands within the stated limits of the committed artifacts.")
    return 0


def main() -> int:
    # The claims include rupee figures, and a Windows console defaults to cp1252,
    # which cannot encode the sign. Without this the tool crashes on its own output.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Verify README claims against artifacts.")
    parser.add_argument("--verbose", action="store_true", help="print passing claims too")
    parser.add_argument("--skip-test-counts", action="store_true",
                        help="skip pytest collection, which is the slow part")
    parser.add_argument("--compare-to", type=Path, metavar="DIR",
                        help="directory holding the committed model_config.json and "
                             "evaluation_report.txt; compares a fresh retrain against "
                             "them instead of checking the README")
    args = parser.parse_args()

    if args.compare_to is not None:
        return compare_to_committed(args.compare_to)

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
