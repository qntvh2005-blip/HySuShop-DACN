from unittest import TestCase
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase as DatabaseTestCase
from django.template.loader import render_to_string

from apps.catalog.models import Product
from apps.interactions.models import UserInteraction
from apps.recommendations.services import recommend
from apps.recommendations.models import RecommendationLog
from research.evaluation.cold_start_audit import cases, user_split
from tests.test_recommenders import tiny_bundle


class UserHoldoutProtocolTests(TestCase):
    def test_disjoint_users_and_next_event_history_prevent_label_leakage(self):
        users = [f"user-{i}" for i in range(30)]
        groups = user_split(users)
        self.assertEqual(groups, user_split(users[::-1]))
        self.assertFalse(set(groups["fit"]) & set(groups["test"]))
        self.assertFalse(set(groups["fit"]) & set(groups["development"]))
        interactions = [{"user_id": "held", "item_id": item, "rating": rating, "timestamp": timestamp}
                        for item, rating, timestamp in [("NEG", 1, 1), ("A", 5, 2), ("B", 4, 3), ("C", 5, 4)]]
        zero = cases(interactions, {"held"}, ["NEG", "A", "B", "C"], 0)[0]
        one = cases(interactions, {"held"}, ["NEG", "A", "B", "C"], 1)[0]
        self.assertEqual((zero["history"], zero["target"], zero["candidates"]), ([], "A", ["NEG", "A", "B", "C"]))
        self.assertEqual((one["history"], one["target"], one["candidates"]), (["A"], "B", ["B", "C"]))


class ExplanationIntegrityTests(DatabaseTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="reason-customer")
        self.other = get_user_model().objects.create_user(username="reason-other")
        for item in ["A", "B", "C", "D"]:
            Product.objects.create(external_item_id=item, name=f"Phụ kiện {item}", slug=f"reason-{item}", price=100, stock=5, is_active=True)
        UserInteraction.objects.create(user=self.user, product=Product.objects.get(external_item_id="A"), event_type="favorite")
        UserInteraction.objects.create(user=self.other, product=Product.objects.get(external_item_id="B"), event_type="favorite")

    def test_logged_evidence_uses_own_history_and_stays_off_customer_card(self):
        Product.objects.filter(external_item_id="A").update(name='<script>alert("x")</script>')
        with patch("apps.recommendations.services.active_bundle", return_value=(tiny_bundle(), {"model_version": "test", "serving_algorithm": "content"})):
            result = recommend(user=self.user, context="personalized", current_item_id="A")
        entry = RecommendationLog.objects.get()
        self.assertEqual(set(entry.evidence["history_weights"]), {"A"})
        self.assertTrue(all(source["item_id"] == "A" for row in entry.evidence["items"] for source in row["sources"]))
        html = render_to_string("catalog/card.html", {"product": result.products[0]})
        self.assertNotIn("Vì sao gợi ý?", html)
        self.assertNotIn('<script>alert("x")</script>', html)

    def test_popularity_and_missing_artifact_remain_distinct_in_log(self):
        with patch("apps.recommendations.services.active_bundle", return_value=(tiny_bundle(), {"model_version": "test", "serving_algorithm": "hybrid"})):
            result = recommend(context="personalized")
        cold = RecommendationLog.objects.latest("pk")
        self.assertEqual(cold.fallback_reason, "no_known_history")
        self.assertEqual(cold.evidence, {})
        self.assertTrue(result.products)
        with patch("apps.recommendations.services.active_bundle", side_effect=OSError("missing")):
            fallback = recommend(user=self.user, context="personalized")
        operational = RecommendationLog.objects.latest("pk")
        self.assertTrue(operational.fallback_reason.startswith("artifact_unavailable:"))
        self.assertEqual(operational.algorithm, "operational_popularity")
        self.assertTrue(fallback.products)
