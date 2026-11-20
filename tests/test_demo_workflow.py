"""Exercise the customer and staff routes together using an isolated database."""

import uuid
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import PreferredDevice
from apps.cart.models import CartItem
from apps.catalog.models import Category, PhoneModel, Product, ProductCompatibility
from apps.interactions.models import Favorite, ProductReview, UserInteraction
from apps.orders.models import Order
from tests.test_checkout import evidence_upload


class DemoWorkflowTests(TestCase):
    def test_customer_to_staff_delivery_review_and_return(self):
        call_command("setup_roles", stdout=StringIO())
        product = Product.objects.create(
            external_item_id="DEMO-FLOW",
            name="Ốp lưng demo",
            slug="op-lung-demo",
            price=99000,
            stock=5,
            is_active=True,
        )
        product.categories.add(Category.objects.create(name="Ốp lưng", slug="op-lung"))
        phone = PhoneModel.objects.create(
            manufacturer="Samsung", name="Galaxy S21", slug="galaxy-s21"
        )
        ProductCompatibility.objects.create(product=product, phone_model=phone, verified=True)
        password = "Demo-workflow-4739!"
        self.assertRedirects(
            self.client.post(
                reverse("signup"),
                {
                    "username": "demo-buyer",
                    "email": "buyer@example.test",
                    "password1": password,
                    "password2": password,
                },
            ),
            reverse("home"),
        )
        buyer = get_user_model().objects.get(username="demo-buyer")
        self.client.logout()
        self.assertRedirects(
            self.client.post(reverse("login"), {"username": buyer.username, "password": password}),
            reverse("home"),
        )
        self.assertRedirects(
            self.client.post(
                reverse("profile"),
                {
                    "first_name": "Khách",
                    "last_name": "Demo",
                    "email": buyer.email,
                    "phone": "0900000000",
                    "default_address": "TP.HCM",
                    "preferred_devices": phone.pk,
                },
            ),
            reverse("profile"),
        )
        self.assertEqual(PreferredDevice.objects.get(user=buyer).phone_model, phone)
        response = self.client.get(
            reverse("product_list"),
            {
                "q": "op lung",
                "phone": phone.pk,
                "price_range": "under_100",
            },
        )
        self.assertEqual(list(response.context["page_obj"]), [product])
        self.assertContains(
            self.client.get(reverse("product_detail", args=[product.slug])), product.name
        )
        self.client.post(reverse("toggle_favorite", args=[product.pk]))
        self.assertTrue(Favorite.objects.filter(user=buyer, product=product).exists())
        self.client.post(reverse("update_cart", args=[product.pk]), {"quantity": 2})
        payload = {
            "checkout_key": str(uuid.uuid4()),
            "recipient_name": "Khách Demo",
            "phone": "0900000000",
            "address": "TP.HCM",
            "payment_method": "simulated",
        }
        response = self.client.post(reverse("checkout"), payload)
        order = Order.objects.get(user=buyer)
        self.assertRedirects(response, reverse("order_detail", args=[order.number]))
        self.client.post(reverse("checkout"), payload)
        self.assertEqual(Order.objects.filter(user=buyer).count(), 1)
        self.assertEqual(order.total, 198000)
        self.assertFalse(CartItem.objects.filter(cart__user=buyer).exists())
        product.refresh_from_db()
        self.assertEqual(product.stock, 3)
        self.assertEqual(
            set(UserInteraction.objects.filter(user=buyer).values_list("event_type", flat=True)),
            {"view", "favorite", "add_to_cart", "purchase"},
        )
        self.assertEqual(
            UserInteraction.objects.filter(user=buyer, event_type="purchase").count(), 1
        )
        other = Client()
        other.force_login(get_user_model().objects.create_user(username="other-demo"))
        self.assertEqual(other.get(reverse("order_detail", args=[order.number])).status_code, 404)
        self.assertEqual(self.client.get(reverse("manage_orders")).status_code, 403)

        staff = get_user_model().objects.create_user(username="demo-staff", is_staff=True)
        staff.groups.add(Group.objects.get(name="Admin"))
        manager = Client()
        manager.force_login(staff)
        path = reverse("manage_order_transition", args=[order.pk])
        for status in ["confirmed", "shipping", "delivered"]:
            self.assertRedirects(
                manager.post(path, {"to_status": status, "reason": "Kiểm thử demo"}),
                reverse("manage_order_detail", args=[order.pk]),
            )
        self.client.post(
            reverse("review_product", args=[product.pk]),
            {
                "rating": 5,
                "comment": "Đã nhận sản phẩm demo.",
            },
        )
        self.assertEqual(ProductReview.objects.get(user=buyer, product=product).rating, 5)
        self.client.post(
            reverse("order_detail", args=[order.number]),
            {"reason": "Sản phẩm cần đổi", "evidence": evidence_upload(), f"return_{order.items.get().pk}": 2},
        )
        for status in ["return_approved", "returned", "returned"]:
            line = order.return_request.items.get()
            manager.post(path, {"to_status": status, "reason": "Kiểm thử hoàn tồn", f"resellable_{line.pk}": 2})
        order.refresh_from_db()
        product.refresh_from_db()
        self.assertEqual(order.status, "returned")
        self.assertEqual(order.payment_status, "refunded")
        self.assertEqual(product.stock, 5)
        self.assertEqual(order.status_history.count(), 7)
