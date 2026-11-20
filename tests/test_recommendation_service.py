import uuid
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.accounts.models import PreferredDevice
from apps.catalog.models import PhoneModel, Product, ProductCompatibility
from apps.interactions.models import UserInteraction
from apps.orders.models import Order, OrderItem
from apps.recommendations.models import RecommendationLog
from apps.recommendations.services import recommend


class RecommendationServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="recommendation-user")
        cls.a = Product.objects.create(
            external_item_id="A",
            name="Available",
            slug="available",
            price=100,
            stock=5,
            is_active=True,
        )
        cls.b = Product.objects.create(
            external_item_id="B",
            name="Out of stock",
            slug="out",
            price=100,
            stock=0,
            is_active=True,
        )
        cls.c = Product.objects.create(
            external_item_id="C",
            name="Inactive",
            slug="inactive",
            price=100,
            stock=5,
            is_active=False,
        )

    def test_missing_artifact_fallback_filters_and_logs(self):
        with (
            TemporaryDirectory() as directory,
            override_settings(ARTIFACT_ROOT=directory, RECOMMENDATION_MODEL_VERSION="missing"),
        ):
            result = recommend(user=self.user, context="personalized")
        self.assertEqual([p.pk for p in result.products], [self.a.pk])
        self.assertEqual(result.algorithm, "operational_popularity")
        self.assertIn("artifact_unavailable", result.fallback_reason)
        self.assertEqual(RecommendationLog.objects.get().item_ids, ["A"])

    def test_similar_excludes_current_product(self):
        with TemporaryDirectory() as directory, override_settings(ARTIFACT_ROOT=directory):
            self.assertEqual(recommend(context="similar", current_item_id="A").products, [])

    def test_device_filter_requires_verified_compatibility(self):
        phone = PhoneModel.objects.create(manufacturer="Test", name="Phone", slug="test-phone")
        compatibility = ProductCompatibility.objects.create(
            product=self.a, phone_model=phone, verified=False
        )
        with TemporaryDirectory() as directory, override_settings(ARTIFACT_ROOT=directory):
            self.assertEqual(recommend(phone_model_id=phone.pk).products, [])
            compatibility.verified = True
            compatibility.save()
            self.assertEqual(
                [p.pk for p in recommend(phone_model_id=phone.pk).products], [self.a.pk]
            )

    def test_stale_preference_does_not_empty_suggestions(self):
        phone = PhoneModel.objects.create(manufacturer="Test", name="Archived", slug="archived")
        ProductCompatibility.objects.create(product=self.c, phone_model=phone, verified=True)
        PreferredDevice.objects.create(user=self.user, phone_model=phone)
        with TemporaryDirectory() as directory, override_settings(ARTIFACT_ROOT=directory):
            self.assertEqual(recommend(user=self.user, context="personalized").products, [self.a])
            self.assertEqual(recommend(phone_model_id=phone.pk).products, [])

    def test_saved_phone_only_limits_the_separate_device_context(self):
        phone = PhoneModel.objects.create(manufacturer="Apple", name="iPhone 13", slug="iphone13")
        ProductCompatibility.objects.create(product=self.a, phone_model=phone, verified=True)
        PreferredDevice.objects.create(user=self.user, phone_model=phone)
        Product.objects.filter(pk=self.c.pk).update(is_active=True)
        with TemporaryDirectory() as directory, override_settings(ARTIFACT_ROOT=directory):
            general = recommend(user=self.user, context="personalized")
            cart = recommend(user=self.user, context="cart")
            device = recommend(user=self.user, context="device", phone_model_id=phone.pk)
        self.assertEqual({p.pk for p in general.products}, {self.a.pk, self.c.pk})
        self.assertEqual({p.pk for p in cart.products}, {self.a.pk, self.c.pk})
        self.assertEqual([p.pk for p in device.products], [self.a.pk])
        self.assertEqual(RecommendationLog.objects.get(context="device").item_ids, ["A"])
        ProductCompatibility.objects.filter(product=self.a).update(verified=False)
        with TemporaryDirectory() as directory, override_settings(ARTIFACT_ROOT=directory):
            self.assertEqual(recommend(context="device", phone_model_id=phone.pk).products, [])

    def test_device_ranking_uses_live_history_and_excludes_owned_and_unavailable_items(self):
        from tests.test_recommenders import tiny_bundle

        phone = PhoneModel.objects.create(manufacturer="Apple", name="iPhone 13", slug="iphone13")
        Product.objects.filter(pk=self.c.pk).update(is_active=True)
        for product in [self.a, self.b, self.c]:
            ProductCompatibility.objects.create(product=product, phone_model=phone, verified=True)
        UserInteraction.objects.create(user=self.user, product=self.a, event_type="favorite")
        model = tiny_bundle()
        with (
            patch(
                "apps.recommendations.services.active_bundle",
                return_value=(model, {"model_version": "test", "serving_algorithm": "hybrid"}),
            ),
            patch.object(model, "rank", wraps=model.rank) as rank,
        ):
            result = recommend(
                user=self.user, context="device", phone_model_id=phone.pk, current_item_id="A"
            )
        self.assertEqual([p.pk for p in result.products], [self.c.pk])
        self.assertEqual(rank.call_args.args[0], "hybrid")
        self.assertEqual(rank.call_args.kwargs["history_weights"], {"A": 3.0})
        order = Order.objects.create(
            user=self.user, checkout_key=uuid.uuid4(), recipient_name="Test",
            phone="0900000000", address="Test", subtotal=100, total=100,
        )
        OrderItem.objects.create(
            order=order, product=self.c, external_item_id_snapshot="C",
            name_snapshot="Inactive", unit_price=100, quantity=1, line_total=100,
        )
        with TemporaryDirectory() as directory, override_settings(ARTIFACT_ROOT=directory):
            result = recommend(
                user=self.user, context="device", phone_model_id=phone.pk, current_item_id="A"
            )
        self.assertEqual(result.products, [])

    def test_invalid_context_and_limit_rejected(self):
        for arguments in [{"limit": 0}, {"limit": 100}, {"context": "invalid"}, {"context": "device"}]:
            with self.assertRaises(ValueError):
                recommend(**arguments)

    def test_loaded_model_scores_live_history_and_filters_candidates(self):
        from tests.test_recommenders import tiny_bundle

        Product.objects.filter(pk=self.c.pk).update(is_active=True)
        UserInteraction.objects.create(user=self.user, product=self.a, event_type="favorite")
        with patch(
            "apps.recommendations.services.active_bundle",
            return_value=(
                tiny_bundle(),
                {"model_version": "test-model", "serving_algorithm": "content"},
            ),
        ):
            result = recommend(user=self.user, context="personalized", current_item_id="A")
        self.assertEqual([p.external_item_id for p in result.products], ["C"])
        self.assertEqual(result.algorithm, "content")
        self.assertEqual(result.model_version, "test-model")

    def test_purchased_filter_is_scoped_to_same_users_order(self):
        other = get_user_model().objects.create_user(username="other-buyer")
        orders = []
        for user, status in [(self.user, "cancelled"), (other, "delivered")]:
            order = Order.objects.create(
                user=user,
                status=status,
                checkout_key=uuid.uuid4(),
                recipient_name="Test",
                phone="0900000000",
                address="Test",
                subtotal=100,
                total=100,
            )
            OrderItem.objects.create(
                order=order,
                product=self.a,
                external_item_id_snapshot="A",
                name_snapshot="Available",
                unit_price=100,
                quantity=1,
                line_total=100,
            )
            orders.append(order)
        with TemporaryDirectory() as directory, override_settings(ARTIFACT_ROOT=directory):
            self.assertEqual(
                [p.pk for p in recommend(user=self.user, context="personalized").products],
                [self.a.pk],
            )
            orders[0].status = "pending"
            orders[0].save()
            self.assertEqual(recommend(user=self.user, context="personalized").products, [])

    def test_views_are_used_but_repeated_views_do_not_overweight(self):
        from tests.test_recommenders import tiny_bundle

        model = tiny_bundle()
        Product.objects.filter(pk=self.c.pk).update(is_active=True)
        for _ in range(3):
            UserInteraction.objects.create(user=self.user, product=self.a, event_type="view")
        with (
            patch(
                "apps.recommendations.services.active_bundle",
                return_value=(model, {"model_version": "test", "serving_algorithm": "content"}),
            ),
            patch.object(model, "rank", wraps=model.rank) as rank,
        ):
            result = recommend(user=self.user, context="personalized", current_item_id="A")
        self.assertEqual(result.algorithm, "content")
        self.assertEqual(result.fallback_reason, "")
        self.assertEqual(rank.call_args.kwargs["history_weights"], {"A": 1.0})
