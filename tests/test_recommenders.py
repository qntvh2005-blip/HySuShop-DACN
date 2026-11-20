import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from research.data.fixtures import synthetic_records
from research.data.io import write_json, write_jsonl
from research.data.pipeline import ROOT, prepare
from research.evaluation.experiment import run_experiment, select_best
from research.evaluation.metrics import topk_metrics
from research.evaluation.uncertainty import paired_bootstrap
from research.models.artifacts import load_bundle, save_bundle
from research.models.recommenders import ALGORITHMS, RecommenderBundle, minmax


def tiny_bundle(**kwargs):
    catalog = [
        {"item_id": item, "content_text": text}
        for item, text in [
            ("A", "red iphone case"),
            ("B", "usb charger cable"),
            ("C", "red iphone cover"),
            ("D", "usb charger adapter"),
        ]
    ]
    train = [
        {"user_id": user, "item_id": item, "rating": 5}
        for user, items in [("x", ["A", "B"]), ("y", ["B", "C"]), ("z", ["A", "D"])]
        for item in items
    ]
    return RecommenderBundle(**kwargs).fit(catalog, train)


class BootstrapTests(unittest.TestCase):
    @staticmethod
    def rows():
        return [
            {"user_id": user, "algorithm": algorithm, "stage": "test", "group": group,
             "candidate_count": 10, "candidate_sha256": "same-candidates",
             "ndcg@10": 0.75 if algorithm == "hybrid" else 0.25,
             "hit_rate@10": int(algorithm == "hybrid")}
            for user, group in (("u1", "sparse"), ("u2", "active"), ("u3", "sparse"))
            for algorithm in ALGORITHMS
        ]

    def test_constant_paired_difference_has_exact_interval(self):
        result = paired_bootstrap(self.rows(), repeats=200)
        for group in result["groups"].values():
            for metrics in group["comparisons"].values():
                self.assertEqual(metrics["ndcg@10"],
                                 {"difference": 0.5, "lower": 0.5, "upper": 0.5})
                self.assertEqual(metrics["hit_rate@10"]["lower"], 1.0)

    def test_pairing_contract_and_order_independence(self):
        rows = self.rows()
        rows[0]["ndcg@10"] = 0.1
        self.assertEqual(paired_bootstrap(rows, repeats=200),
                         paired_bootstrap(list(reversed(rows)), repeats=200))
        with self.assertRaises(ValueError):
            paired_bootstrap(rows[:-1])
        rows[-1]["candidate_sha256"] = "different-candidates"
        with self.assertRaises(ValueError):
            paired_bootstrap(rows)


class RecommenderTests(unittest.TestCase):
    def test_content_similarity_and_self_exclusion(self):
        model = tiny_bundle()
        self.assertEqual(model.rank("content", ["A"], ["B", "C", "D"]).item_ids[0], "C")
        similar = model.similar("A", ["A", "B", "C", "D"])
        self.assertEqual(similar.item_ids[0], "C")
        self.assertNotIn("A", similar.item_ids)

    def test_collaborative_cosine_and_binary_history(self):
        model = tiny_bundle()
        scores = model.raw_scores("item_cf", ["A"], ["B", "C", "D"])
        np.testing.assert_allclose(scores, [0.5, 0, 1 / math.sqrt(2)], atol=1e-12)
        np.testing.assert_allclose(scores, model.raw_scores("item_cf", ["A", "A"], ["B", "C", "D"]))
        self.assertTrue(np.all(model.cf_neighbors.diagonal() == 0))

    def test_popularity_ties_and_cold_start_fallback(self):
        model = tiny_bundle()
        self.assertEqual(model.rank("popularity", [], ["B", "A"]).item_ids, ["A", "B"])
        result = model.rank("hybrid", ["unknown"], ["D", "B", "A", "C"])
        self.assertEqual(result.item_ids, ["A", "B", "C", "D"])
        self.assertEqual(result.fallback_reason, "no_known_history")

    def test_hybrid_weight_endpoints_and_constant_scores(self):
        model = tiny_bundle(alpha=1)
        candidates = ["B", "C", "D"]
        content, collaborative = model.component_scores(["A"], candidates)
        np.testing.assert_allclose(model.raw_scores("hybrid", ["A"], candidates), minmax(content))
        model.alpha = 0
        np.testing.assert_allclose(
            model.raw_scores("hybrid", ["A"], candidates), minmax(collaborative)
        )
        np.testing.assert_equal(minmax([3, 3]), [0, 0])
        with self.assertRaises(ValueError):
            minmax([float("nan")])

    def test_candidate_contract_and_empty_candidates(self):
        model = tiny_bundle()
        for algorithm in ALGORITHMS:
            result = model.rank(algorithm, ["A"], ["B", "D"], 5)
            self.assertEqual(set(result.item_ids), {"B", "D"})
            self.assertEqual(model.rank(algorithm, [], []).item_ids, [])
        with self.assertRaises(ValueError):
            model.rank("content", [], ["A", "A"])
        with self.assertRaises(ValueError):
            model.rank("popularity", [], ["unknown"])

    def test_optional_operational_weights_do_not_change_binary_benchmark(self):
        model = tiny_bundle()
        candidates = ["C", "D"]
        binary = model.raw_scores("content", ["A", "B"], candidates)
        weighted = model.raw_scores("content", ["A", "B"], candidates, {"A": 5, "B": 1})
        self.assertGreater(weighted[0], binary[0])
        self.assertLess(weighted[1], binary[1])
        np.testing.assert_allclose(
            binary, model.raw_scores("content", ["A", "B"], candidates, {"A": 1, "B": 1})
        )
        with self.assertRaises(ValueError):
            model.raw_scores("hybrid", ["A"], candidates, {"A": 0})

    def test_artifact_round_trip_and_checksum(self):
        model = tiny_bundle()
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / "artifact"
            save_bundle(model, folder, {"source_kind": "synthetic_fixture"})
            loaded, _ = load_bundle(folder)
            self.assertEqual(
                model.rank("hybrid", ["A"], ["B", "C", "D"]),
                loaded.rank("hybrid", ["A"], ["B", "C", "D"]),
            )
            with (folder / "bundle.joblib").open("ab") as stream:
                stream.write(b"corruption")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_bundle(folder)


