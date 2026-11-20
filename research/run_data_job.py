"""Run the real-data workflow and persist its status for long downloads."""

import argparse
import json
import os
import subprocess
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from research.data.io import file_hash, write_json
from research.data.pipeline import ROOT, prepare
from research.download import download
from research.validate import validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw/amazon-2023-hf")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/amazon-v1")
    parser.add_argument("--workers-per-file", type=int, choices=range(1, 9), default=8)
    args = parser.parse_args()
    job_dir = ROOT / "reports/data-job"
    job_dir.mkdir(parents=True, exist_ok=True)
    lock = job_dir / "job.lock"
    try:
        with lock.open("x", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    except FileExistsError:
        raise SystemExit(
            "A job lock already exists. Inspect the recorded PID before explicitly removing a stale lock."
        )
    status = {
        "pid": os.getpid(),
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(args.output.resolve()),
        "raw_dir": str(args.raw_dir.resolve()),
        "log": str(job_dir / "job.log"),
    }

    def update(stage, **extra):
        status.update(stage=stage, updated_at_utc=datetime.now(timezone.utc).isoformat(), **extra)
        write_json(job_dir / "status.json", status)

    try:
        update("downloading")
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(
                pool.map(
                    lambda kind: download(kind, args.raw_dir, args.workers_per_file, "huggingface"),
                    ["metadata", "reviews"],
                )
            )
        write_json(
            args.raw_dir / "source_manifest.json",
            {"files": receipts, "kind": "official_raw_download"},
        )
        if (args.output / "manifest.json").exists():
            update("validating_existing_dataset")
            audit = validate(args.output)
        else:
            update("preprocessing")
            prepare(
                args.raw_dir / "meta_Cell_Phones_and_Accessories.jsonl",
                args.raw_dir / "Cell_Phones_and_Accessories.jsonl",
                args.output,
            )
            update("validating")
            audit = validate(args.output)
        write_json(job_dir / "validation.json", audit)
        update("importing_catalog")
        subprocess.run(
            [sys.executable, "manage.py", "import_research_catalog", str(args.output)],
            cwd=ROOT,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        manifest = json.loads((args.output / "manifest.json").read_text(encoding="utf-8"))
        summary = {
            "status": "complete",
            "statistics": manifest["statistics"],
            "validation": audit,
            "manifest_sha256": file_hash(args.output / "manifest.json"),
            "dataset": str(args.output.resolve()),
        }
        write_json(job_dir / "result.json", summary)
        update("complete", result=str(job_dir / "result.json"))
        print("Real-data preparation, validation and catalog import complete.", flush=True)
    except Exception as error:
        update("failed", error=f"{type(error).__name__}: {error}")
        traceback.print_exc()
        raise
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
