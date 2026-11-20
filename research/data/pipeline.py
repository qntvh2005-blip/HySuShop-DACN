"""Disk-backed Amazon preprocessing. No Django database or website events are used."""

import argparse
import gzip
import json
import os
import platform
import sqlite3
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from research.data.io import canonical, digest, file_hash, read_jsonl, write_json, write_jsonl
from research.data.normalize import AccessoryFilter, normalize_metadata, normalize_review

ROOT = Path(__file__).resolve().parents[2]


def log(message):
    print(message, flush=True)


def counts(connection, positive_min):
    indexes = {
        r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }
    if {"review_user_rating", "review_item_rating"} <= indexes:
        # Separate covering-index scans avoid two huge DISTINCT temporary B-trees.
        positives = connection.execute(
            "SELECT COUNT(*) FROM reviews INDEXED BY review_user_rating WHERE rating >= ?",
            (positive_min,),
        ).fetchone()[0]
        users = connection.execute(
            "SELECT COUNT(*) FROM (SELECT user_id FROM reviews INDEXED BY review_user_rating WHERE rating >= ? GROUP BY user_id)",
            (positive_min,),
        ).fetchone()[0]
        items = connection.execute(
            "SELECT COUNT(*) FROM (SELECT item_id FROM reviews INDEXED BY review_item_rating WHERE rating >= ? GROUP BY item_id)",
            (positive_min,),
        ).fetchone()[0]
        return {"positives": positives, "users": users, "items": items}
    row = connection.execute(
        "SELECT COUNT(*), COUNT(DISTINCT user_id), COUNT(DISTINCT item_id) FROM reviews WHERE rating >= ?",
        (positive_min,),
    ).fetchone()
    return {"positives": row[0], "users": row[1], "items": row[2]}


def prune_core(connection, user_min=5, item_min=5, positive_min=4):
    """Delete all ratings of unsupported users/items; iterate until fixed point."""
    history = []
    while True:
        before = connection.total_changes
        connection.execute("DROP TABLE IF EXISTS keep_users")
        connection.execute(
            "CREATE TEMP TABLE keep_users AS SELECT user_id FROM reviews WHERE rating >= ? GROUP BY user_id HAVING COUNT(*) >= ?",
            (positive_min, user_min),
        )
        connection.execute("CREATE UNIQUE INDEX keep_users_id ON keep_users(user_id)")
        connection.execute(
            "DELETE FROM reviews WHERE user_id NOT IN (SELECT user_id FROM keep_users)"
        )
        connection.execute("DROP TABLE IF EXISTS keep_items")
        connection.execute(
            "CREATE TEMP TABLE keep_items AS SELECT item_id FROM reviews WHERE rating >= ? GROUP BY item_id HAVING COUNT(*) >= ?",
            (positive_min, item_min),
        )
        connection.execute("CREATE UNIQUE INDEX keep_items_id ON keep_items(item_id)")
        connection.execute(
            "DELETE FROM reviews WHERE item_id NOT IN (SELECT item_id FROM keep_items)"
        )
        connection.commit()
        changed = connection.total_changes - before
        state = counts(connection, positive_min)
        history.append(state)
        log(f"core iteration {len(history)}: {state}")
        if not changed or not state["positives"]:
            break
    return history


def configure_temporary_directory():
    # Keep this project's sort/index spill files off the Windows system drive.
    temporary = ROOT / ".local" / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(temporary)
    os.environ["TMP"] = str(temporary)
    os.environ["SQLITE_TMPDIR"] = str(temporary)
    tempfile.tempdir = str(temporary)


def open_staging(path):
    configure_temporary_directory()
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA cache_size=-65536")
    connection.execute("PRAGMA temp_store=FILE")
    connection.executescript("""
        CREATE TABLE items (item_id TEXT PRIMARY KEY, payload TEXT NOT NULL, tie_hash TEXT NOT NULL);
        CREATE TABLE reviews (user_id TEXT NOT NULL, item_id TEXT NOT NULL, rating REAL NOT NULL,
          timestamp INTEGER NOT NULL, tie_hash TEXT NOT NULL, PRIMARY KEY(user_id,item_id)) WITHOUT ROWID;
    """)
    return connection