class EvaluationTests(unittest.TestCase):
    def test_known_topk_metrics_and_short_rankings(self):
        metrics = topk_metrics(["a", "b", "hit"], {"hit"}, 5)
        self.assertEqual(metrics, {"precision": 0.2, "recall": 1, "hit_rate": 1.0, "ndcg": 0.5})
        self.assertEqual(topk_metrics(["a"], {"hit"}, 10)["precision"], 0)
        self.assertEqual(topk_metrics(["hit"], {"hit"}, 10)["precision"], 0.1)
        with self.assertRaises(ValueError):
            topk_metrics(["hit", "hit"], {"hit"}, 5)

    def test_selection_rejects_test_and_breaks_ties_by_grid_order(self):
        trials = [
            {
                "stage": "development",
                "id": i,
                "metrics": {"all": {"ndcg@10": 0.1, "hit_rate@10": 0.2}},
            }
            for i in [0, 1]
        ]
        self.assertEqual(select_best(trials)["id"], 0)
        trials[0]["stage"] = "test"
        with self.assertRaisesRegex(ValueError, "development"):
            select_best(trials)

    def test_full_experiment_locks_config_and_shares_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            metadata, reviews = synthetic_records()
            write_jsonl(root / "meta.jsonl", metadata)
            write_jsonl(root / "reviews.jsonl", reviews)
            config = json.loads(
                (ROOT / "research/configs/experiment.json").read_text(encoding="utf-8")
            )
            config["models"]["content"] = {"ngram_grid": [[1, 1]], "min_df_grid": [1]}
            config["models"]["item_cf"]["neighbors_grid"] = [5]
            config["evaluation"]["timing_repeats"] = 2
            write_json(root / "config.json", config)
            prepare(
                root / "meta.jsonl",
                root / "reviews.jsonl",
                root / "dataset",
                root / "config.json",
                source_kind="synthetic_fixture",
            )
            with self.assertRaisesRegex(ValueError, "Synthetic"):
                run_experiment(root / "dataset", root / "blocked", root / "blocked-artifact")
            result = run_experiment(
                root / "dataset", root / "reports", root / "artifact", allow_synthetic=True
            )
            self.assertEqual(result["status"], "complete")
            locked = json.loads((root / "reports/locked_config.json").read_text(encoding="utf-8"))
            self.assertEqual(locked["selected_on"], "development")
            self.assertIn(locked["alpha"], [0.25, 0.5, 0.75])
            self.assertFalse(locked["refit"])
            from research.data.io import read_jsonl

            per_user = list(read_jsonl(root / "reports/test_per_user.jsonl"))
            hashes = {r["candidate_sha256"] for r in per_user if r["user_id"] == "u00"}
            self.assertEqual(len(hashes), 1)
            self.assertEqual({r["algorithm"] for r in per_user}, set(ALGORITHMS))
            self.assertTrue(all(len(r["timings_ms"]) == 2 for r in per_user))
            self.assertTrue((root / "artifact/manifest.json").is_file())
