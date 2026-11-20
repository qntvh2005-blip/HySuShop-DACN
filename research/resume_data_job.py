"""Recover the fully ingested staging database without reading/inserting reviews again."""

import json
import os
import sqlite3
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone

from research.data.io import file_hash, write_json
from research.data.pipeline import (
    ROOT,
    configure_temporary_directory,
    counts,
    export_dataset,
    finalize,
    prune_core,
    subset,
)
from research.validate import validate


def main():
    job = ROOT / "reports/data-job"
    output = ROOT / "data/processed/amazon-v2"
    raw = ROOT / "data/raw/amazon-2023-hf"
    lock = job / "job.lock"
    with lock.open("x", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    status = {
        "pid": os.getpid(),
        "dataset": str(output),
        "raw_dir": str(raw),
        "recovery": "reuse_completed_ingestion",
    }

    def update(stage, **extra):
        status.update(stage=stage, updated_at_utc=datetime.now(timezone.utc).isoformat(), **extra)
        write_json(job / "status.json", status)

    configure_temporary_directory()
    connection = sqlite3.connect(output / "staging.sqlite3", timeout=30)
    connection.execute("PRAGMA cache_size=-524288")
    connection.execute("PRAGMA temp_store=FILE")
    try:
        indexes = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        if not {"review_user_rating", "review_item_rating"} <= indexes:
            raise ValueError(
                "Recovery requires completed review ingestion and both committed indexes"
            )
        if (output / "manifest.json").exists():
            raise ValueError("Refusing to modify an already finalized dataset")
        update("filtering_core")
        config = json.loads((ROOT / "research/configs/experiment.json").read_text(encoding="utf-8"))
        rules = json.loads((output / "filter_rules.json").read_text(encoding="utf-8"))
        if rules["version"] != config["preprocessing"]["filter_version"]:
            raise ValueError("Recovered metadata filter differs from requested version")
        write_json(output / "config.json", config)
        started = time.perf_counter()
        dataset = config["dataset"]
        stats = {
            "ingestion": {
                "status": "recovered_completed_ingestion",
                "raw_ingestion_counters": None,
                "note": "Original in-memory ingestion counters were unavailable after recovery; no counts invented.",
            }
        }
        stats["before_core"] = counts(connection, dataset["positive_rating_min"])
        print(f"Recovered staging: {stats['before_core']}", flush=True)
        stats["full_core"] = prune_core(
            connection,
            dataset["core_min_user_positives"],
            dataset["core_min_item_positives"],
            dataset["positive_rating_min"],
        )
        update("selecting_subset")
        stats["subset_steps"] = subset(connection, config)
        update("exporting_splits")
        stats["final"] = export_dataset(connection, output, config)
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.close()
        finalize(
            raw / "meta_Cell_Phones_and_Accessories.jsonl",
            raw / "Cell_Phones_and_Accessories.jsonl",
            output,
            config,
            rules,
            stats,
            started,
            "official_raw",
        )
        update("validating")
        audit = validate(output)
        write_json(job / "validation.json", audit)
        update("importing_catalog")
        subprocess.run(
            [sys.executable, "manage.py", "import_research_catalog", str(output)],
            cwd=ROOT,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        write_json(
            job / "result.json",
            {
                "status": "complete",
                "statistics": stats["final"],
                "validation": audit,
                "manifest_sha256": file_hash(output / "manifest.json"),
                "dataset": str(output),
            },
        )
        update("complete", result=str(job / "result.json"))
    except Exception as error:
        update("failed", error=f"{type(error).__name__}: {error}")
        traceback.print_exc()
        raise
    finally:
        connection.close()
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
