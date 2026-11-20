"""The custom back office preserves the same data safety as the former generic admin."""

from datetime import timedelta
from io import BytesIO, StringIO
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.catalog.compatibility import sync_product_compatibilities
from apps.catalog.models import (
    Brand,
    Category,
    PhoneModel,
    Product,
    ProductCategory,
    ProductCompatibility,
    ProductImage,
)
from apps.orders.models import Order, OrderItem


class CatalogAdminTests(TestCase):
    def setUp(self):
        call_command("setup_roles", stdout=StringIO())
        self.staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        self.staff.groups.add(Group.objects.get(name="Admin"))
        self.product = Product.objects.create(
            external_item_id="SOURCE",
            name="Source item",
            slug="source-item",
            source_metadata={"dataset_manifest_sha256": "frozen", "title": "Original title"},
            price=100,
            stock=3,
            is_active=True,
        )
        self.category = Category.objects.create(name="Cases", slug="cases")
        ProductCategory.objects.create(product=self.product, category=self.category)
        self.client.force_login(self.staff)

    def payload(self):
        return {
            "name": "Tên mới",
            "external_item_id": "FORGED",
            "description": "Mô tả",
            "feature_lines": "Đặc điểm 1\nĐặc điểm 2",
            "price": "199000",
            "stock": "8",
            "is_active": "on",
            "categories": [self.category.pk],
            "revision": self.product.updated_at.isoformat(),
            "source_metadata": '{"dataset_manifest_sha256":"forged"}',
            "price_source": "forged",
        }

    def test_research_identity_and_metadata_cannot_be_edited_or_deleted(self):
        response = self.client.get(reverse("manage_product_edit", args=[self.product.pk]))
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertTrue(form.fields["external_item_id"].disabled)
        self.assertNotIn("source_metadata", form.fields)
        self.assertNotIn("price_source", form.fields)
        self.assertEqual(
            self.client.post(reverse("manage_product_delete", args=[self.product.pk])).status_code,
            403,
        )
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())
        self.assertNotContains(response, "Site quản trị hệ thống")

    def test_stock_price_and_storefront_changes_preserve_source_metadata(self):
        response = self.client.post(
            reverse("manage_product_edit", args=[self.product.pk]), self.payload()
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.external_item_id, "SOURCE")
        self.assertEqual(
            self.product.source_metadata,
            {"dataset_manifest_sha256": "frozen", "title": "Original title"},
        )
        self.assertEqual(
            (self.product.price, self.product.stock, self.product.price_source),
            (199000, 8, "manual_demo"),
        )
        self.assertEqual(self.product.name, "Tên mới")
        self.assertEqual(self.product.features, ["Đặc điểm 1", "Đặc điểm 2"])
        self.assertEqual(list(self.product.categories.all()), [self.category])

    def test_stale_form_cannot_overwrite_stock_after_checkout(self):
        payload = self.payload()
        Product.objects.filter(pk=self.product.pk).update(
            stock=2, updated_at=self.product.updated_at + timedelta(seconds=1)
        )
        response = self.client.post(reverse("manage_product_edit", args=[self.product.pk]), payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["revision"])
        self.product.refresh_from_db()
        self.assertEqual((self.product.stock, self.product.name), (2, "Source item"))

    def test_category_required_and_invalid_price_and_stock_are_atomic(self):
        for changes in [{"categories": []}, {"price": "-1"}, {"stock": "-3"}, {"price": ""}]:
            data = {**self.payload(), **changes}
            response = self.client.post(
                reverse("manage_product_edit", args=[self.product.pk]), data
            )
            self.assertTrue(response.context["form"].errors)
            self.product.refresh_from_db()
            self.assertEqual(
                (self.product.name, self.product.price, self.product.stock), ("Source item", 100, 3)
            )

    def test_manual_product_creation_and_deletion(self):
        data = {
            **self.payload(),
            "external_item_id": "MANUAL",
            "source_metadata": '{"dataset_manifest_sha256":"forged"}',
        }
        self.assertEqual(self.client.post(reverse("manage_product_create"), data).status_code, 302)
        manual = Product.objects.get(external_item_id="MANUAL")
        self.assertEqual(manual.source_metadata, {})
        self.assertEqual(manual.currency, "VND")
        self.assertEqual(
            self.client.post(reverse("manage_product_delete", args=[manual.pk])).status_code, 302
        )
        self.assertFalse(Product.objects.filter(pk=manual.pk).exists())

    def test_customer_and_csrf_cannot_write_catalog(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        path = reverse("manage_product_edit", args=[self.product.pk])
        self.assertEqual(csrf_client.post(path, self.payload()).status_code, 403)
        customer = get_user_model().objects.create_user(username="customer")
        self.client.force_login(customer)
        for path in [
            reverse("manage_products"),
            path,
            reverse("manage_taxonomy", args=["danh-muc"]),
        ]:
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_image_deletion_checks_product_ownership(self):
        other = Product.objects.create(external_item_id="OTHER", slug="other", name="Other")
        image = ProductImage.objects.create(
            product=other, image_url="https://example.com/other.png"
        )
        self.assertEqual(
            self.client.post(
                reverse("manage_image_delete", args=[self.product.pk, image.pk])
            ).status_code,
            404,
        )
        self.assertTrue(ProductImage.objects.filter(pk=image.pk).exists())

    def test_local_image_upload_preview_markup_and_safe_file_cleanup(self):
        add = reverse("manage_image_add", args=[self.product.pk])
        editor = reverse("manage_product_edit", args=[self.product.pk])
        existing = ProductImage.objects.create(
            product=self.product, image_url="https://example.com/existing.png"
        )
        content = BytesIO()
        Image.new("RGBA", (1800, 1200), (255, 0, 0, 128)).save(content, format="PNG")
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            invalid = self.client.post(
                add, {"file": SimpleUploadedFile("bad.png", b"not an image")}, follow=True
            )
            self.assertContains(invalid, "Vui lòng chọn ảnh JPG, PNG hoặc WebP hợp lệ")
            self.assertEqual(self.product.images.count(), 1)
            for filename in ("first.png", "second.png"):
                response = self.client.post(
                    add, {"file": SimpleUploadedFile(filename, content.getvalue()), "alt": "Ảnh mới"}
                )
                self.assertEqual(response.url, editor + "#product-images")

            first, second = self.product.images.exclude(file="")
            self.assertEqual([first.position, second.position], [1, 2])
            with first.file.open("rb") as saved, Image.open(saved) as image:
                self.assertEqual(image.format, "WEBP")
                self.assertEqual(image.width, 1600)
                self.assertIn("A", image.getbands())
            response = self.client.get(editor)
            self.assertContains(response, 'enctype="multipart/form-data"')
            self.assertContains(response, "Xem trước ảnh sản phẩm")
            self.assertContains(response, first.display_url)
            detail = self.client.get(reverse("product_detail", args=[self.product.slug]))
            self.assertContains(detail, "detail-slide", count=3)
            self.assertContains(detail, 'class="detail-slide" hidden', count=2)
            self.assertContains(detail, 'aria-label="Ảnh trước"')
            self.assertContains(detail, 'aria-label="Ảnh tiếp theo"')
            self.assertContains(detail, existing.display_url)
            self.assertContains(detail, first.display_url)

            order = Order.objects.create(user=self.staff, checkout_key=uuid4(), subtotal=100, total=100)
            OrderItem.objects.create(
                order=order, product=self.product, external_item_id_snapshot=self.product.external_item_id,
                name_snapshot=self.product.name, image_snapshot=second.display_url,
                unit_price=100, quantity=1, line_total=100,
            )
            with self.captureOnCommitCallbacks(execute=True):
                for image in (first, second):
                    self.client.post(reverse("manage_image_delete", args=[self.product.pk, image.pk]))
            self.assertFalse(first.file.storage.exists(first.file.name))
            self.assertTrue(second.file.storage.exists(second.file.name))
            self.assertEqual(list(self.product.images.all()), [existing])

    def test_catalog_status_totals_distinguish_active_and_archived_rows(self):
        Product.objects.create(external_item_id="ARCHIVED", slug="archived", name="Archived")
        response = self.client.get(reverse("manage_products"), {"state": "archived"})
        self.assertContains(response, "1 đang mở bán · 1 đã ngừng bán")
        self.assertEqual(response.context["page_obj"].paginator.count, 1)

    def test_search_matches_product_types_before_features_in_both_catalogs(self):
        grip_brand = Brand.objects.create(name="PopSockets", slug="popsockets")
        grip = Product.objects.create(
            external_item_id="GRIP",
            name="Tay cầm điện thoại",
            slug="grip",
            brand=grip_brand,
            features=["Chất liệu: Silicone, Kính."],
            price=79000,
            is_active=True,
        )
        glass = Product.objects.create(
            external_item_id="GLASS",
            name="Kính cường lực bảo vệ màn hình",
            slug="glass",
            features=["Hạn chế bám vân tay", "Hỗ trợ thao tác cảm ứng", "Vật liệu: Bao da"],
            price=99000,
            is_active=True,
        )
        grip.categories.add(Category.objects.create(name="Tay cầm và vòng giữ điện thoại", slug="grips"))
        glass.categories.add(Category.objects.create(name="Miếng dán và kính bảo vệ màn hình", slug="screens"))
        charger = Product.objects.create(
            external_item_id="CAR-CHARGER", name="Mẫu sạc", slug="car-charger",
            price=99000, is_active=True,
        )
        charger.categories.add(Category.objects.create(name="Bộ sạc trên ô tô", slug="car-chargers"))
        hybrid = Product.objects.create(
            external_item_id="HYBRID", name="Pin dự phòng kiêm củ sạc", slug="hybrid",
            price=99000, is_active=True,
        )
        hybrid.categories.add(Category.objects.create(name="Củ sạc điện thoại", slug="wall-chargers"))
        for url in (reverse("manage_products"), reverse("product_list")):
            for query, expected in (
                ("tay cầm", [grip]), ("TAY CAM", [grip]), ("tay cầm PopSockets", [grip]),
                ("kính", [glass]), ("kinh cuong luc", [glass]), ("GRIP", [grip]),
                ("bao da", []), ("sạc ô tô", [charger]), ("bộ sạc trên ô tô", [charger]),
                ("pin dự phòng", [hybrid]),
            ):
                with self.subTest(url=url, query=query):
                    response = self.client.get(url, {"q": query})
                    self.assertEqual(list(response.context["page_obj"]), expected)

    def test_manual_negative_compatibility_survives_resync(self):
        phone = PhoneModel.objects.create(manufacturer="Apple", name="iPhone 13", slug="iphone13")
        ProductCompatibility.objects.create(
            product=self.product, phone_model=phone, verified=True, source="metadata"
        )
        self.client.post(
            reverse("manage_compatibility_save", args=[self.product.pk]), {"phone_model": phone.pk}
        )
        link = self.product.compatibilities.get()
        self.assertFalse(link.verified)
        self.assertEqual(link.source, "manual")
        sync_product_compatibilities(self.product, [])
        self.assertTrue(
            ProductCompatibility.objects.filter(
                pk=link.pk, verified=False, source="manual"
            ).exists()
        )

    def test_taxonomy_crud_duplicate_and_used_record_protection(self):
        for kind, data, model in [
            ("danh-muc", {"name": "New category"}, Category),
            ("thuong-hieu", {"name": "New brand"}, Brand),
            ("thiet-bi", {"name": "Test phone", "manufacturer": "Test"}, PhoneModel),
        ]:
            path = reverse("manage_taxonomy_create", args=[kind])
            result = self.client.post(path, data, follow=True)
            self.assertEqual(result.status_code, 200)
            self.assertContains(result, "Đang mở bán")
            self.assertNotContains(result, "Tổng liên kết")
            self.assertNotContains(result, "Danh sách chọn khi nhập sản phẩm")
            obj = model.objects.get(name=data["name"])
            self.assertEqual([row.pk for row in result.context["page_obj"]], [obj.pk])
            self.assertEqual(result.context["page_obj"][0].active_count, 0)
            self.assertEqual(
                self.client.get(reverse("manage_taxonomy_edit", args=[kind, obj.pk])).status_code,
                200,
            )
            duplicate = self.client.post(path, data)
            self.assertTrue(duplicate.context["form"].errors)
            self.client.post(reverse("manage_taxonomy_delete", args=[kind, obj.pk]))
            self.assertFalse(model.objects.filter(pk=obj.pk).exists())
        self.client.post(reverse("manage_taxonomy_delete", args=["danh-muc", self.category.pk]))
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())

    def test_old_admin_routes_are_not_mounted_and_lists_render(self):
        self.assertRedirects(self.client.get("/admin/"), reverse("dashboard"))
        self.assertEqual(self.client.get("/admin/catalog/product/").status_code, 404)
        for name, args in [
            ("manage_products", []),
            ("manage_orders", []),
            ("manage_activity", []),
            ("manage_recommendations", []),
            ("manage_taxonomy", ["danh-muc"]),
            ("manage_taxonomy", ["thuong-hieu"]),
            ("manage_taxonomy", ["thiet-bi"]),
        ]:
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Không gian quản trị")
            self.assertNotContains(response, "/admin/")
