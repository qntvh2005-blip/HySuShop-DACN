"""Post-hoc paired user bootstrap of frozen test metrics; never refits a model."""

import argparse
import json
from pathlib import Path

import numpy as np

from research.data.io import file_hash, write_json
from research.models.recommenders import ALGORITHMS

METRICS = ("ndcg@10", "hit_rate@10")
BASELINES = tuple(name for name in ALGORITHMS if name != "hybrid")


def paired_bootstrap(rows, *, repeats=5000, seed=42):
    """Percentile intervals conditional on this test cohort and fitted models.

    Resample users, retaining every algorithm/metric for each sampled user.
    These descriptive intervals are not adjusted for multiple comparisons.
    """
    if repeats < 2:
        raise ValueError("At least two bootstrap replicates are required")
    users = {}
    for row in rows:
        if row["stage"] != "test" or row["algorithm"] not in ALGORITHMS:
            raise ValueError("Only the four frozen test algorithms are accepted")
        paired = users.setdefault(row["user_id"], {})
        if row["algorithm"] in paired or row["group"] not in {"sparse", "active"}:
            raise ValueError("Duplicate user/algorithm or invalid group")
        for metric in METRICS:
            value = row[metric]
            if not np.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("Metrics must be finite and within [0, 1]")
            if metric == "hit_rate@10" and value not in (0, 1):
                raise ValueError("Per-user hit rate must be binary")
        paired[row["algorithm"]] = row
    if not users:
        raise ValueError("The test cohort is empty")
    ordered = [users[user] for user in sorted(users)]
    for paired in ordered:
        if set(paired) != set(ALGORITHMS):
            raise ValueError("Every user must have all four algorithms")
        contracts = {
            (r["group"], r["candidate_count"], r["candidate_sha256"])
            for r in paired.values()
        }
        if len(contracts) != 1:
            raise ValueError("Paired algorithms must share group and candidates")
    rng = np.random.default_rng(seed)
    result = {"method": "paired-user percentile bootstrap", "post_hoc": True,
              "repeats": repeats, "seed": seed, "confidence_level": 0.95,
              "scope": "conditional on frozen models, rankings and test cohort; no refit",
              "multiple_comparison_adjustment": None, "groups": {}}
    for group in ("all", "sparse", "active"):
        members = [p for p in ordered if group == "all" or p["hybrid"]["group"] == group]
        if not members:
            result["groups"][group] = {"users": 0, "comparisons": {}}
            continue
        differences = np.array([
            [p["hybrid"][metric] - p[baseline][metric]
             for baseline in BASELINES for metric in METRICS] for p in members
        ])
        draws = np.empty((repeats, differences.shape[1]))
        for start in range(0, repeats, 128):
            stop = min(start + 128, repeats)
            indices = rng.integers(len(members), size=(stop - start, len(members)))
            draws[start:stop] = differences[indices].mean(axis=1)
        limits = np.quantile(draws, [0.025, 0.975], axis=0)
        means = differences.mean(axis=0)
        comparisons = {}
        for index, baseline in enumerate(BASELINES):
            comparisons[baseline] = {
                metric: {"difference": float(means[index * 2 + offset]),
                         "lower": float(limits[0, index * 2 + offset]),
                         "upper": float(limits[1, index * 2 + offset])}
                for offset, metric in enumerate(METRICS)
            }
        result["groups"][group] = {"users": len(members), "comparisons": comparisons}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output file to preserve saved results")
    directory = args.report_directory
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    sources = {}
    for name in ("test_per_user.jsonl", "test_metrics.json"):
        sources[name] = file_hash(directory / name)
        if sources[name] != manifest["outputs"][name]:
            parser.error(f"Frozen input checksum mismatch: {name}")
    rows = [json.loads(line) for line in (directory / "test_per_user.jsonl").read_text(
        encoding="utf-8").splitlines() if line.strip()]
    result = paired_bootstrap(rows)
    result["input_sha256"] = {**sources, "manifest.json": file_hash(directory / "manifest.json")}
    write_json(args.output, result)
    print(f"Saved paired user uncertainty estimates: {args.output}")


if __name__ == "__main__":
    main()
