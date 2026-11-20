import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from research.data.dataset import ResearchDataset
from research.data.fixtures import synthetic_records
from research.data.io import file_hash, write_json, write_jsonl
from research.data.normalize import AccessoryFilter
from research.data.pipeline import ROOT, prepare
from research.refine_catalog import refine


class CatalogRefinementTests(SimpleTestCase):
    def test_watch_only_is_excluded_but_shared_phone_accessory_is_kept(self):
        rules = json.loads(
            (ROOT / "research/configs/accessory_filter.json").read_text(encoding="utf-8")
        )
        policy = AccessoryFilter(rules)
        for title in [
            "Screen Protector for Fitbit Charge 4",
            "Galaxy Watch Screen Protector",
            "TV Wall Mount Bracket",
        ]:
            self.assertFalse(
                policy.decide(
                    {"parent_asin": "TEST", "title": title, "categories": ["Screen Protectors"]}
                )[0]
            )
        self.assertTrue(
            policy.decide(
                {
                    "parent_asin": "TEST",
                    "title": "Charging Stand for Apple Watch and iPhone 14",
                    "categories": ["Charging Stations"],
                }
            )[0]
        )

    def test_refinement_preserves_parent_and_rebuilds_valid_splits(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            metadata, reviews = synthetic_records()
            write_jsonl(root / "meta.jsonl", metadata)
            write_jsonl(root / "reviews.jsonl", reviews)
            config = json.loads(
                (ROOT / "research/configs/experiment.json").read_text(encoding="utf-8")
            )
            write_json(root / "config.json", config)
            prepare(
                root / "meta.jsonl",
                root / "reviews.jsonl",
                root / "parent",
                root / "config.json",
                source_kind="synthetic_fixture",
            )
            parent_hash = file_hash(root / "parent/manifest.json")
            rules = json.loads(
                (ROOT / "research/configs/accessory_filter.json").read_text(encoding="utf-8")
            )
            rules["reviewed_exclusions"]["I00"] = "Test-only reviewed exclusion"
            write_json(root / "rules.json", rules)
            with self.assertRaises(ValueError):
                refine(root / "parent", root / "blocked", root / "rules.json")
            manifest = refine(
                root / "parent", root / "clean", root / "rules.json", allow_synthetic=True
            )
            self.assertEqual(file_hash(root / "parent/manifest.json"), parent_hash)
            self.assertEqual(manifest["source_kind"], "synthetic_fixture")
            self.assertEqual(manifest["derivation"]["parent_manifest_sha256"], parent_hash)
            dataset = ResearchDataset(root / "clean")
            self.assertNotIn("I00", dataset.item_ids)
            self.assertTrue(all(r["item_id"] != "I00" for r in dataset.rows("interactions")))
            self.assertGreater(manifest["statistics"]["users"], 0)
            for name in ["sample-a", "sample-b"]:
                refine(
                    root / "parent",
                    root / name,
                    root / "rules.json",
                    allow_synthetic=True,
                    max_items=10,
                )
            sampled = ResearchDataset(root / "sample-a")
            self.assertLessEqual(len(sampled.item_ids), 10)
            self.assertNotIn("I00", sampled.item_ids)
            for filename in [
                "catalog.jsonl",
                "interactions.jsonl",
                "train.jsonl",
                "candidates.jsonl",
            ]:
                self.assertEqual(
                    file_hash(root / "sample-a" / filename), file_hash(root / "sample-b" / filename)
                )