def ingest_metadata(connection, source, accessory_filter, output):
    stats = Counter()
    with gzip.open(
        output / "metadata_audit.jsonl.gz", "wt", encoding="utf-8", newline="\n"
    ) as audit:
        for number, record in enumerate(read_jsonl(source), 1):
            keep, reason = accessory_filter.decide(record)
            stats[reason] += 1
            audit.write(
                canonical(
                    {
                        "item_id": record.get("parent_asin"),
                        "title": record.get("title"),
                        "kept": keep,
                        "reason": reason,
                    }
                )
                + "\n"
            )
            if keep:
                normalized = normalize_metadata(record)
                connection.execute(
                    """INSERT INTO items VALUES (?,?,?) ON CONFLICT(item_id) DO UPDATE SET
                    payload=excluded.payload, tie_hash=excluded.tie_hash WHERE excluded.tie_hash > items.tie_hash""",
                    (normalized["item_id"], canonical(normalized), digest(normalized)),
                )
            if number % 50000 == 0:
                connection.commit()
                log(f"metadata: {number:,} records")
    connection.commit()
    stats["unique_items_kept"] = connection.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    return dict(stats)


def ingest_reviews(connection, source):
    valid_items = {row[0] for row in connection.execute("SELECT item_id FROM items")}
    stats = Counter()
    batch = []
    statement = """INSERT INTO reviews VALUES (?,?,?,?,?) ON CONFLICT(user_id,item_id) DO UPDATE SET
        rating=excluded.rating, timestamp=excluded.timestamp, tie_hash=excluded.tie_hash
        WHERE excluded.timestamp > reviews.timestamp OR
        (excluded.timestamp = reviews.timestamp AND excluded.tie_hash > reviews.tie_hash)"""
    for number, raw in enumerate(read_jsonl(source), 1):
        stats["raw_records"] += 1
        if raw.get("parent_asin") not in valid_items:
            stats["outside_filtered_catalog"] += 1
            continue
        record = normalize_review(raw)
        if record is None:
            stats["invalid_records"] += 1
            continue
        stats["valid_matching_records"] += 1
        if "timestamp" not in raw and "sort_timestamp" in raw:
            stats["sort_timestamp_fallback"] += 1
        batch.append(
            tuple(record[k] for k in ["user_id", "item_id", "rating", "timestamp", "tie_hash"])
        )
        if len(batch) >= 10000:
            connection.executemany(statement, batch)
            connection.commit()
            batch.clear()
        if number % 500000 == 0:
            log(f"reviews: {number:,} scanned; {stats['valid_matching_records']:,} matching")
    if batch:
        connection.executemany(statement, batch)
    connection.commit()
    stats["deduplicated_records"] = connection.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    stats["duplicate_records_removed"] = (
        stats["valid_matching_records"] - stats["deduplicated_records"]
    )
    return dict(stats)


def subset(connection, config):
    dataset = config["dataset"]
    positive = dataset["positive_rating_min"]
    settings = config["preprocessing"]
    seed = config["seed"]
    connection.create_function(
        "seed_order", 1, lambda value: digest([seed, value]), deterministic=True
    )
    steps = []
    for column, limit in [("item_id", settings["max_items"]), ("user_id", settings["max_users"])]:
        if limit:
            # Dense item shortlist, deterministic randomized ties; seeded user shortlist.
            order = (
                "COUNT(*) DESC, seed_order(item_id), item_id"
                if column == "item_id"
                else "seed_order(user_id), user_id"
            )
            connection.execute("DROP TABLE IF EXISTS subset_ids")
            connection.execute(
                f"CREATE TEMP TABLE subset_ids AS SELECT {column} AS id FROM reviews WHERE rating >= ? GROUP BY {column} ORDER BY {order} LIMIT ?",
                (positive, limit),
            )
            connection.execute("CREATE UNIQUE INDEX subset_id ON subset_ids(id)")
            connection.execute(
                f"DELETE FROM reviews WHERE {column} NOT IN (SELECT id FROM subset_ids)"
            )
            connection.commit()
            steps.append(
                {
                    "column": column,
                    "limit": limit,
                    "after_selection": counts(connection, positive),
                    "core": prune_core(
                        connection,
                        dataset["core_min_user_positives"],
                        dataset["core_min_item_positives"],
                        positive,
                    ),
                }
            )
    return steps


