from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.catalog.compatibility import devices_from_source, devices_from_title, sync_product_compatibilities
from apps.catalog.forms import CatalogFilterForm
from apps.catalog.models import Category, PhoneModel, Product, ProductCategory, ProductCompatibility


class DeviceParsingTests(SimpleTestCase):
    def names(self, text):
        return {d.name for d in devices_from_title(text)}

    def test_explicit_negative_does_not_become_verified_compatibility(self):
        cases = [
            (
                "Ailun for iPhone 11 Pro/ Xs/ X [NOT for iPhone 11,6.1 inch]",
                {"iPhone 11 Pro", "iPhone XS", "iPhone X"},
            ),
            ("Compatible for iPhone 12 Pro Max (Not for iPhone 12 Pro)", {"iPhone 12 Pro Max"}),
            ("Designed for iPhone 12 Pro Max [Not for iPhone 12 Pro]", {"iPhone 12 Pro Max"}),
            ("Case for Galaxy S22 Ultra; not compatible with Galaxy S22", {"Galaxy S22 Ultra"}),
            ("For Google Pixel 6 Pro (does not fit Pixel 6)", {"Pixel 6 Pro"}),
            ("iPhone 14 charger (Not Compatible with Quick Charge)", {"iPhone 14"}),
            ("iPhone 12/12 Pro (not for 12 Pro)", {"iPhone 12"}),
            ("Samsung Galaxy S22/S22 Ultra (not for S22)", {"Galaxy S22 Ultra"}),
            ("Ốp cho iPhone 12 Pro Max (không dùng cho iPhone 12 Pro)", {"iPhone 12 Pro Max"}),
        ]
        for title, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(self.names(title), expected)

    def test_se_requires_explicit_generation_and_keeps_exclusions_separate(self):
        cases = [
            ("Case for iPhone SE", set()),
            ("iPhone SE (1st gen - 2016)", {"iPhone SE (2016)"}),
            ("iPhone SE (2022/2020)", {"iPhone SE (2020)", "iPhone SE (2022)"}),
            ("iPhone SE 3 (2022), iPhone SE 2 (2020)", {"iPhone SE (2020)", "iPhone SE (2022)"}),
            ("Case for iPhone SE (3rd generation)", {"iPhone SE (2022)"}),
            ("iPhone SE (3rd and 2nd gen)/8/7", {
                "iPhone SE (2020)", "iPhone SE (2022)", "iPhone 8", "iPhone 7",
            }),
            (
                "(NOT for New iPhone SE) for Apple iPhone 5 / 5S / 2016 1st Gen SE ONLY",
                {"iPhone 5", "iPhone 5s", "iPhone SE (2016)"},
            ),
            (
                "iPhone SE (2016) (Not compatible with 2020 version of iPhone SE)",
                {"iPhone SE (2016)"},
            ),
            ("iPhone SE Case (2017)", set()),
        ]
        for title, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(self.names(title), expected)

    def test_samsung_pixel_lists_variants_and_family_only_are_distinct(self):
        names = self.names(
            "Samsung Galaxy S23 Ultra/S22+/Note 20 Ultra, Google Pixel 6 Pro/6/5a, iPhone 13Pro Max/12 mini"
        )
        self.assertEqual(
            names,
            {
                "Galaxy S23 Ultra",
                "Galaxy S22 Plus",
                "Galaxy Note 20 Ultra",
                "Pixel 6 Pro",
                "Pixel 6",
                "Pixel 5a",
                "iPhone 13 Pro Max",
                "iPhone 12 Mini",
            },
        )
        self.assertEqual(self.names("Universal for iPhone, Samsung Galaxy and Google Pixel"), set())
        self.assertEqual(self.names("Galaxy Note 21, Galaxy S5 Edge, Pixel 6 XL, iPhone 3"), set())
        self.assertEqual(self.names("iPhone 10s Max and iPhone XS Max"), {"iPhone XS Max"})
        self.assertEqual(self.names("iPhone SE2020 (Not for iPhone SE2022)"), {"iPhone SE (2020)"})

    def test_supported_source_names_and_older_phone_models(self):
        self.assertEqual(self.names("OtterBox for Samsung Galaxy S III"), {"Galaxy S3"})
        self.assertEqual(self.names("Screen protector for Galaxy Z Flip 3"), {"Galaxy Z Flip 3"})
        self.assertEqual(self.names("Slim case for LG G3 (not for LG G4)"), {"LG G3"})
        self.assertEqual(self.names("Case for Google Nexus 6P (not for 6)"), {"Nexus 6P"})
        self.assertEqual(self.names("USB-C charger for Nexus 6P/5X"), {"Nexus 6P", "Nexus 5X"})
        self.assertEqual(self.names("Wallet case for iPhone SE, Apple SE (2020)"), {"iPhone SE (2020)"})

    def test_screen_sizes_and_pack_counts_are_not_phone_models(self):
        cases = [
            ("iPhone 8,7,6s,6, 4.7-Inch, 3 Pack", {"iPhone 8", "iPhone 7", "iPhone 6s", "iPhone 6"}),
            ("iPhone 8 Plus,7 Plus,6s Plus,6 Plus, 5.5 Inch 3Pack", {"iPhone 8 Plus", "iPhone 7 Plus", "iPhone 6s Plus", "iPhone 6 Plus"}),
            ("Screen Protector for iPhone 7, 6 inch", {"iPhone 7"}),
            ("Case for iPhone 8, 5-Pack", {"iPhone 8"}),
            ("Case for iPhone 8, 4 pieces", {"iPhone 8"}),
            ("Case for iPhone 8/7/6, 4.7 inch", {"iPhone 8", "iPhone 7", "iPhone 6"}),
            ("Protector for iPhone 4.7-inch", set()),
            ("Case for iPhone 4, iPhone 5", {"iPhone 4", "iPhone 5"}),
        ]
        for title, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(self.names(title), expected)


