from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Product
from apps.interactions.models import UserInteraction
from apps.recommendations.models import RecommendationLog
from apps.recommendations.services import recommend
from tests.test_recommenders import tiny_bundle


class ExplanationEvidenceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="evidence-buyer")
        for item in ["A", "B", "C", "D"]:
            Product.objects.create(external_item_id=item, name=f"Product {item}", slug=f"evidence-{item}", price=100, stock=5, is_active=True)
        UserInteraction.objects.create(user=self.user, product=Product.objects.get(external_item_id="A"), event_type="favorite")

    def test_hybrid_evidence_reconstructs_actual_ranking_and_limits_access(self):
        with patch("apps.recommendations.services.active_bundle", return_value=(tiny_bundle(), {"model_version": "test", "serving_algorithm": "hybrid"})):
            result = recommend(user=self.user, context="personalized", current_item_id="A")
        log = RecommendationLog.objects.get()
        self.assertEqual([row["item_id"] for row in log.evidence["items"]], log.item_ids)
        for row in log.evidence["items"]:
            expected = log.evidence["alpha"] * row["content_normalized"] + (1 - log.evidence["alpha"]) * row["cf_normalized"]
            self.assertAlmostEqual(expected, row["score"])
            self.assertEqual(row["sources"][0]["item_id"], "A")
        self.client.force_login(self.user)
        path = reverse("manage_recommendation_detail", args=[log.pk])
        self.assertEqual(self.client.get(path).status_code, 403)
        admin = get_user_model().objects.create_superuser(username="evidence-admin", password="test")
        self.client.force_login(admin)
        self.assertContains(self.client.get(path), "Product A")

    def test_empty_history_and_unknown_history_use_popularity(self):
        model = tiny_bundle()
        for history in [[], ["NEW-ITEM"]]:
            result = model.rank("hybrid", history, model.item_ids, 3)
            self.assertEqual(result.fallback_reason, "no_known_history")
            self.assertEqual(result.item_ids, model.rank("popularity", [], model.item_ids, 3).item_ids)
