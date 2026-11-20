import uuid
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import PreferredDevice
from apps.cart.services import set_quantity
from apps.catalog.models import Brand, Category, PhoneModel, Product, ProductCategory
from apps.orders.models import OrderReturn
from apps.orders.services import checkout, transition_order
from tests.test_checkout import evidence_upload


class ManagementWorkflowTests(TestCase):
    def setUp(self):
        call_command("setup_roles", stdout=StringIO())
        self.staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        self.staff.groups.add(Group.objects.get(name="Admin"))
        self.buyer = get_user_model().objects.create_user(username="buyer")
        self.product = Product.objects.create(
            external_item_id="SOURCE",
            name="Product at checkout",
            slug="source",
            price=100,
            stock=10,
            is_active=True,
            source_metadata={"dataset_manifest_sha256": "frozen"},
        )
        self.category = Category.objects.create(name="Cases", slug="cases")
        ProductCategory.objects.create(product=self.product, category=self.category)
        set_quantity(user=self.buyer, product_id=self.product.pk, quantity=2)
        self.order = checkout(
            user=self.buyer,
            checkout_key=uuid.uuid4(),
            recipient_name="Recipient",
            phone="0900000000",
            address="Shipping address",
            payment_method="simulated",
        )
        self.client.force_login(self.staff)

    def test_custom_order_state_flow_and_return_restock_once(self):
        path = reverse("manage_order_transition", args=[self.order.pk])
        self.assertEqual(self.client.get(path).status_code, 405)
        self.client.post(path, {"to_status": "delivered"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "pending")
        for status in ["confirmed", "shipping", "delivered"]:
            self.assertRedirects(
                self.client.post(path, {"to_status": status, "reason": "Staff workflow"}),
                reverse("manage_order_detail", args=[self.order.pk]),
            )
            self.order.refresh_from_db()
            self.assertEqual(self.order.status, status)
        self.client.post(path, {"to_status": "return_requested"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "delivered")
        buyer = Client()
        buyer.force_login(self.buyer)
        detail = reverse("order_detail", args=[self.order.number])
        evidence = reverse("return_evidence", args=[self.order.number])
        self.assertContains(buyer.get(reverse("orders")), "Chi tiết")
        self.assertContains(buyer.get(detail), "Yêu cầu trả hàng")
        invalid = buyer.post(
            detail, {"reason": "Ảnh sai", "evidence": SimpleUploadedFile("anh.jpg", b"fake"), f"return_{self.order.items.get().pk}": 2}
        )
        self.assertContains(invalid, "ảnh JPG, PNG hoặc WebP hợp lệ")
        self.assertFalse(OrderReturn.objects.exists())
        self.assertRedirects(
            buyer.post(detail, {"reason": "Hàng bị hỏng", "evidence": evidence_upload(), f"return_{self.order.items.get().pk}": 2}), detail
        )
        buyer.post(detail, {"reason": "Yêu cầu trùng", "evidence": evidence_upload()})
        self.assertEqual(OrderReturn.objects.count(), 1)
        self.client.post(path, {"to_status": "returned"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "return_requested")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 8)
        staff_detail = reverse("manage_order_detail", args=[self.order.pk])
        self.assertContains(self.client.get(staff_detail), "Hàng bị hỏng")
        self.assertContains(self.client.get(staff_detail), evidence)
        self.assertEqual(self.client.get(evidence)["Content-Type"], "image/jpeg")
        self.assertEqual(buyer.get(evidence).status_code, 200)
        outsider = Client()
        outsider.force_login(get_user_model().objects.create_user(username="outsider"))
        self.assertEqual(outsider.get(evidence).status_code, 404)
        self.client.post(path, {"to_status": "return_approved", "reason": "Staff workflow"})
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual((self.order.status, self.product.stock), ("return_approved", 8))
        line = self.order.return_request.items.get()
        self.client.post(path, {"to_status": "returned", f"resellable_{line.pk}": 2})
        self.client.post(path, {"to_status": "returned", f"resellable_{line.pk}": 2})
        self.product.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.product.stock, 10)
        self.assertEqual(self.order.payment_status, "refunded")
        self.assertEqual(self.order.status_history.count(), 7)
        response = self.client.get(reverse("manage_order_detail", args=[self.order.pk]))
        self.assertContains(response, "Staff workflow")
        self.assertNotContains(response, 'name="to_status"')

    def test_rejection_requires_explanation_and_keeps_paid_order(self):
        for status in ["confirmed", "shipping", "delivered"]:
            transition_order(actor=self.staff, order_id=self.order.pk, to_status=status)
        buyer = Client()
        buyer.force_login(self.buyer)
        detail = reverse("order_detail", args=[self.order.number])
        buyer.post(detail, {"reason": "Muốn trả hàng", "evidence": evidence_upload(), f"return_{self.order.items.get().pk}": 2})
        path = reverse("manage_order_transition", args=[self.order.pk])
        self.client.post(path, {"to_status": "reject_return"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "return_requested")
        self.client.post(path, {"to_status": "reject_return", "reason": "Hàng còn nguyên vẹn"})
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual((self.order.status, self.order.payment_status), ("delivered", "paid"))
        self.assertEqual(self.product.stock, 8)
        self.assertContains(buyer.get(detail), "Hàng còn nguyên vẹn")

    def test_order_details_use_snapshot_and_search_uuid_prefix(self):
        self.product.name = "Changed after checkout"
        self.product.price = 999
        self.product.save()
        response = self.client.get(reverse("manage_order_detail", args=[self.order.pk]))
        self.assertContains(response, "Product at checkout")
        self.assertNotContains(response, "Changed after checkout")
        response = self.client.get(reverse("manage_orders"), {"q": str(self.order.number)[:8]})
        self.assertEqual(list(response.context["page_obj"]), [self.order])
        self.assertNotContains(response, "/admin/")

    def test_view_only_staff_cannot_process_orders_or_modify_products(self):
        observer = get_user_model().objects.create_user(username="observer", is_staff=True)
        observer.user_permissions.add(
            *Permission.objects.filter(codename__in=["view_order", "view_product"])
        )
        self.client.force_login(observer)
        response = self.client.get(reverse("manage_order_detail", args=[self.order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_transition"])
        self.assertEqual(
            self.client.post(
                reverse("manage_order_transition", args=[self.order.pk]), {"to_status": "confirmed"}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("manage_product_edit", args=[self.product.pk]), {"stock": 999}
            ).status_code,
            403,
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "pending")

    def test_customer_with_group_but_without_staff_flag_is_denied(self):
        self.buyer.groups.add(Group.objects.get(name="Admin"))
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(reverse("manage_products")).status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse("manage_order_transition", args=[self.order.pk]), {"to_status": "confirmed"}
            ).status_code,
            403,
        )
        transition_order(actor=self.staff, order_id=self.order.pk, to_status="confirmed")
        history_count = self.order.status_history.count()
        self.product.refresh_from_db()
        reserved_stock = self.product.stock
        self.assertEqual(
            self.client.post(reverse("cancel_order", args=[self.order.number])).status_code,
            403,
        )
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.status, "confirmed")
        self.assertEqual(self.product.stock, reserved_stock)
        self.assertEqual(self.order.status_history.count(), history_count)

    def test_order_action_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        self.assertEqual(
            client.post(
                reverse("manage_order_transition", args=[self.order.pk]), {"to_status": "confirmed"}
            ).status_code,
            403,
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "pending")

    def test_brand_and_preferred_phone_cannot_be_deleted_while_used(self):
        brand = Brand.objects.create(name="Brand", slug="brand")
        self.product.brand = brand
        self.product.save()
        phone = PhoneModel.objects.create(manufacturer="Apple", name="iPhone 13", slug="iphone13")
        PreferredDevice.objects.create(user=self.buyer, phone_model=phone)
        self.client.post(reverse("manage_taxonomy_delete", args=["thuong-hieu", brand.pk]))
        self.client.post(reverse("manage_taxonomy_delete", args=["thiet-bi", phone.pk]))
        self.assertTrue(Brand.objects.filter(pk=brand.pk).exists())
        self.assertTrue(PhoneModel.objects.filter(pk=phone.pk).exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.brand_id, brand.pk)

    def test_product_choices_hide_legacy_data_and_keep_existing_links(self):
        current = Brand.objects.create(name="Anker", slug="anker")
        legacy = Brand.objects.create(name="Legacy Brand", slug="old-brand")
        archived_category = Category.objects.create(name="Legacy Category", slug="old-category")
        archived = Product.objects.create(
            external_item_id="OLD", name="Old item", slug="old-item", brand=legacy
        )
        archived.categories.add(archived_category)
        self.product.brand = current
        self.product.save()
        response = self.client.get(reverse("manage_product_create"))
        self.assertContains(response, "Anker")
        self.assertNotContains(response, "Legacy Brand")
        self.assertNotContains(response, "Legacy Category")
        self.assertContains(response, 'class="category-picker"')
        self.assertContains(
            self.client.get(reverse("manage_product_edit", args=[archived.pk])), "Legacy Brand"
        )
        taxonomy = reverse("manage_taxonomy", args=["thuong-hieu"])
        self.assertNotContains(self.client.get(taxonomy), "Legacy Brand")
        self.assertContains(self.client.get(taxonomy, {"scope": "all"}), "Legacy Brand")

    def test_archived_out_of_sample_research_product_cannot_be_reactivated(self):
        self.product.is_active = False
        self.product.save()
        data = {
            "name": self.product.name,
            "price": "100",
            "stock": "10",
            "is_active": "on",
            "categories": [self.category.pk],
            "revision": self.product.updated_at.isoformat(),
        }
        with patch("research.data.dataset.ResearchDataset") as loader:
            loader.return_value.item_ids = ["DIFFERENT"]
            response = self.client.post(
                reverse("manage_product_edit", args=[self.product.pk]), data
            )
        self.assertTrue(response.context["form"].errors["is_active"])
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_active)

    def test_home_links_to_real_products_and_counts_active_categories(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Phụ kiện hợp gu,")
        self.assertTrue(
            all(
                product.is_active and product.stock > 0
                for product in response.context["hero_products"]
            )
        )
        self.assertEqual(
            [(category.pk, category.item_count) for category in response.context["categories"]],
            [(self.category.pk, 1)],
        )
        self.assertNotContains(response, "/admin/")
