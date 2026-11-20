"""Development-only selection followed by locked, train-only top-K test evaluation."""

import argparse
import csv
import json
import os
import platform
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from research.data.dataset import ResearchDataset
from research.data.io import file_hash, write_json, write_jsonl
from research.evaluation.metrics import topk_metrics
from research.models.artifacts import save_bundle
from research.models.recommenders import ALGORITHMS, RecommenderBundle
from research.validate import validate


def summarize(rows, ks):
    result = {}
    for group in ["all", "sparse", "active"]:
        members = rows if group == "all" else [row for row in rows if row["group"] == group]
        result[group] = {
            "users": len(members),
            "fallback_users": sum(bool(r["fallback_reason"]) for r in members),
        }
        for k in ks:
            for metric in ["precision", "recall", "ndcg", "hit_rate"]:
                key = f"{metric}@{k}"
                result[group][key] = (
                    float(np.mean([row[key] for row in members])) if members else None
                )
        durations = [value for row in members for value in row["timings_ms"]]
        result[group]["mean_ms"] = float(np.mean(durations)) if durations else None
        result[group]["p95_ms"] = float(np.percentile(durations, 95)) if durations else None
    return result


def evaluate(bundle, algorithm, dataset, stage, config, *, timing=False):
    if stage not in {"development", "test"}:
        raise ValueError("Invalid evaluation stage")
    users = {row["user_id"]: row for row in dataset.rows("users")}
    ks = config["evaluation"]["k"]
    cases = [
        (target, dataset.candidates(target["user_id"], stage)) for target in dataset.rows(stage)
    ]
    if timing:
        for target, candidates in cases[: config["evaluation"]["timing_warmup_users_max"]]:
            bundle.rank(algorithm, bundle.histories.get(target["user_id"], []), candidates, max(ks))
    output = []
    for target, candidates in cases:
        user = target["user_id"]
        history = bundle.histories.get(user, [])
        durations = []
        ranked = None
        repeats = config["evaluation"]["timing_repeats"] if timing else 1
        for _ in range(repeats):
            started = time.perf_counter()
            result = bundle.rank(algorithm, history, candidates, max(ks))
            elapsed = 1000 * (time.perf_counter() - started)
            if ranked is not None and ranked != result.item_ids:
                raise ValueError("Non-reproducible ranking across timing repeats")
            ranked = result.item_ids
            if timing:
                durations.append(elapsed)
        row = {
            "user_id": user,
            "stage": stage,
            "algorithm": algorithm,
            "group": users[user]["group"],
            "candidate_sha256": dataset.candidate_records[(stage, user)]["candidate_sha256"],
            "candidate_count": len(candidates),
            "ranked_item_ids": ranked,
            "fallback_reason": result.fallback_reason,
            "timings_ms": durations,
        }
        for k in ks:
            row.update(
                {
                    f"{metric}@{k}": value
                    for metric, value in topk_metrics(ranked, {target["item_id"]}, k).items()
                }
            )
        output.append(row)
    return summarize(output, ks), output


def select_best(trials):
    if not trials or any(trial["stage"] != "development" for trial in trials):
        raise ValueError("Parameters may only be selected from development metrics")
    # max is stable: first grid config wins exact metric ties.
    return max(
        trials,
        key=lambda trial: (
            trial["metrics"]["all"]["ndcg@10"],
            trial["metrics"]["all"]["hit_rate@10"],
        ),
    )