class CompatibilitySyncTests(TestCase):
    def test_reviewed_shared_accessory_appears_for_each_phone_without_fake_links(self):
        headset = Product.objects.create(
            external_item_id="B0092KJ9BU",
            slug="headset",
            name="Tai nghe dùng chung",
            price=99000,
            is_active=True,
            source_metadata={
                "item_id": "B0092KJ9BU",
                "dataset_manifest_sha256": "test",
                "title": "Bluetooth Headset",
                "categories": ["Single Ear Bluetooth Headsets"],
            },
        )
        case = Product.objects.create(
            external_item_id="CASE",
            slug="case",
            name="Ốp lưng",
            price=99000,
            is_active=True,
        )
        category = Category.objects.create(name="Ốp lưng", slug="cases")
        ProductCategory.objects.create(product=case, category=category)
        apple = PhoneModel.objects.create(manufacturer="Apple", name="iPhone 7", slug="iphone-7")
        pixel = PhoneModel.objects.create(manufacturer="Google", name="Pixel 6", slug="pixel-6")
        ProductCompatibility.objects.create(product=case, phone_model=apple, verified=True)
        ProductCompatibility.objects.create(product=case, phone_model=pixel, verified=True)

        call_command("refresh_compatibilities", reviewed_only=True, stdout=StringIO())
        headset.refresh_from_db()
        self.assertFalse(headset.is_universal_accessory)
        call_command("refresh_compatibilities", reviewed_only=True, apply=True, stdout=StringIO())
        headset.refresh_from_db()
        self.assertTrue(headset.is_universal_accessory)
        self.assertFalse(headset.compatibilities.exists())

        url = reverse("product_list")
        for phone in (apple, pixel):
            response = self.client.get(url, {"phone": phone.pk})
            self.assertCountEqual(response.context["page_obj"], [case, headset])
            self.assertContains(response, "Phụ kiện dùng chung")
        selected = self.client.get(url, {"phone": apple.pk, "category": category.pk})
        self.assertEqual(list(selected.context["page_obj"]), [case])
        detail = self.client.get(reverse("product_detail", args=[headset.slug]))
        self.assertContains(detail, "Dùng được trên hầu hết thiết bị di động")
        self.assertContains(detail, "hỗ trợ âm thanh qua Bluetooth")

    def test_samsung_charger_uses_models_named_outside_the_title(self):
        product = Product.objects.create(
            external_item_id="B015CMD692",
            slug="samsung-usb-charger",
            name="Củ sạc Samsung",
            price=149000,
            is_active=True,
            source_metadata={
                "item_id": "B015CMD692",
                "title": "Samsung OEM Adapter with USB Sync Charging Cable",
                "features": ["Compatible with Samsung Galaxy Note 2, Galaxy S3, Galaxy S4"],
                "attributes": {"Compatible Phone Models": "Samsung Galaxy Note,Samsung Galaxy S5"},
            },
        )
        sync_product_compatibilities(product)
        models = PhoneModel.objects.filter(productcompatibility__product=product)
        self.assertEqual(
            set(models.values_list("name", flat=True)),
            {"Galaxy Note 2", "Galaxy S3", "Galaxy S4", "Galaxy S5"},
        )
        detail = self.client.get(reverse("product_detail", args=[product.slug]))
        self.assertContains(detail, "Samsung Galaxy S4")
        self.assertContains(detail, "Cáp đi kèm dùng đầu Micro USB")
        galaxy_s4 = models.get(name="Galaxy S4")
        filtered = self.client.get(reverse("product_list"), {"phone": galaxy_s4.pk})
        self.assertEqual(list(filtered.context["page_obj"]), [product])

    def test_travel_adapter_uses_connection_guidance_without_inventing_models(self):
        source = {
            "item_id": "B0C575KCXJ",
            "title": "NEWVANGA Universal Travel Adapter with Dual USB Charging Ports",
            "categories": ["Wall Chargers"],
        }
        product = Product.objects.create(
            external_item_id=source["item_id"],
            slug="travel-adapter",
            name="Đầu chuyển phích cắm du lịch",
            price=99000,
            is_active=True,
            source_metadata=source,
        )
        self.assertEqual(devices_from_source(source), [])
        response = self.client.get(reverse("product_detail", args=[product.slug]))
        self.assertContains(response, "Đầu chuyển du lịch có hai cổng USB")
        self.assertContains(response, "không đổi điện áp")
        self.assertNotContains(response, "Chưa xác nhận được mẫu máy")

    def test_generated_links_are_corrected_without_changing_manual_links_or_catalog(self):
        product = Product.objects.create(
            external_item_id="SAMPLE",
            slug="sample",
            name="Tên giữ nguyên",
            price=99000,
            stock=7,
            is_active=True,
            source_metadata={
                "title": "Case for iPhone 12 Pro Max (Not for iPhone 12 Pro), Galaxy S22 and Google Pixel 6",
                "dataset_manifest_sha256": "original",
            },
        )
        wrong = PhoneModel.objects.create(
            manufacturer="Apple", name="iPhone 12 Pro", slug="iphone-12-pro"
        )
        manual = PhoneModel.objects.create(manufacturer="Test", name="Manual", slug="manual")
        ProductCompatibility.objects.create(
            product=product, phone_model=wrong, source="metadata", verified=True
        )
        ProductCompatibility.objects.create(
            product=product, phone_model=manual, source="manual", verified=False
        )
        before = (product.name, product.price, product.stock, product.source_metadata.copy())
        call_command("refresh_compatibilities", stdout=StringIO())
        self.assertTrue(
            ProductCompatibility.objects.filter(product=product, phone_model=wrong).exists()
        )
        call_command("refresh_compatibilities", apply=True, stdout=StringIO())
        self.assertFalse(
            ProductCompatibility.objects.filter(product=product, phone_model=wrong).exists()
        )
        self.assertFalse(
            ProductCompatibility.objects.get(product=product, phone_model=manual).verified
        )
        names = set(
            ProductCompatibility.objects.filter(product=product, verified=True).values_list(
                "phone_model__name", flat=True
            )
        )
        self.assertEqual(names, {"iPhone 12 Pro Max", "Galaxy S22", "Pixel 6"})
        self.assertEqual(
            set(CatalogFilterForm().fields["phone"].queryset.values_list("name", flat=True)), names
        )
        ids = set(ProductCompatibility.objects.values_list("pk", flat=True))
        sync_product_compatibilities(product)
        self.assertEqual(set(ProductCompatibility.objects.values_list("pk", flat=True)), ids)
        product.refresh_from_db()
        self.assertEqual(
            (product.name, product.price, product.stock, product.source_metadata), before
        )
