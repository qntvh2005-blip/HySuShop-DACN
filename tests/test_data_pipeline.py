import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from research.data.dataset import ResearchDataset
from research.data.fixtures import synthetic_records
from research.data.io import canonical, write_json, write_jsonl
from research.data.normalize import AccessoryFilter, normalize_metadata, normalize_review
from research.data.pipeline import ROOT, prepare, prune_core
from research.validate import validate


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        rules = json.loads(
            (ROOT / "research/configs/accessory_filter.json").read_text(encoding="utf-8")
        )
        self.filter = AccessoryFilter(rules)

    def test_phone_exclusion_and_accessory_inclusion(self):
        self.assertFalse(
            self.filter.decide(
                {"parent_asin": "P", "title": "Unlocked smartphone", "categories": ["Cell Phones"]}
            )[0]
        )
        self.assertTrue(self.filter.decide({"parent_asin": "C", "title": "iPhone case"})[0])
        self.assertFalse(self.filter.decide({"parent_asin": "S", "title": "SIM card"})[0])
        self.assertFalse(
            self.filter.decide(
                {
                    "parent_asin": "X",
                    "title": "Unknown",
                    "categories": ["Cell Phones & Accessories"],
                }
            )[0]
        )
        self.assertFalse(
            self.filter.decide(
                {
                    "parent_asin": "W",
                    "title": "Apple Watch Screen Protector",
                    "categories": [
                        "Cell Phones & Accessories",
                        "Smartwatch Accessories",
                        "Screen Protectors",
                    ],
                }
            )[0]
        )

    def test_metadata_content_omits_rating_and_review_signals(self):
        meta, _ = synthetic_records()
        raw = copy.deepcopy(meta[0])
        raw.update(average_rating=4.99, rating_number=987654, bought_together=["SECRET_TARGET"])
        result = normalize_metadata(raw)
        self.assertNotIn("SECRET_TARGET", result["content_text"])
        self.assertNotIn("987654", result["content_text"])
        self.assertIn("Protective", result["content_text"])
        self.assertNotIn("<b>", result["content_text"])
        self.assertEqual(result["source_currency"], "USD")

    def test_invalid_ratings_and_timestamp_fallback(self):
        base = {"user_id": "u", "parent_asin": "i", "rating": 4, "timestamp": 1000}
        for update in [
            {"rating": float("nan")},
            {"rating": 6},
            {"rating": True},
            {"timestamp": -1},
            {"timestamp": 1000.5},
            {"user_id": ""},
        ]:
            self.assertIsNone(normalize_review({**base, **update}))
        base.pop("timestamp")
        self.assertEqual(normalize_review({**base, "sort_timestamp": 1000})["timestamp"], 1000)

    def test_iterative_core_cascades(self):
        db = sqlite3.connect(":memory:")
        try:
            db.execute("CREATE TABLE reviews(user_id TEXT,item_id TEXT,rating REAL)")
            db.executemany(
                "INSERT INTO reviews VALUES(?,?,?)",
                [("a", "x", 5), ("a", "y", 5), ("b", "y", 5), ("b", "z", 5), ("c", "z", 5)],
            )
            steps = prune_core(db, user_min=2, item_min=2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0], 0)
            self.assertGreater(len(steps), 1)
        finally:
            db.close()


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.meta, self.reviews = synthetic_records()
        write_jsonl(self.root / "meta.jsonl", self.meta)
        write_jsonl(self.root / "reviews.jsonl", self.reviews)
        self.config = json.loads(
            (ROOT / "research/configs/experiment.json").read_text(encoding="utf-8")
        )
        self.config["preprocessing"].update(max_items=12, max_users=100)
        write_json(self.root / "config.json", self.config)

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, name="dataset"):
        output = self.root / name
        prepare(
            self.root / "meta.jsonl",
            self.root / "reviews.jsonl",
            output,
            self.root / "config.json",
            source_kind="synthetic_fixture",
        )
        return ResearchDataset(output)

    def test_positive_history_seen_history_and_targets(self):
        dataset = self.prepare()
        training = list(dataset.rows("train"))
        self.assertTrue(all(r["rating"] >= 4 for r in training))
        self.assertFalse(any(r["user_id"] == "u00" and r["item_id"] == "I00" for r in training))
        self.assertFalse(any(r["user_id"] == "ambiguous" for r in dataset.rows("users")))
        for stage in ["development", "test"]:
            candidates = dataset.candidates("u00", stage)
            self.assertNotIn("I00", candidates)  # newest rating is negative and observed
            target = next(r for r in dataset.rows(stage) if r["user_id"] == "u00")
            self.assertIn(target["item_id"], candidates)
            self.assertFalse(
                any(r["user_id"] == "u00" and r["item_id"] == target["item_id"] for r in training)
            )
        dev = next(r for r in dataset.rows("development") if r["user_id"] == "u00")
        self.assertNotIn(dev["item_id"], dataset.candidates("u00", "test"))
        self.assertEqual(dataset.manifest["statistics"]["users"], 10)
        self.assertEqual(validate(dataset.directory)["status"], "passed")

    def test_order_independent_reproducibility_and_tie_resolution(self):
        # Equal-timestamp conflicting ratings resolve through a deterministic normalized hash.
        first = {"user_id": "u01", "parent_asin": "I01", "rating": 5, "timestamp": 1001}
        second = {**first, "rating": 2}
        self.reviews.extend([first, second])
        write_jsonl(self.root / "reviews.jsonl", self.reviews)
        one = self.prepare("one")
        write_jsonl(self.root / "meta.jsonl", list(reversed(self.meta)))
        write_jsonl(self.root / "reviews.jsonl", list(reversed(self.reviews)))
        two = self.prepare("two")
        for filename in ["catalog", "train", "development", "test", "users", "interactions"]:
            self.assertEqual(list(one.rows(filename)), list(two.rows(filename)))
        self.assertEqual(one.candidate_records, two.candidate_records)
        chosen = max(
            [normalize_review(first), normalize_review(second)], key=lambda r: r["tie_hash"]
        )
        actual = next(
            r for r in one.rows("interactions") if r["user_id"] == "u01" and r["item_id"] == "I01"
        )
        self.assertEqual(actual["rating"], chosen["rating"])

    def test_candidate_integrity_and_dataset_tampering(self):
        dataset = self.prepare()
        dataset.candidate_records[("test", "u00")]["candidate_sha256"] = "broken"
        with self.assertRaises(ValueError):
            dataset.candidates("u00", "test")
        with (dataset.directory / "train.jsonl").open("a", encoding="utf-8") as output:
            output.write(canonical({"tampered": True}) + "\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            ResearchDataset(dataset.directory)

    def test_no_overwrite_and_incompatible_protocol_rejected(self):
        self.prepare()
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.config["split"]["refit_on_train_dev"] = True
        write_json(self.root / "config.json", self.config)
        with self.assertRaises(ValueError):
            self.prepare("unsupported")

    def test_seeded_subset_reapplies_core(self):
        self.config["preprocessing"].update(max_users=6, max_items=10)
        write_json(self.root / "config.json", self.config)
        dataset = self.prepare()
        self.assertLessEqual(len(dataset.item_ids), 10)
        self.assertLessEqual(len(list(dataset.rows("users"))), 6)
        for user in dataset.rows("users"):
            self.assertGreaterEqual(user["train_positives"], 3)
