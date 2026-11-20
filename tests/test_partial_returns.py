import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.cart.services import set_quantity
from apps.catalog.models import Product
from apps.orders.services import checkout, request_order_return, transition_order
from apps.recommendations.services import recommend
from tests.test_checkout import evidence_upload


class PartialReturnTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="partial-buyer")
        self.admin = get_user_model().objects.create_superuser(username="partial-admin", password="test")
        self.products = []
        for index, price in enumerate([100000, 150000, 200000]):
            product = Product.objects.create(
                external_item_id=f"RETURN{index}", slug=f"return-{index}",
                name=f"Phụ kiện {index}", price=price, stock=10, is_active=True,
            )
            self.products.append(product)
            set_quantity(user=self.user, product_id=product.pk, quantity=2)
        self.order = checkout(
            user=self.user, checkout_key=uuid.uuid4(), recipient_name="Khách hàng",
            phone="0900000000", address="TP.HCM",
        )
        for status in ["confirmed", "shipping", "delivered"]:
            transition_order(actor=self.admin, order_id=self.order.pk, to_status=status)

    def test_customer_selects_one_line_and_damaged_item_does_not_restock(self):
        self.client.force_login(self.user)
        item = self.order.items.get(product=self.products[0])
        response = self.client.post(reverse("order_detail", args=[self.order.number]), {
            "reason": "Một sản phẩm bị hỏng", "evidence": evidence_upload(), f"return_{item.pk}": 1,
        })
        self.assertEqual(response.status_code, 302)
        claim = self.order.return_request
        self.assertEqual(claim.items.count(), 1)
        transition_order(actor=self.admin, order_id=self.order.pk, to_status="return_approved")
        line = claim.items.get()
        for inspections in [None, {line.pk: -1}, {line.pk: 2}, {line.pk: True}, {999999: 0}]:
            with self.assertRaises(ValidationError):
                transition_order(actor=self.admin, order_id=self.order.pk, to_status="returned", inspections=inspections)
        transition_order(actor=self.admin, order_id=self.order.pk, to_status="returned", inspections={line.pk: 0})
        transition_order(actor=self.admin, order_id=self.order.pk, to_status="returned", inspections={line.pk: 0})
        self.order.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual((self.order.refunded_amount, self.order.net_total), (Decimal(100000), Decimal(800000)))
        self.assertEqual(self.order.payment_status, "partially_refunded")
        self.assertEqual(item.returned_quantity, 1)
        self.assertEqual([Product.objects.get(pk=p.pk).stock for p in self.products], [8, 8, 8])
        self.client.force_login(self.admin)
        dashboard = self.client.get(reverse("dashboard"))
        self.assertEqual(dashboard.context["revenue"], 800000)
        sold = {row["product_id"]: row["value"] for row in dashboard.context["best_sellers"]}
        self.assertEqual(sold[item.product_id], 1)

    def test_return_limits_and_foreign_line_are_rejected_atomically(self):
        item = self.order.items.first()
        for quantities in [{}, {item.pk: 3}, {item.pk: 0}, {item.pk: True}, {999999: 1}]:
            with self.assertRaises(ValidationError):
                request_order_return(user=self.user, order_id=self.order.pk, reason="Lỗi", evidence=evidence_upload(), quantities=quantities)
        self.assertFalse(hasattr(self.order, "return_request"))

    def test_receipt_restock_requires_admin_entry_and_counts_only_resellable_units(self):
        item = self.order.items.first()
        request_order_return(user=self.user, order_id=self.order.pk, reason="Trả hai", evidence=evidence_upload(), quantities={item.pk: 2})
        transition_order(actor=self.admin, order_id=self.order.pk, to_status="return_approved")
        line = self.order.return_request.items.get()
        self.client.force_login(self.admin)
        path = reverse("manage_order_transition", args=[self.order.pk])
        self.client.post(path, {"to_status": "returned"})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "return_approved")
        self.client.post(path, {"to_status": "returned", f"resellable_{line.pk}": 1})
        item.product.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(item.product.stock, 9)
        self.assertEqual(line.damaged_quantity, 1)
