from copy import deepcopy
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.catalog.localization import localized_product
from apps.catalog.models import Brand, Category, Product, ProductCategory, ProductImage

SOURCE = {
    "item_id": "B0TEST",
    "title": "Spigen Rugged Armor Case for iPhone 13 (NOT for iPhone 13 Pro Max) - Black",
    "categories": ["Cell Phones & Accessories", "Basic Cases"],
    "description": ["Original supplier paragraph."],
    "features": ["Original supplier feature."],
    "attributes": {
        "Brand": "Spigen",
        "Color": "Black",
        "Material": "Thermoplastic Polyurethane",
        "Special Feature": "Scratch Resistant, Unknown marketing prose",
        "Item model number": "ACS-13",
    },
    "dataset_manifest_sha256": "retained-hash",
}


class SummaryTests(SimpleTestCase):
    def test_summary_uses_explicit_facts_and_preserves_source(self):
        before = deepcopy(SOURCE)
        result = localized_product(SOURCE)
        self.assertEqual(SOURCE, before)
        self.assertIn("Ốp lưng điện thoại Spigen Rugged Armor cho iPhone 13", result["name"])
        self.assertNotIn("Pro Max", result["name"])
        self.assertIn("Màu sắc: Đen.", result["features"])
        self.assertIn("Chất liệu: Nhựa TPU.", result["features"])
        self.assertIn("Hạn chế trầy xước", result["features"])
        self.assertNotIn("Unknown marketing prose", " ".join(result["features"]))

    def test_missing_specs_are_not_invented(self):
        result = localized_product({"title": "Unknown accessory", "categories": ["Accessories"]})
        self.assertEqual(result["name"], "Phụ kiện điện thoại")
        self.assertEqual(result["features"], [])

    def test_summary_and_compatibility_share_exclusions_and_se_generations(self):
        from apps.catalog.compatibility import devices_from_title

        title = "Case for iPhone SE 2 (2020), iPhone SE 3 (2022); not for iPhone 13"
        item = {
            "title": title,
            "categories": ["Basic Cases"],
            "attributes": {
                "Compatible Phone Models": "iPhone 15",
                "Item model number": "iPhone 13",
            },
        }
        result = localized_product(item)
        self.assertIn("iPhone SE (2020)", result["name"])
        self.assertIn("iPhone SE (2022)", result["name"])
        self.assertNotIn("iPhone 13", result["name"])
        self.assertNotIn("iPhone 15", result["description"])
        self.assertEqual(
            {d.name for d in devices_from_title(title)}, {"iPhone SE (2020)", "iPhone SE (2022)"}
        )

    def test_title_variants_remain_distinguishable_without_invented_specs(self):
        def summary(title, attributes=None):
            return localized_product(
                {
                    "title": title,
                    "categories": ["Wireless Chargers"],
                    "attributes": attributes or {},
                }
            )

        single = summary("Yootech Wireless Charger X2")
        pair = summary("Yootech [2 Pack] Wireless Charger X2")
        self.assertNotEqual(single["name"], pair["name"])
        self.assertIn("Bộ 2 chiếc", pair["name"])
        cable = summary("Anker 24W Car Charger", {"Brand": "Anker", "Connector Type": "Lightning"})
        usb = summary("Anker 320 Car Charger (24W II)", {"Brand": "Anker", "Connector Type": "USB"})
        self.assertNotEqual(cable["name"], usb["name"])
        self.assertIn("Lightning", cable["name"])
        self.assertIn("320", usb["name"])
        vent = summary("WixGear Air Vent Magnetic Phone Car Mount")
        dashboard = summary("WixGear Dashboard Magnetic Phone Car Mount")
        self.assertNotEqual(vent["name"], dashboard["name"])

    def test_phone_and_watch_charger_is_not_solar_charger(self):
        result = localized_product(
            {"title": "Charger for iPhone and Apple Watch", "categories": ["Charging Stations"]}
        )
        self.assertEqual(result["name"], "Trạm sạc điện thoại và đồng hồ")
        self.assertNotIn("năng lượng", result["name"])

    def test_case_with_screen_protection_keeps_its_main_product_type(self):
        for qualifier in ("with", "without"):
            result = localized_product(
                {
                    "title": f"Rugged Case for Galaxy S8 {qualifier} Built-in Screen Protector",
                    "categories": ["Basic Cases"],
                }
            )
            self.assertTrue(result["name"].startswith("Ốp lưng điện thoại"))
        protector = localized_product(
            {
                "title": "Case Friendly Screen Protector for Galaxy S8",
                "categories": ["Screen Protectors"],
            }
        )
        self.assertTrue(protector["name"].startswith("Miếng dán bảo vệ màn hình"))


class LocalizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.brand = Brand.objects.create(name="Spigen", slug="spigen")
        cls.category = Category.objects.create(name="Basic Cases", slug="original-category-slug")
        cls.product = Product.objects.create(
            external_item_id="B0TEST",
            name=SOURCE["title"],
            slug="original-product-slug",
            source_metadata=SOURCE,
            brand=cls.brand,
            price=99000,
            stock=7,
            is_active=True,
        )
        ProductCategory.objects.create(product=cls.product, category=cls.category)
        ProductImage.objects.create(
            product=cls.product, image_url="https://example.com/product.jpg", alt=SOURCE["title"]
        )

    def test_preview_apply_idempotency_and_operational_preservation(self):
        call_command("localize_catalog", stdout=StringIO())
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, SOURCE["title"])
        call_command("localize_catalog", apply=True, stdout=StringIO())
        self.product.refresh_from_db()
        self.category.refresh_from_db()
        self.assertTrue(self.product.name.startswith("Ốp lưng"))
        self.assertEqual(self.category.name, "Ốp lưng điện thoại")
        self.assertEqual(self.category.slug, "original-category-slug")
        self.assertEqual(self.product.slug, "original-product-slug")
        self.assertEqual(self.product.source_metadata, SOURCE)
        self.assertEqual(
            (self.product.price, self.product.stock, self.product.is_active), (99000, 7, True)
        )
        self.assertEqual(self.product.images.get().alt, self.product.name)
        output = StringIO()
        call_command("localize_catalog", apply=True, stdout=output)
        self.assertIn("Products: 0; categories: 0", output.getvalue())

    def test_vietnamese_search_source_search_and_filter_labels(self):
        call_command("localize_catalog", apply=True, stdout=StringIO())
        for query in [
            "ốp lưng",
            "ỐP LƯNG",
            "op lung",
            "nhựa TPU",
            "nhua TPU",
            "Spigen",
            "B0TEST",
            "Rugged Armor Case",
        ]:
            with self.subTest(query=query):
                response = self.client.get(reverse("product_list"), {"q": query})
                self.assertEqual(list(response.context["page_obj"]), [self.product])
        for query in ["sac", "sạc"]:
            response = self.client.get(reverse("product_list"), {"q": query})
            self.assertEqual(list(response.context["page_obj"]), [])
        filtered = self.client.get(reverse("product_list"), {"category": self.category.pk})
        self.assertContains(filtered, "Ốp lưng điện thoại")
        self.assertNotContains(filtered, ">Basic Cases<")
        detail = self.client.get(reverse("product_detail", args=[self.product.slug]))
        self.assertContains(detail, "Chất liệu: Nhựa TPU.")
        self.assertNotContains(detail, "Original supplier paragraph.")

    def test_reviewed_category_correction_moves_only_the_source_category(self):
        from apps.catalog.management.commands.import_research_catalog import stable_slug

        source = {
            **SOURCE,
            "item_id": "B085W5XVV6",
            "title": "USB C Type Charging Cable",
            "categories": ["Automobile Chargers"],
        }
        original = Category.objects.create(
            name="Bộ sạc trên ô tô", slug=stable_slug("Automobile Chargers")
        )
        self.product.external_item_id = source["item_id"]
        self.product.source_metadata = source
        self.product.save()
        self.product.categories.add(original)

        call_command("localize_catalog", repair_filters=True, apply=True, stdout=StringIO())
        target = Category.objects.get(slug=stable_slug("Cables & Adapters"))
        self.product.refresh_from_db()
        self.assertEqual(set(self.product.categories.all()), {self.category, target})
        self.assertEqual(self.product.source_metadata, source)
        self.assertEqual((self.product.price, self.product.stock), (99000, 7))
        response = self.client.get(reverse("product_list"), {"category": target.pk})
        self.assertEqual(list(response.context["page_obj"]), [self.product])

    def test_category_search_ignores_case_and_accents(self):
        self.category.name = "Ốp lưng điện thoại"
        self.category.save()
        for query in ("ốp lưng", "op lung", "ỐP LƯNG"):
            with self.subTest(query=query):
                response = self.client.get(reverse("product_list"), {"q": query})
                self.assertEqual(list(response.context["page_obj"]), [self.product])
