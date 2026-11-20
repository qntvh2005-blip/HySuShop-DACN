"""Replay de-identified recorded serving cases without fitting or changing the live DB."""

import argparse
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from research.data.io import digest, file_hash, write_json
from research.models.artifacts import load_bundle
from research.models.recommenders import minmax


def audit(snapshot, artifact, output):
    import json

    snapshot, artifact, output = Path(snapshot), Path(artifact), Path(output)
    if output.exists():
        raise ValueError("Use a fresh output file")
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    bundle, manifest = load_bundle(artifact)
    assert data["model_version"] == manifest["model_version"]
    assert data["bundle_sha256"] == manifest["bundle_sha256"]
    results = []
    for case in data["cases"]:
        candidates, weights = case["candidate_ids"], case["history_weights"]
        assert candidates and len(candidates) == case["candidate_count"]
        assert digest(candidates) == case["candidate_sha256"]
        history = list(weights)
        assert case["context"] in {"personalized", "popular"}
        assert case["algorithm"] in {"hybrid", "popularity"}
        assert not case["fallback_reason"]
        assert case["alpha"] == bundle.alpha
        content, cf = bundle.component_scores(history, candidates, weights)
        cn, fn = minmax(content, bundle.epsilon), minmax(cf, bundle.epsilon)
        pos = candidates.index(case["item_id"])
        ranked = bundle.rank(case["algorithm"], history, candidates, len(candidates), history_weights=weights)
        assert ranked.item_ids.index(case["item_id"]) + 1 == case["rank"]
        stored = case["scores"]
        checks = {
            "content_score": float(content[pos]), "cf_score": float(cf[pos]),
            "content_normalized": float(cn[pos]), "cf_normalized": float(fn[pos]),
            "score": float(ranked.scores[case["rank"] - 1]),
        }
        errors = {key: abs(value - stored[key]) for key, value in checks.items()}
        assert all(error < 1e-10 for error in errors.values()), errors
        for source in stored["sources"]:
            assert source["item_id"] in weights and source["weight"] == weights[source["item_id"]]
            a, b = bundle.item_index[source["item_id"]], bundle.item_index[case["item_id"]]
            assert np.isclose((bundle.item_vectors[a] @ bundle.item_vectors[b].T).toarray()[0, 0], source["content_similarity"])
            assert np.isclose(float(bundle.cf_neighbors[a, b]), source["cf_similarity"])
        comparison = {}
        for algorithm in ["content", "item_cf", "popularity"]:
            ranks = bundle.rank(algorithm, history, candidates, len(candidates), history_weights=weights)
            comparison[algorithm] = ranks.item_ids.index(case["item_id"]) + 1
        results.append({
            "case": case["case"], "source_log_id": case["source_log_id"],
            "kind": case["kind"], "item_id": case["item_id"], "rank": case["rank"],
            "candidate_count": len(candidates), "checks_passed": True,
            "max_absolute_score_error": max(errors.values()),
            "content_contribution": float(bundle.alpha * cn[pos]) if case["algorithm"] == "hybrid" else None,
            "cf_contribution": float((1 - bundle.alpha) * fn[pos]) if case["algorithm"] == "hybrid" else None,
            "component_only_ranks": comparison,
            "popularity_train_users": float(bundle.popularity[bundle.item_index[case["item_id"]]]),
        })
    write_json(output, {
        "cases_checked": len(results), "all_passed": True,
        "scope": "Replayed fixed recorded cases and full stored candidate pools; score, normalization, rank and retained source-link checks only. Deliberately selected examples, not causal explanations, aggregate accuracy, usefulness or user-understanding measurements. No training, activation or live database writes.",
        "snapshot_sha256": file_hash(snapshot), "script_sha256": file_hash(Path(__file__)),
        "bundle_sha256": manifest["bundle_sha256"], "results": results,
    })
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        for result in audit(args.snapshot, args.artifact, args.output):
            print(result)
