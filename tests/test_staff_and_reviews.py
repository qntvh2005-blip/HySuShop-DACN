import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.cart.services import set_quantity
from apps.catalog.models import Product
from apps.interactions.models import ProductReview
from apps.orders.models import Order
from apps.orders.services import checkout
from research.data.io import file_hash, write_json


class StaffAndReviewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="buyer")
        self.staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        call_command("setup_roles", verbosity=0)
        self.staff.groups.add(Group.objects.get(name="Admin"))
        self.product = Product.objects.create(
            external_item_id="CASE",
            name="Test case",
            slug="test-case",
            price=100,
            stock=3,
            is_active=True,
        )

    def test_staff_actions_follow_order_state_machine(self):
        set_quantity(user=self.user, product_id=self.product.pk, quantity=1)
        order = checkout(
            user=self.user,
            checkout_key=uuid.uuid4(),
            recipient_name="Test",
            phone="0900000000",
            address="Test",
        )
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        for state in ["confirmed", "shipping", "delivered"]:
            self.client.post(
                reverse("manage_order_transition", args=[order.pk]), {"to_status": state}
            )
            order.refresh_from_db()
            self.assertEqual(order.status, state)
        self.assertEqual(order.status_history.count(), 4)

    def test_review_requires_delivered_order_and_escapes_html(self):
        self.client.force_login(self.user)
        path = reverse("review_product", args=[self.product.pk])
        before_delivery = self.client.get(reverse("product_detail", args=[self.product.slug]))
        self.assertNotContains(before_delivery, 'name="rating"')
        self.client.post(path, {"rating": "5", "comment": "Not purchased"})
        self.assertEqual(ProductReview.objects.count(), 0)
        set_quantity(user=self.user, product_id=self.product.pk, quantity=1)
        order = checkout(
            user=self.user,
            checkout_key=uuid.uuid4(),
            recipient_name="Test",
            phone="0900000000",
            address="Test",
        )
        order_url = reverse("order_detail", args=[order.number])
        product_url = reverse("product_detail", args=[self.product.slug])
        self.assertNotContains(self.client.get(order_url), "Đánh giá sản phẩm")
        Order.objects.filter(pk=order.pk).update(status="delivered")
        self.assertContains(self.client.get(order_url), f'href="{product_url}#viet-danh-gia"')
        submitted = self.client.post(path, {"rating": "5", "comment": "<script>alert(1)</script>"})
        review = ProductReview.objects.get()
        self.assertEqual(review.rating, 5)
        self.assertRedirects(submitted, f"{product_url}#danh-gia-{review.pk}")
        response = self.client.get(product_url)
        self.assertContains(response, 'id="viet-danh-gia"')
        self.assertContains(response, f'id="danh-gia-{review.pk}"')
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, 'type="radio" name="rating"', count=5)
        self.assertContains(response, 'class="rating-star"', count=5)
        self.assertContains(response, 'class="star-filled"', count=5)
        self.assertNotContains(response, "5/5 sao")
        self.assertContains(
            response,
            '<input type="radio" name="rating" value="5" id="id_rating_4" required checked>',
            html=True,
        )
        self.client.post(path, {"rating": "4", "comment": "Updated review"})
        self.assertEqual(ProductReview.objects.count(), 1)
        self.assertEqual(ProductReview.objects.get().rating, 4)
        Product.objects.filter(pk=self.product.pk).update(is_active=False)
        self.assertNotContains(self.client.get(order_url), "Đánh giá sản phẩm")

    def test_customer_cannot_open_staff_dashboard(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 403)

    def test_dashboard_metrics_group_selection_and_checksum(self):
        with (
            TemporaryDirectory() as temp,
            override_settings(
                BASE_DIR=Path(temp),
                ARTIFACT_ROOT=Path(temp) / "artifacts",
                RECOMMENDATION_MODEL_VERSION="fixture-new",
            ),
        ):
            root = Path(temp)
            folder = root / "reports/fixture-new"
            folder.mkdir(parents=True)
            metrics = {}
            for algorithm in ["popularity", "content", "item_cf", "hybrid"]:
                metrics[algorithm] = {}
                for group, count in [("all", 10), ("sparse", 8), ("active", 2)]:
                    values = {"users": count, "mean_ms": 1.2, "p95_ms": 2.1, "fallback_users": 0}
                    for k in [5, 10]:
                        values.update(
                            {
                                f"{name}@{k}": 0.2
                                for name in ["precision", "recall", "ndcg", "hit_rate"]
                            }
                        )
                    metrics[algorithm][group] = values
            write_json(folder / "test_metrics.json", metrics)
            write_json(
                folder / "manifest.json",
                {
                    "status": "complete",
                    "source_kind": "official_raw",
                    "outputs": {"test_metrics.json": file_hash(folder / "test_metrics.json")},
                    "locked_config": {
                        "alpha": 0.5,
                        "content": {"min_df": 2},
                        "item_cf": {"neighbors": 100},
                        "dataset_manifest_sha256": "fixture",
                    },
                },
            )
            self.client.force_login(self.staff)
            response = self.client.get(reverse("dashboard"), {"group": "active", "k": "5"})
            self.assertContains(response, "nDCG@5")
            self.assertContains(response, "width:20.000%")
            self.assertTrue(all(row["users"] == 2 for row in response.context["benchmark"]))
            (folder / "test_metrics.json").write_text("{}", encoding="utf-8")
            response = self.client.get(reverse("dashboard"))
            self.assertEqual(response.context["benchmark"], [])
