from unittest.mock import patch
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.cart.models import CartItem
from apps.cart.services import set_quantity
from apps.catalog.models import Brand, Category, Product, ProductCategory
from apps.common.management_forms import ProductEditor
from apps.interactions.models import UserInteraction
from apps.recommendations.services import RecommendationResult
from tests.test_recommenders import tiny_bundle


class ReviewRegressionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="review-buyer")
        cls.brand = Brand.objects.create(name="Hữu Phước", slug="huu-phuoc")
        cls.product = Product.objects.create(
            external_item_id="REVIEW-CASE",
            name="Ốp mẫu",
            slug="review-case",
            brand=cls.brand,
            price=99000,
            stock=20,
            is_active=True,
        )
        cls.category = Category.objects.create(name="Ốp lưng", slug="review-category")
        ProductCategory.objects.create(product=cls.product, category=cls.category)

    def test_unaccented_search_finds_the_live_brand_name(self):
        response = self.client.get(reverse("product_list"), {"q": "huu phuoc"})
        self.assertEqual([p.pk for p in response.context["page_obj"]], [self.product.pk])

    def test_brand_rename_is_searchable_without_reimporting_the_product(self):
        self.brand.name = "Thương hiệu Việt"
        self.brand.save(update_fields=["name"])
        response = self.client.get(reverse("product_list"), {"q": "thuong hieu viet"})
        self.assertEqual([p.pk for p in response.context["page_obj"]], [self.product.pk])
        self.assertEqual(self.product.name, "Ốp mẫu")

    def test_invalid_cart_action_does_not_replace_quantity_or_record_events(self):
        self.client.force_login(self.user)
        set_quantity(user=self.user, product_id=self.product.pk, quantity=4)
        count = UserInteraction.objects.count()
        self.client.post(
            reverse("update_cart", args=[self.product.pk]),
            {"mode": "unexpected", "quantity": 1},
        )
        self.assertEqual(CartItem.objects.get(cart__user=self.user).quantity, 4)
        self.assertEqual(UserInteraction.objects.count(), count)

    def test_missing_quantity_cannot_silently_reset_a_cart_line(self):
        self.client.force_login(self.user)
        set_quantity(user=self.user, product_id=self.product.pk, quantity=4)
        self.client.post(reverse("update_cart", args=[self.product.pk]), {})
        self.assertEqual(CartItem.objects.get(cart__user=self.user).quantity, 4)

    def test_zero_similarity_uses_popularity_and_records_the_fallback(self):
        model = tiny_bundle()
        # A shares no content terms with B or D. Make the popularity order
        # differ from alphabetical order to expose arbitrary zero-score ties.
        model.popularity[model.item_index["D"]] = 9
        ranking = model.similar("A", ["A", "B", "D"], 2)
        self.assertEqual(ranking.item_ids, ["D", "B"])
        self.assertEqual(ranking.fallback_reason, "zero_scores")
        self.assertNotIn("A", ranking.item_ids)

    def test_fallback_products_are_not_presented_as_content_matches(self):
        result = RecommendationResult(
            [], "operational_popularity", "untrained", "artifact_unavailable:OSError", 0
        )
        with patch("apps.catalog.views.recommend", return_value=result):
            response = self.client.get(reverse("product_detail", args=[self.product.slug]))
        self.assertContains(response, "Có thể bạn quan tâm")
        self.assertNotContains(response, "Sản phẩm tương tự")

    def test_content_matches_keep_the_similar_products_heading(self):
        result = RecommendationResult([], "content_similar", "test", "", 0)
        with patch("apps.catalog.views.recommend", return_value=result):
            response = self.client.get(reverse("product_detail", args=[self.product.slug]))
        self.assertContains(response, "Sản phẩm tương tự")

    def test_conflicting_brand_records_cannot_be_reopened_in_management(self):
        self.product.is_active = False
        for item_id in [
            "B00D856NOG", "B00M3073L4", "B00OHE8AOI", "B017JT6846",
            "B01D8C6ULO", "B0756Z8X82", "B07WR4J1GN",
        ]:
            with self.subTest(item_id=item_id):
                self.product.external_item_id = item_id
                self.product.save()
                form = ProductEditor(
                    {
                        "external_item_id": item_id,
                        "name": self.product.name,
                        "brand": self.brand.pk,
                        "categories": [self.category.pk],
                        "price": 99000,
                        "stock": 20,
                        "is_active": "on",
                        "revision": self.product.updated_at.isoformat(),
                    },
                    instance=self.product,
                )
                self.assertFalse(form.is_valid())
                self.assertIn("is_active", form.errors)

    def test_source_repair_archives_conflict_without_changing_research_metadata(self):
        source = {
            "item_id": "B0756Z8X82",
            "title": "Anker Wireless Charger",
            "categories": ["Wireless Chargers"],
            "attributes": {"Brand": "Samsung"},
            "dataset_manifest_sha256": "frozen-research",
        }
        self.product.external_item_id = source["item_id"]
        self.product.source_metadata = source
        self.product.save()
        call_command("localize_catalog", repair_filters=True, apply=True, stdout=StringIO())
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_active)
        self.assertEqual(self.product.source_metadata, source)
        self.assertEqual((self.product.price, self.product.stock), (99000, 20))