def export_dataset(connection, output, config):
    positive = config["dataset"]["positive_rating_min"]
    # Freeze catalog before ambiguous-user exclusion, as specified in protocol v1.
    item_ids = [
        r[0]
        for r in connection.execute(
            "SELECT DISTINCT item_id FROM reviews WHERE rating >= ? ORDER BY item_id", (positive,)
        )
    ]
    if not item_ids:
        raise ValueError(
            "No positive core survived; adjust documented subset/filter policy, not hidden thresholds"
        )
    catalog = [
        json.loads(
            connection.execute("SELECT payload FROM items WHERE item_id=?", (item,)).fetchone()[0]
        )
        for item in item_ids
    ]
    write_jsonl(output / "catalog.jsonl", catalog)
    write_json(output / "item_index.json", item_ids)
    train, development, test, stage_rows, users, interactions, excluded = [], [], [], [], [], [], []
    positive_count = 0
    candidate_sizes = []
    for (user,) in connection.execute(
        "SELECT DISTINCT user_id FROM reviews ORDER BY user_id"
    ).fetchall():
        history = [
            {"user_id": user, "item_id": item, "rating": rating, "timestamp": timestamp}
            for item, rating, timestamp in connection.execute(
                "SELECT item_id,rating,timestamp FROM reviews WHERE user_id=? ORDER BY timestamp,item_id",
                (user,),
            )
        ]
        positives = [r for r in history if r["rating"] >= positive]
        if len(positives) < 3:
            raise ValueError("User without enough positives after core")
        training, dev, target = positives[:-2], positives[-2], positives[-1]
        if not training[-1]["timestamp"] < dev["timestamp"] < target["timestamp"]:
            excluded.append({"user_id": user, "reason": "non_strict_split_boundary"})
            continue
        user_train_ids = {r["item_id"] for r in training}
        group = (
            "sparse"
            if len(training) <= config["evaluation"]["sparse_train_positives"][1]
            else "active"
        )
        users.append({"user_id": user, "train_positives": len(training), "group": group})
        train.extend(training)
        development.append(dev)
        test.append(target)
        interactions.extend(history)
        positive_count += len(positives)
        for stage, heldout in [("development", dev), ("test", target)]:
            seen = sorted(r["item_id"] for r in history if r["timestamp"] < heldout["timestamp"])
            seen_set = set(seen)
            candidates = [item for item in item_ids if item not in seen_set]
            if heldout["item_id"] not in candidates or user_train_ids & set(candidates):
                raise ValueError("Candidate/history leakage")
            candidate_sizes.append(len(candidates))
            # Store compact complement + hash. Shared loader expands the exact full candidate list.
            stage_rows.append(
                {
                    "user_id": user,
                    "stage": stage,
                    "target_item_id": heldout["item_id"],
                    "target_timestamp": heldout["timestamp"],
                    "seen_item_ids": seen,
                    "candidate_count": len(candidates),
                    "candidate_sha256": digest(candidates),
                }
            )
    if not users:
        raise ValueError("No users with unambiguous chronological split")
    for filename, rows in [
        ("train.jsonl", train),
        ("development.jsonl", development),
        ("test.jsonl", test),
        ("users.jsonl", users),
        ("interactions.jsonl", interactions),
        ("candidates.jsonl", stage_rows),
        ("excluded_users.jsonl", excluded),
    ]:
        write_jsonl(output / filename, rows)
    group_counts = dict(Counter(r["group"] for r in users))
    post_item_counts = Counter(r["item_id"] for r in train + development + test)
    return {
        "users": len(users),
        "items": len(item_ids),
        "positives": positive_count,
        "all_ratings": len(interactions),
        "train_positives": len(train),
        "development_positives": len(development),
        "test_positives": len(test),
        "excluded_ambiguous_users": len(excluded),
        "groups": group_counts,
        "positive_sparsity": 1 - positive_count / (len(users) * len(item_ids)),
        "min_candidates": min(candidate_sizes),
        "max_candidates": max(candidate_sizes),
        "stage_user_pairs_below_k10": sum(n < 10 for n in candidate_sizes),
        "items_below_core_after_boundary_exclusion": sum(
            post_item_counts[item] < config["dataset"]["core_min_item_positives"]
            for item in item_ids
        ),
    }


