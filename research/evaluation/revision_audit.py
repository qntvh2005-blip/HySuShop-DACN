"""Recheck frozen results and report post-hoc uncertainty without tuning on test."""

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from research.data.dataset import ResearchDataset
from research.data.io import digest, file_hash, write_json
from research.evaluation.uncertainty import paired_bootstrap
from research.models.artifacts import load_bundle
from research.models.recommenders import ALGORITHMS, minmax
from research.validate import validate


def paired_randomization(rows, repeats=10000, seed=20261119):
    # Paired exchangeability under the null; correct the 18 comparisons together.
    paired_bootstrap(rows, repeats=2, seed=seed)
    by_user = {}
    for row in rows:
        by_user.setdefault(row["user_id"], {})[row["algorithm"]] = row
    rng = np.random.default_rng(seed)
    comparisons = []
    for group in ["all", "sparse", "active"]:
        users = [by_user[u] for u in sorted(by_user) if group == "all" or by_user[u]["hybrid"]["group"] == group]
        for algorithm in ["popularity", "content", "item_cf"]:
            for metric in ["ndcg@10", "hit_rate@10"]:
                difference = np.array([u["hybrid"][metric] - u[algorithm][metric] for u in users])
                observed = float(difference.mean())
                extreme = 0
                for start in range(0, repeats, 128):
                    count = min(128, repeats - start)
                    signs = rng.choice([-1, 1], size=(count, len(users)))
                    draws = (signs * difference).mean(axis=1)
                    extreme += int(np.count_nonzero(np.abs(draws) >= abs(observed) - 1e-14))
                comparisons.append({
                    "group": group, "baseline": algorithm, "metric": metric, "users": len(users),
                    "difference": observed, "p_two_sided": (extreme + 1) / (repeats + 1),
                })
    order = sorted(range(len(comparisons)), key=lambda i: comparisons[i]["p_two_sided"])
    previous = 0
    for position, index in enumerate(order):
        previous = min(1.0, max(previous, comparisons[index]["p_two_sided"] * (len(order) - position)))
        comparisons[index]["p_holm"] = previous
    return {"method": "paired sign-flip randomization, two-sided", "repeats": repeats,
            "seed": seed, "adjustment": "Holm across 18 comparisons", "post_hoc": True,
            "assumption": "paired algorithm labels are exchangeable under the null; cohort and fits are fixed",
            "comparisons": comparisons}


def audit(dataset_dir, report_dir, artifact_dir, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    dataset = ResearchDataset(dataset_dir)
    report_dir = Path(report_dir)
    report_manifest = json.loads((report_dir / "manifest.json").read_text(encoding="utf-8"))
    for name in ["test_per_user.jsonl", "test_metrics.json", "locked_config.json"]:
        if file_hash(report_dir / name) != report_manifest["outputs"][name]:
            raise ValueError(f"Changed frozen report: {name}")
    if file_hash(dataset.directory / "manifest.json") != report_manifest["locked_config"]["dataset_manifest_sha256"]:
        raise ValueError("Dataset is not the frozen benchmark cohort")
    bundle, artifact_manifest = load_bundle(artifact_dir)
    if artifact_manifest["bundle_sha256"] != report_manifest["artifact_bundle_sha256"]:
        raise ValueError("Bundle differs from frozen fit")
    rows = [json.loads(line) for line in (report_dir / "test_per_user.jsonl").read_text(encoding="utf-8").splitlines()]
    targets = {row["user_id"]: row for row in dataset.rows("test")}
    recomputed = 0
    for row in rows:
        result = bundle.rank(row["algorithm"], bundle.histories.get(row["user_id"], []), dataset.candidates(row["user_id"], "test"), 10)
        if result.item_ids != row["ranked_item_ids"]:
            raise ValueError("Frozen rankings cannot be reproduced")
        recomputed += 1
    degree = Counter(row["item_id"] for row in dataset.rows("train"))
    top = [item for item, _ in sorted(degree.items(), key=lambda pair: (-pair[1], pair[0]))[:71]]
    train = list(dataset.rows("train"))
    audit_result = {
        "validation": validate(dataset.directory), "rankings_reproduced": recomputed,
        "top_decile_items": len(top), "top_decile_train_share": sum(degree[item] for item in top) / len(train),
        "groups": Counter(row["group"] for row in dataset.rows("users")),
        "leakage_limit": "core and item selection use the full cohort before temporal splitting; results are conditional on this retrospective catalog",
        "catalog_metadata": "TF-IDF is fit on the fixed catalog; historical metadata availability is not guaranteed by the source",
        "refit_or_test_tuning": False,
    }
    write_json(output / "data_audit.json", audit_result)
    write_json(output / "bootstrap.json", paired_bootstrap(rows))
    write_json(output / "statistical_tests.json", paired_randomization(rows))
    exposures = {}
    for algorithm in ALGORITHMS:
        recommendations = [item for row in rows if row["algorithm"] == algorithm for item in row["ranked_item_ids"]]
        exposures[algorithm] = {
            "distinct_recommended_items": len(set(recommendations)),
            "top_decile_recommendation_share": sum(item in top for item in recommendations) / len(recommendations),
        }
    write_json(output / "popularity_exposure.json", exposures)
    user = sorted(targets)[0]
    candidates = dataset.candidates(user, "test")
    history = bundle.histories[user]
    content, cf = bundle.component_scores(history, candidates)
    content_norm, cf_norm = minmax(content, bundle.epsilon), minmax(cf, bundle.epsilon)
    ranking = bundle.rank("hybrid", history, candidates, 10)
    positions = {item: i for i, item in enumerate(candidates)}
    example = {"selection": "first lexicographic test user, fixed before examining scores", "user_id": user,
               "history": history, "target": targets[user]["item_id"], "alpha": bundle.alpha,
               "candidate_count": len(candidates), "candidate_sha256": digest(candidates),
               "ranges": {"content_min": float(min(content)), "content_max": float(max(content)),
                          "cf_min": float(min(cf)), "cf_max": float(max(cf)), "epsilon": bundle.epsilon},
               "rows": []}
    for item, score in zip(ranking.item_ids, ranking.scores):
        i = positions[item]
        example["rows"].append({"item_id": item, "content": float(content[i]), "cf": float(cf[i]),
                                "content_norm": float(content_norm[i]), "cf_norm": float(cf_norm[i]), "hybrid": score})
    write_json(output / "hybrid_example.json", example)
    write_json(output / "provenance.json", {
        "report_manifest_sha256": file_hash(report_dir / "manifest.json"),
        "dataset_manifest_sha256": file_hash(dataset.directory / "manifest.json"),
        "script_sha256": file_hash(Path(__file__)), "seed": 20261119,
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="data/processed/amazon-medium-v1")
    parser.add_argument("--reports", default="reports/amazon-medium-v1")
    parser.add_argument("--artifacts", default="artifacts/amazon-medium-v1")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        audit(args.dataset, args.reports, args.artifacts, args.output)
    print("Frozen benchmark audit completed")
