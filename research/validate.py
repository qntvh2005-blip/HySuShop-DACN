"""Audit dataset integrity and chronological histories independently of model fitting."""

import argparse
from collections import defaultdict

from research.data.dataset import ResearchDataset


def validate(directory):
    dataset = ResearchDataset(directory)
    config = __import__("json").loads(
        (dataset.directory / "config.json").read_text(encoding="utf-8")
    )
    positive = config["dataset"]["positive_rating_min"]
    catalog_ids = [row["item_id"] for row in dataset.rows("catalog")]
    if catalog_ids != sorted(set(catalog_ids)) or catalog_ids != dataset.item_ids:
        raise ValueError("Catalog and item index differ or contain duplicates")
    interactions = defaultdict(list)
    unique_pairs = set()
    for row in dataset.rows("interactions"):
        key = (row["user_id"], row["item_id"])
        if key in unique_pairs or row["item_id"] not in dataset.item_ids:
            raise ValueError("Duplicate user-item or unmapped interaction")
        unique_pairs.add(key)
        interactions[row["user_id"]].append(row)
    train = defaultdict(list)
    for row in dataset.rows("train"):
        if row["rating"] < positive:
            raise ValueError("Negative interaction in train")
        train[row["user_id"]].append(row)
    users = {r["user_id"]: r for r in dataset.rows("users")}
    if set(users) != set(train) or set(users) != set(interactions):
        raise ValueError("User cohort differs across files")
    targets = {
        stage: {r["user_id"]: r for r in dataset.rows(stage)} for stage in ["development", "test"]
    }
    for user in users:
        history = interactions[user]
        dev, test = targets["development"][user], targets["test"][user]
        positives = sorted(
            [r for r in history if r["rating"] >= positive],
            key=lambda r: (r["timestamp"], r["item_id"]),
        )
        actual_train = sorted(train[user], key=lambda r: (r["timestamp"], r["item_id"]))
        if actual_train != positives[:-2] or dev != positives[-2] or test != positives[-1]:
            raise ValueError("Split differs from positive leave-last-two-out")
        if not max(r["timestamp"] for r in actual_train) < dev["timestamp"] < test["timestamp"]:
            raise ValueError("Non-strict chronological split")
        if users[user]["train_positives"] != len(actual_train):
            raise ValueError("User interaction group count mismatch")
        for stage in ["development", "test"]:
            target = targets[stage][user]
            record = dataset.candidate_records[(stage, user)]
            expected_seen = sorted(
                r["item_id"] for r in history if r["timestamp"] < target["timestamp"]
            )
            if (
                record["seen_item_ids"] != expected_seen
                or record["target_item_id"] != target["item_id"]
                or record["target_timestamp"] != target["timestamp"]
            ):
                raise ValueError("Observed seen history/target differs from source interactions")
            dataset.candidates(user, stage)
    return {
        "status": "passed",
        "users": len(users),
        "items": len(dataset.item_ids),
        "user_stage_pairs": len(dataset.candidate_records),
        "source_kind": dataset.manifest["source_kind"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset")
    args = parser.parse_args()
    print(validate(args.dataset))
