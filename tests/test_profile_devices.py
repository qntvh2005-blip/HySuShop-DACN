from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.forms import ProfileForm
from apps.accounts.models import PreferredDevice, Profile
from apps.catalog.forms import CatalogFilterForm
from apps.catalog.models import PhoneModel, Product, ProductCompatibility
from apps.interactions.models import UserInteraction
from apps.recommendations.models import RecommendationLog


class ProfileDeviceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="device-shopper", first_name="Khách"
        )
        product = Product.objects.create(
            external_item_id="DEVICE-TEST",
            name="Phụ kiện thử",
            slug="device-test",
            price=99000,
            stock=5,
            is_active=True,
        )
        cls.apple = PhoneModel.objects.create(
            manufacturer="Apple", name="iPhone SE 2020", slug="se-2020"
        )
        cls.samsung = PhoneModel.objects.create(
            manufacturer="Samsung", name="Galaxy Note 10 Plus 5G", slug="note-10-plus-5g"
        )
        cls.unverified = PhoneModel.objects.create(
            manufacturer="Google", name="Pixel 6", slug="pixel-6"
        )
        for device in [cls.apple, cls.samsung]:
            ProductCompatibility.objects.create(product=product, phone_model=device, verified=True)
        ProductCompatibility.objects.create(
            product=product, phone_model=cls.unverified, verified=False
        )
        PreferredDevice.objects.create(user=cls.user, phone_model=cls.apple)

    def setUp(self):
        self.client.force_login(self.user)

    def test_profile_is_single_collapsed_select_and_persists_new_selection(self):
        page = self.client.get(reverse("profile"))
        field = page.context["form"]["preferred_devices"]
        self.assertEqual(field.value(), self.apple.pk)
        self.assertNotIn("multiple", str(field))
        self.assertNotIn('size="', str(field))
        self.assertIn("form-select device-select", str(field))
        self.assertIn("Samsung Galaxy Note 10 Plus 5G", str(field))
        saved = self.client.post(
            reverse("profile"), {"preferred_devices": self.samsung.pk, "first_name": "Khách"}
        )
        self.assertRedirects(saved, reverse("profile"))
        self.assertEqual(
            list(
                PreferredDevice.objects.filter(user=self.user).values_list(
                    "phone_model_id", flat=True
                )
            ),
            [self.samsung.pk],
        )
        self.assertContains(
            self.client.get(reverse("profile")),
            f'<option value="{self.samsung.pk}" selected>Samsung Galaxy Note 10 Plus 5G</option>',
            html=True,
        )

    def test_optional_selection_can_be_cleared(self):
        response = self.client.post(
            reverse("profile"), {"preferred_devices": "", "first_name": "Khách"}
        )
        self.assertRedirects(response, reverse("profile"))
        self.assertFalse(PreferredDevice.objects.filter(user=self.user).exists())

    def test_profile_phone_shows_legacy_error_and_validates_updates(self):
        url = reverse("profile")
        legacy_phone = "043333333333"
        stored, _ = Profile.objects.update_or_create(
            user=self.user, defaults={"phone": legacy_phone}
        )
        page = self.client.get(url)
        field = str(page.context["form"]["phone"])
        self.assertIn('maxlength="10"', field)
        self.assertIn('pattern="0[35789][0-9]{8}"', field)
        self.assertIn('aria-invalid="true"', field)
        self.assertIn(f'value="{legacy_phone}"', field)

        invalid = self.client.post(url, {"phone": "1045622622"})
        self.assertIn("phone", invalid.context["form"].errors)
        self.assertIn('aria-invalid="true"', str(invalid.context["form"]["phone"]))
        stored.refresh_from_db()
        self.assertEqual(stored.phone, legacy_phone)

        for phone in ["0912345678", ""]:
            with self.subTest(phone=phone):
                self.assertRedirects(self.client.post(url, {"phone": phone}), url)
                stored.refresh_from_db()
                self.assertEqual(stored.phone, phone)

    def test_preference_remains_editable_after_its_last_product_is_archived(self):
        ProductCompatibility.objects.filter(phone_model=self.apple).update(verified=False)
        profile = self.client.get(reverse("profile"))
        self.assertContains(
            profile,
            f'<option value="{self.apple.pk}" selected>Apple iPhone SE 2020</option>',
            html=True,
        )
        self.assertRedirects(
            self.client.post(reverse("profile"), {"preferred_devices": self.apple.pk}),
            reverse("profile"),
        )
        self.assertFalse(CatalogFilterForm().fields["phone"].queryset.filter(pk=self.apple.pk).exists())

    def test_invalid_selection_does_not_change_profile_or_preference(self):
        for value in [self.unverified.pk, "not-a-device", "999999999"]:
            with self.subTest(value=value):
                response = self.client.post(
                    reverse("profile"), {"preferred_devices": value, "first_name": "Đổi tên"}
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("preferred_devices", response.context["form"].errors)
                self.user.refresh_from_db()
                self.assertEqual(self.user.first_name, "Khách")
                self.assertEqual(
                    PreferredDevice.objects.get(user=self.user).phone_model_id, self.apple.pk
                )

    def test_filter_and_profile_share_full_verified_device_names(self):
        profile = ProfileForm().fields["preferred_devices"]
        catalog = CatalogFilterForm().fields["phone"]
        expected = {
            str(self.apple.pk): "Apple iPhone SE 2020",
            str(self.samsung.pk): "Samsung Galaxy Note 10 Plus 5G",
        }
        for field in [profile, catalog]:
            self.assertEqual(
                {str(value): label for value, label in field.choices if value}, expected
            )

    def test_home_keeps_general_products_and_shows_a_separate_verified_phone_group(self):
        other = Product.objects.create(
            external_item_id="OTHER", name="Pin sạc", slug="pin-sac",
            price=199000, stock=5, is_active=True,
        )
        with TemporaryDirectory() as directory, override_settings(ARTIFACT_ROOT=directory):
            page = self.client.get(reverse("home"))
        self.assertEqual(
            {p.pk for p in page.context["recommendation"].products},
            {other.pk, Product.objects.get(external_item_id="DEVICE-TEST").pk},
        )
        self.assertEqual(
            [p.external_item_id for p in page.context["device_recommendation"].products],
            ["DEVICE-TEST"],
        )
        self.assertContains(page, "Phụ kiện cho điện thoại của bạn")
        self.assertContains(page, "Apple iPhone SE 2020")
        self.assertEqual(page.context["hero_products"], page.context["recommendation"].products[:3])
        self.assertFalse(page.context["has_personalized_recommendation"])
        self.assertContains(page, "Sản phẩm được quan tâm")
        self.assertEqual(
            set(RecommendationLog.objects.values_list("context", flat=True)),
            {"personalized", "device"},
        )

    def test_home_without_phone_or_with_archived_phone_still_suggests_products(self):
        PreferredDevice.objects.filter(user=self.user).delete()
        with TemporaryDirectory() as directory, override_settings(ARTIFACT_ROOT=directory):
            page = self.client.get(reverse("home"))
            self.assertTrue(page.context["recommendation"].products)
            self.assertIsNone(page.context["device_recommendation"])
            self.assertNotContains(page, 'id="device-recommendations"')
            self.assertNotContains(page, "Gợi ý dành cho bạn")
            PreferredDevice.objects.create(user=self.user, phone_model=self.apple)
            ProductCompatibility.objects.filter(phone_model=self.apple).update(verified=False)
            page = self.client.get(reverse("home"))
        self.assertTrue(page.context["recommendation"].products)
        self.assertEqual(page.context["device_recommendation"].products, [])
        self.assertContains(page, "Chưa có phụ kiện phù hợp để gợi ý thêm")
        self.assertNotContains(page, f'?phone={self.apple.pk}')
        self.assertEqual(PreferredDevice.objects.get(user=self.user).phone_model, self.apple)

    def test_home_uses_real_model_history_and_guest_popularity_for_hero(self):
        from tests.test_recommenders import tiny_bundle

        PreferredDevice.objects.filter(user=self.user).delete()
        Product.objects.all().update(is_active=False)
        for code in ["A", "B", "C"]:
            Product.objects.create(
                external_item_id=code, name=code, slug=code.lower(),
                price=100, stock=5, is_active=True,
            )
        UserInteraction.objects.create(
            user=self.user, product=Product.objects.get(external_item_id="A"),
            event_type="favorite",
        )
        with patch(
            "apps.recommendations.services.active_bundle",
            return_value=(tiny_bundle(), {"model_version": "test", "serving_algorithm": "hybrid"}),
        ):
            page = self.client.get(reverse("home"))
            self.assertTrue(page.context["has_personalized_recommendation"])
            self.assertContains(page, "Gợi ý dành cho bạn")
            self.assertEqual(
                page.context["hero_products"], page.context["recommendation"].products[:3]
            )
            self.client.logout()
            page = self.client.get(reverse("home"))
        self.assertEqual(page.context["recommendation"].algorithm, "popularity")
        self.assertFalse(page.context["has_personalized_recommendation"])
        self.assertContains(page, "Sản phẩm được quan tâm")
        self.assertIsNone(page.context["preferred_device"])
