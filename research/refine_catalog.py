"""Derive a cleaned cohort from a verified official subset without redownloading raw data."""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from research.data.dataset import ResearchDataset
from research.data.io import canonical, digest, file_hash, write_json, write_jsonl
from research.data.normalize import AccessoryFilter
from research.data.pipeline import ROOT, export_dataset, finalize, open_staging, prune_core
from research.validate import validate


def refine(parent_dir, output, rules_path, *, allow_synthetic=False, max_items=None):
    parent = ResearchDataset(parent_dir)
    validate(parent.directory)
    kind = parent.manifest["source_kind"]
    if kind != "official_raw" and not allow_synthetic:
        raise ValueError("Only verified official parent datasets may be refined")
    output = Path(output)
    config = json.loads((parent.directory / "config.json").read_text(encoding="utf-8"))
    rules = json.loads(Path(rules_path).read_text(encoding="utf-8"))
    config["preprocessing"]["filter_version"] = rules["version"]
    config["preprocessing"]["derivation"] = (
        "filter_parent_catalog_then_repeat_core_and_temporal_split"
    )
    policy = AccessoryFilter(rules)
    kept, excluded = [], []
    for item in parent.rows("catalog"):
        keep, reason = policy.decide(
            {
                "parent_asin": item["item_id"],
                "title": item["title"],
                "categories": item["categories"],
            }
        )
        if keep:
            kept.append(item)
        else:
            excluded.append(
                {
                    "item_id": item["item_id"],
                    "title": item["title"],
                    "reason": reason,
                    "review_note": rules.get("reviewed_exclusions", {}).get(item["item_id"], ""),
                }
            )
    if max_items is not None:
        if isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 1:
            raise ValueError("max_items must be a positive integer")
        degree = Counter(
            row["item_id"]
            for row in parent.rows("interactions")
            if row["rating"] >= config["dataset"]["positive_rating_min"]
        )
        kept.sort(
            key=lambda item: (
                -degree[item["item_id"]],
                digest([config["seed"], item["item_id"]]),
                item["item_id"],
            )
        )
        for item in kept[max_items:]:
            excluded.append(
                {
                    "item_id": item["item_id"],
                    "title": item["title"],
                    "reason": "seeded_degree_subset",
                }
            )
        kept = kept[:max_items]
        config["preprocessing"]["max_items"] = max_items
        config["preprocessing"]["derivation"] = (
            "filter_then_seeded_degree_subset_then_repeat_core_and_temporal_split"
        )
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    write_json(output / "config.json", config)
    write_json(output / "filter_rules.json", rules)
    write_jsonl(output / "excluded_items.jsonl", excluded)
    derivation = {
        "method": "verified_official_subset_refinement",
        "parent_directory": str(parent.directory.resolve()),
        "parent_manifest_sha256": file_hash(parent.directory / "manifest.json"),
        "original_download_inputs": parent.manifest.get("inputs", []),
        "seed": config["seed"],
        "max_items_before_core": max_items,
        "item_selection": "positive_degree_desc_then_seeded_hash"
        if max_items
        else "all_allowed_parent_items",
        "note": "Reuses normalized parent catalog and all-rating cohort; no source download. Any item subset is selected before fitting models, then core and temporal splits are rebuilt.",
    }
    write_json(output / "derivation.json", derivation)
    connection = open_staging(output / "staging.sqlite3")
    try:
        for item in kept:
            connection.execute(
                "INSERT INTO items VALUES (?,?,?)", (item["item_id"], canonical(item), digest(item))
            )
        kept_ids = {item["item_id"] for item in kept}
        for row in parent.rows("interactions"):
            if row["item_id"] in kept_ids:
                connection.execute(
                    "INSERT INTO reviews VALUES (?,?,?,?,?)",
                    (row["user_id"], row["item_id"], row["rating"], row["timestamp"], digest(row)),
                )
        connection.commit()
        core = prune_core(
            connection,
            config["dataset"]["core_min_user_positives"],
            config["dataset"]["core_min_item_positives"],
            config["dataset"]["positive_rating_min"],
        )
        final = export_dataset(connection, output, config)
        stats = {
            "parent_statistics": parent.manifest["statistics"],
            "excluded_catalog_items": len(excluded),
            "core_iterations": core,
            "final": final,
        }
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    manifest = finalize(
        parent.directory / "catalog.jsonl",
        parent.directory / "interactions.jsonl",
        output,
        config,
        rules,
        stats,
        started,
        kind,
    )
    manifest["derivation"] = derivation
    write_json(output / "manifest.json", manifest)
    validate(output)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parent")
    parser.add_argument("output")
    parser.add_argument("--rules", default=str(ROOT / "research/configs/accessory_filter.json"))
    parser.add_argument("--max-items", type=int)
    args = parser.parse_args()
    refine(args.parent, args.output, args.rules, max_items=args.max_items)