def prepare(
    metadata,
    reviews,
    output,
    config_path=ROOT / "research/configs/experiment.json",
    filter_path=ROOT / "research/configs/accessory_filter.json",
    source_kind="official_raw",
):
    metadata, reviews, output = Path(metadata), Path(reviews), Path(output)
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    rules = json.loads(Path(filter_path).read_text(encoding="utf-8"))
    if config["split"]["refit_on_train_dev"] or config["split"]["test_profile"] != "train_only":
        raise ValueError("Pipeline v1 supports only frozen train protocol")
    for path in [metadata, reviews]:
        if not path.is_file():
            raise ValueError(f"Input not available: {path.name}")
        if source_kind == "official_raw":
            receipt_path = path.with_suffix(path.suffix + ".source.json")
            if not receipt_path.is_file():
                raise ValueError("Official inputs require download source receipts")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("status") != "complete" or receipt.get("bytes") != path.stat().st_size:
                raise ValueError("Official source is incomplete or changed")
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    write_json(output / "config.json", config)
    write_json(output / "filter_rules.json", rules)
    write_json(output / "run_status.json", {"status": "in_progress", "source_kind": source_kind})
    connection = open_staging(output / "staging.sqlite3")
    try:
        stats = {"metadata": ingest_metadata(connection, metadata, AccessoryFilter(rules), output)}
        stats["reviews"] = ingest_reviews(connection, reviews)
        log("Creating positive-feedback indexes")
        # Indexes include rating to support configurable positive threshold without hardcoded partial-index predicates.
        connection.execute("CREATE INDEX review_user_rating ON reviews(user_id,rating)")
        connection.execute("CREATE INDEX review_item_rating ON reviews(item_id,rating)")
        dataset = config["dataset"]
        stats["before_core"] = counts(connection, dataset["positive_rating_min"])
        stats["full_core"] = prune_core(
            connection,
            dataset["core_min_user_positives"],
            dataset["core_min_item_positives"],
            dataset["positive_rating_min"],
        )
        stats["subset_steps"] = subset(connection, config)
        stats["final"] = export_dataset(connection, output, config)
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    return finalize(metadata, reviews, output, config, rules, stats, started, source_kind)


def finalize(metadata, reviews, output, config, rules, stats, started, source_kind):
    write_json(output / "statistics.json", stats)
    inputs = []
    for path in [metadata, reviews]:
        receipt_path = path.with_suffix(path.suffix + ".source.json")
        receipt = (
            json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else None
        )
        checksum = file_hash(path)
        if receipt and (receipt.get("status") != "complete" or receipt.get("sha256") != checksum):
            raise ValueError(f"Source receipt invalid: {path.name}")
        inputs.append(
            {
                "filename": path.name,
                "bytes": path.stat().st_size,
                "sha256": checksum,
                "receipt": receipt,
            }
        )
    outputs = {
        p.name: file_hash(p)
        for p in sorted(output.iterdir())
        if p.suffix in {".jsonl", ".json"} and p.name != "run_status.json"
    }
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL, text=True
        ).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        revision = None
    code_hashes = {
        str(p.relative_to(ROOT)).replace("\\", "/"): file_hash(p)
        for p in sorted((ROOT / "research").rglob("*.py"))
    }
    manifest = {
        "status": "complete",
        "source_kind": source_kind,
        "protocol_version": config["protocol_version"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": config["seed"],
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "git_revision": revision,
        "code_sha256": code_hashes,
        "inputs": inputs,
        "outputs": outputs,
        "config_sha256": digest(config),
        "filter_sha256": digest(rules),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "statistics": stats["final"],
    }
    write_json(output / "manifest.json", manifest)
    write_json(output / "run_status.json", {"status": "complete", "source_kind": source_kind})
    log(f"Complete: {canonical(stats['final'])}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("data/raw/amazon-2023/meta_Cell_Phones_and_Accessories.jsonl.gz"),
    )
    parser.add_argument(
        "--reviews",
        type=Path,
        default=Path("data/raw/amazon-2023/Cell_Phones_and_Accessories.jsonl.gz"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "research/configs/experiment.json")
    parser.add_argument(
        "--filter", type=Path, default=ROOT / "research/configs/accessory_filter.json"
    )
    parser.add_argument(
        "--source-kind", choices=["official_raw", "synthetic_fixture"], default="official_raw"
    )
    args = parser.parse_args()
    prepare(args.metadata, args.reviews, args.output, args.config, args.filter, args.source_kind)


if __name__ == "__main__":
    main()
