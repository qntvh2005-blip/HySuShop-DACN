"""Shared, integrity-checked candidate loader used by every recommender."""

import json
from pathlib import Path

from research.data.io import digest, file_hash, read_jsonl


class ResearchDataset:
    def __init__(self, directory, verify=True):
        self.directory = Path(directory)
        self.manifest = json.loads((self.directory / "manifest.json").read_text(encoding="utf-8"))
        if self.manifest.get("status") != "complete":
            raise ValueError("Dataset is not complete")
        if verify:
            for name, expected in self.manifest["outputs"].items():
                if file_hash(self.directory / name) != expected:
                    raise ValueError(f"Dataset checksum mismatch: {name}")
        self.item_ids = json.loads((self.directory / "item_index.json").read_text(encoding="utf-8"))
        self.candidate_records = {
            (r["stage"], r["user_id"]): r for r in read_jsonl(self.directory / "candidates.jsonl")
        }

    def candidates(self, user_id, stage):
        record = self.candidate_records[(stage, user_id)]
        seen = set(record["seen_item_ids"])
        candidates = [item for item in self.item_ids if item not in seen]
        if (
            digest(candidates) != record["candidate_sha256"]
            or len(candidates) != record["candidate_count"]
        ):
            raise ValueError("Candidate checksum/count mismatch")
        if record["target_item_id"] not in candidates:
            raise ValueError("Hidden target is absent from candidates")
        return candidates

    def rows(self, name):
        if name not in {
            "catalog",
            "train",
            "development",
            "test",
            "users",
            "interactions",
            "excluded_users",
        }:
            raise ValueError("Unknown dataset file")
        return read_jsonl(self.directory / f"{name}.jsonl")
