"""Separate user-holdout experiment; never changes the serving fit or frozen benchmark."""

import argparse
from collections import defaultdict
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from research.data.dataset import ResearchDataset
from research.data.io import digest, file_hash, write_json
from research.evaluation.metrics import topk_metrics
from research.models.recommenders import ALGORITHMS, RecommenderBundle


def user_split(user_ids, seed=42):
    users = sorted(set(user_ids))
    if len(users) < 10:
        raise ValueError("At least ten users are needed for three disjoint groups")
    order = np.random.default_rng(seed).permutation(len(users))
    users = [users[i] for i in order]
    first, second = int(.8 * len(users)), int(.9 * len(users))
    groups = {"fit": sorted(users[:first]), "development": sorted(users[first:second]), "test": sorted(users[second:])}
    assert sum(len(v) for v in groups.values()) == len(set().union(*map(set, groups.values())))
    return groups


def cases(interactions, users, item_ids, known_events):
    by_user = defaultdict(list)
    for row in interactions:
        if row["user_id"] in users:
            by_user[row["user_id"]].append(row)
    result = []
    for user in sorted(users):
        rows = sorted(by_user[user], key=lambda r: (r["timestamp"], r["item_id"]))
        positive = [r for r in rows if r["rating"] >= 4]
        if len(positive) <= known_events:
            continue
        target = positive[known_events]
        history = positive[:known_events]
        if history and max(r["timestamp"] for r in history) >= target["timestamp"]:
            continue
        # Zero history means no prior observations are supplied, including negative ratings.
        seen = {r["item_id"] for r in rows if r["timestamp"] < target["timestamp"]} if known_events else set()
        candidates = [item for item in item_ids if item not in seen]
        assert target["item_id"] in candidates and target["item_id"] not in {r["item_id"] for r in history}
        result.append({"user_id": user, "history": [r["item_id"] for r in history],
                       "target": target["item_id"], "candidates": candidates,
                       "candidate_sha256": digest(candidates)})
    return result


def evaluate(bundle, algorithm, records):
    output = []
    for case in records:
        rank = bundle.rank(algorithm, case["history"], case["candidates"], 10)
        metrics = topk_metrics(rank.item_ids, {case["target"]}, 10)
        output.append({"user_id": case["user_id"], "target": case["target"],
                       "candidate_sha256": case["candidate_sha256"], "ranked_item_ids": rank.item_ids,
                       "fallback_reason": rank.fallback_reason, **metrics})
    return {"users": len(output), "metrics": {key: float(np.mean([r[key] for r in output]))
            for key in ["precision", "recall", "hit_rate", "ndcg"]},
            "fallback_users": sum(bool(r["fallback_reason"]) for r in output), "per_user": output}


def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    dataset = ResearchDataset("data/processed/amazon-medium-v1")
    catalog = list(dataset.rows("catalog"))
    interactions = list(dataset.rows("interactions"))
    groups = user_split([r["user_id"] for r in dataset.rows("users")])
    fit_ids = set(groups["fit"])
    train = [r for r in dataset.rows("train") if r["user_id"] in fit_ids]
    dev = cases(interactions, set(groups["development"]), dataset.item_ids, 1)
    assert set(r["user_id"] for r in train).isdisjoint(groups["development"] + groups["test"])
    protocol = {
        "seed": 42, "user_groups": groups, "fit_interactions": len(train),
        "dataset_manifest_sha256": file_hash(dataset.directory / "manifest.json"),
        "selection": "development users only, one known positive then predict the next positive, nDCG@10 then Hit Rate@10",
        "zero_history": "test users absent from fitting; no observations supplied; first positive is target; full catalog",
        "one_event": "same held-out test users, first positive supplied then predict second positive; exclude earlier observed items",
        "limits": "retrospective fixed catalog/core/metadata; no common global time cutoff; first-positive labels are Amazon ratings, not live customer satisfaction; distinct targets in the two scenarios, so their metric difference is not a causal effect of collecting one event",
        "grids": {"ngram": [[1, 1], [1, 2]], "min_df": [1, 2], "neighbors": [20, 50, 100], "alpha": [.25, .5, .75]},
    }
    write_json(output / "protocol_before_test.json", protocol)
    trials = []
    def trial(algorithm, **params):
        model = RecommenderBundle(**params).fit(catalog, train)
        result = evaluate(model, algorithm, dev)
        trials.append({"algorithm": algorithm, "parameters": params, "metrics": result["metrics"]})
        return model, result["metrics"]
    def best(records):
        return max(records, key=lambda x: (x[1]["ndcg"], x[1]["hit_rate"]))[0]
    content = best([trial("content", ngram_range=ngram, min_df=minimum) for ngram in [(1, 1), (1, 2)] for minimum in [1, 2]])
    cf = best([trial("item_cf", neighbors=n) for n in [20, 50, 100]])
    hybrid = best([trial("hybrid", ngram_range=content.ngram_range, min_df=content.min_df,
                         neighbors=cf.neighbors, alpha=a) for a in [.25, .5, .75]])
    models = {"popularity": hybrid, "content": content, "item_cf": cf, "hybrid": hybrid}
    write_json(output / "selected_before_test.json", {"trials": trials,
        "content": {"ngram_range": content.ngram_range, "min_df": content.min_df},
        "neighbors": cf.neighbors, "alpha": hybrid.alpha, "selected_on": "disjoint development users"})
    results = {}
    for name, known in [("zero_history", 0), ("one_event", 1)]:
        records = cases(interactions, set(groups["test"]), dataset.item_ids, known)
        results[name] = {algorithm: evaluate(models[algorithm], algorithm, records) for algorithm in ALGORITHMS}
        if known == 0:
            baseline = results[name]["popularity"]["per_user"]
            for algorithm in ALGORITHMS:
                assert [r["ranked_item_ids"] for r in results[name][algorithm]["per_user"]] == [r["ranked_item_ids"] for r in baseline]
    write_json(output / "results.json", results)
    write_json(output / "provenance.json", {"script_sha256": file_hash(Path(__file__)),
        "dataset_manifest_sha256": protocol["dataset_manifest_sha256"],
        "protocol_sha256": file_hash(output / "protocol_before_test.json"),
        "selection_sha256": file_hash(output / "selected_before_test.json"),
        "active_artifact_modified": False})
    print({name: {a: r["metrics"] for a, r in methods.items()} for name, methods in results.items()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    with threadpool_limits(limits=1):
        run(parser.parse_args().output)