def run_experiment(dataset_dir, report_dir, artifact_dir, allow_synthetic=False):
    dataset = ResearchDataset(dataset_dir)
    if dataset.manifest["source_kind"] != "official_raw" and not allow_synthetic:
        raise ValueError("Synthetic fixtures cannot be reported as real benchmark results")
    validate(dataset_dir)
    config = json.loads((dataset.directory / "config.json").read_text(encoding="utf-8"))
    if config["split"]["refit_on_train_dev"] or config["split"]["test_profile"] != "train_only":
        raise ValueError("Only the frozen train protocol is supported")
    report_dir, artifact_dir = Path(report_dir), Path(artifact_dir)
    if artifact_dir.exists():
        raise FileExistsError("Artifact output already exists")
    report_dir.mkdir(parents=True, exist_ok=False)
    write_json(
        report_dir / "status.json",
        {"stage": "tuning_development", "source_kind": dataset.manifest["source_kind"]},
    )
    catalog, train = list(dataset.rows("catalog")), list(dataset.rows("train"))
    models = config["models"]
    trials = []
    fit_times = []

    def fit(**parameters):
        start = time.perf_counter()
        model = RecommenderBundle(**parameters).fit(
            catalog, train, config["dataset"]["positive_rating_min"]
        )
        fit_times.append({"parameters": parameters, "seconds": time.perf_counter() - start})
        return model

    def trial(model, algorithm, parameters):
        metrics, _ = evaluate(model, algorithm, dataset, "development", config)
        record = {
            "stage": "development",
            "algorithm": algorithm,
            "parameters": parameters,
            "metrics": metrics,
        }
        trials.append(record)
        print(
            f"development {algorithm} {parameters}: nDCG@10={metrics['all']['ndcg@10']:.6f}",
            flush=True,
        )
        return record

    with threadpool_limits(limits=config["evaluation"]["threads"]):
        content_trials = []
        for ngram in models["content"]["ngram_grid"]:
            for min_df in models["content"]["min_df_grid"]:
                parameters = {"ngram_range": ngram, "min_df": min_df}
                try:
                    content_trials.append(trial(fit(**parameters), "content", parameters))
                except ValueError as error:
                    # A genuinely unusable vocabulary is a failed grid point, not a test-driven change.
                    if (
                        "empty vocabulary" not in str(error)
                        and "no terms remain" not in str(error).lower()
                    ):
                        raise
                    trials.append(
                        {
                            "stage": "development",
                            "algorithm": "content",
                            "parameters": parameters,
                            "error": str(error),
                        }
                    )
        content_parameters = select_best(content_trials)["parameters"]
        cf_trials = []
        for neighbors in models["item_cf"]["neighbors_grid"]:
            model = fit(**content_parameters, neighbors=neighbors)
            cf_trials.append(trial(model, "item_cf", {"neighbors": neighbors}))
        cf_parameters = select_best(cf_trials)["parameters"]
        bundle = fit(**content_parameters, **cf_parameters, epsilon=models["hybrid"]["epsilon"])
        hybrid_trials = []
        for alpha in models["hybrid"]["alpha_grid"]:
            bundle.alpha = alpha
            hybrid_trials.append(trial(bundle, "hybrid", {"alpha": alpha}))
        bundle.alpha = select_best(hybrid_trials)["parameters"]["alpha"]
        # Re-evaluate selected algorithms on dev to choose the serving algorithm before test.
        serving_trials = [trial(bundle, algorithm, {}) for algorithm in ALGORITHMS]
        serving_algorithm = select_best(serving_trials)["algorithm"]
        locked = {
            "selected_on": "development",
            "content": content_parameters,
            "item_cf": cf_parameters,
            "alpha": bundle.alpha,
            "serving_algorithm": serving_algorithm,
            "refit": False,
            "dataset_manifest_sha256": file_hash(dataset.directory / "manifest.json"),
            "source_kind": dataset.manifest["source_kind"],
            "protocol_version": config["protocol_version"],
        }
        write_json(report_dir / "development_grid.json", trials)
        write_json(report_dir / "locked_config.json", locked)
        write_json(
            report_dir / "status.json",
            {"stage": "evaluating_test", "source_kind": dataset.manifest["source_kind"]},
        )
        summaries, per_user = {}, []
        for algorithm in ALGORITHMS:
            summaries[algorithm], rows = evaluate(
                bundle, algorithm, dataset, "test", config, timing=True
            )
            per_user.extend(rows)
            print(
                f"test {algorithm}: nDCG@10={summaries[algorithm]['all']['ndcg@10']:.6f}",
                flush=True,
            )
    write_json(report_dir / "test_metrics.json", summaries)
    write_jsonl(report_dir / "test_per_user.jsonl", per_user)
    write_json(report_dir / "fit_times.json", fit_times)
    records = [
        {"algorithm": algorithm, "group": group, **values}
        for algorithm, groups in summaries.items()
        for group, values in groups.items()
    ]
    with (report_dir / "test_metrics.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    artifact_manifest = save_bundle(
        bundle,
        artifact_dir,
        {
            "locked_config": locked,
            "model_version": artifact_dir.name,
            "serving_algorithm": serving_algorithm,
            "source_kind": dataset.manifest["source_kind"],
        },
    )
    metadata = {
        "status": "complete",
        "source_kind": dataset.manifest["source_kind"],
        "locked_config": locked,
        "dataset_directory": str(dataset.directory.resolve()),
        "artifact_directory": str(artifact_dir.resolve()),
        "artifact_bundle_sha256": artifact_manifest["bundle_sha256"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "threads": config["evaluation"]["threads"],
        "timing_scope": "warm scoring and top-10 ranking; excludes DB/load/fit/candidate expansion",
        "dependencies": {
            name: version(name)
            for name in ["numpy", "scipy", "scikit-learn", "pandas", "joblib", "threadpoolctl"]
        },
        "outputs": {
            p.name: file_hash(p)
            for p in report_dir.iterdir()
            if p.is_file() and p.name != "status.json"
        },
    }
    write_json(report_dir / "manifest.json", metadata)
    write_json(
        report_dir / "status.json",
        {"stage": "complete", "source_kind": dataset.manifest["source_kind"]},
    )
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset")
    parser.add_argument("--reports", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--allow-synthetic", action="store_true")
    args = parser.parse_args()
    run_experiment(args.dataset, args.reports, args.artifacts, args.allow_synthetic)
