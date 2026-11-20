import uuid
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from PIL import Image

from apps.cart.models import CartItem
from apps.cart.services import set_quantity
from apps.catalog.models import Product, ProductImage
from apps.interactions.models import UserInteraction
from apps.orders.models import Order
from apps.orders.services import checkout, request_order_return, transition_order


def place(user, key=None):
    return checkout(
        user=user,
        checkout_key=key or uuid.uuid4(),
        recipient_name="Người nhận",
        phone="0900000000",
        address="TP.HCM",
    )


def evidence_upload():
    data = BytesIO()
    Image.new("RGB", (8, 8), "red").save(data, format="PNG")
    return SimpleUploadedFile("anh.png", data.getvalue(), content_type="image/png")


class CheckoutTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="buyer")
        self.other = get_user_model().objects.create_user(username="outsider")
        self.admin = get_user_model().objects.create_superuser(username="admin", password="test")
        self.product = Product.objects.create(
            external_item_id="P", name="Ốp lưng", slug="case", price=100000, stock=3, is_active=True
        )
        set_quantity(user=self.user, product_id=self.product.pk, quantity=2)

    def test_atomic_checkout_snapshot_and_retry(self):
        image = ProductImage.objects.create(
            product=self.product, image_url="https://example.com/checkout.jpg"
        )
        key = uuid.uuid4()
        order = place(self.user, key)
        image.image_url = "https://example.com/new.jpg"
        image.save()
        self.assertEqual(order.items.get().display_image, "https://example.com/checkout.jpg")
        self.assertEqual(place(self.user, key).pk, order.pk)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1)
        self.assertEqual(order.total, 200000)
        self.assertEqual(UserInteraction.objects.filter(event_type="purchase").count(), 1)
        self.assertEqual(CartItem.objects.count(), 0)
        self.product.price = 123
        self.product.save()
        self.assertEqual(order.items.get().unit_price, 100000)
        with self.assertRaises(PermissionDenied):
            place(self.other, key)

    def test_stock_failure_rolls_back_whole_order(self):
        Product.objects.filter(pk=self.product.pk).update(stock=1)
        with self.assertRaises(ValidationError):
            place(self.user)
        self.assertFalse(Order.objects.exists())
        self.assertEqual(CartItem.objects.get().quantity, 2)
        self.assertFalse(UserInteraction.objects.filter(event_type="purchase").exists())

    def test_phone_validation_rejects_punctuation_without_creating_order(self):
        from apps.accounts.forms import ProfileForm
        from apps.orders.forms import CheckoutForm

        data = {"checkout_key": uuid.uuid4(), "recipient_name": "Khách hàng", "address": "TP.HCM", "payment_method": "cod"}
        for phone in ["........", "()-- --()", "1234567-", "1234567890123456"]:
            with self.subTest(phone=phone):
                self.assertFalse(CheckoutForm({**data, "phone": phone}).is_valid())
                self.assertFalse(ProfileForm({"phone": phone}).is_valid())
                with self.assertRaises(ValidationError):
                    checkout(user=self.user, phone=phone, **data)
        self.assertTrue(ProfileForm({"phone": ""}).is_valid())
        self.assertTrue(CheckoutForm({**data, "phone": "0900000000"}).is_valid())
        for phone in [
            "1045622622", "090123456", "0601234567", "09123456789", "0912 345 678",
            "+84 (90) 123-4567", "028 3812 3456", "09123a5678", " 0912345678",
        ]:
            with self.subTest(phone=phone):
                self.assertFalse(CheckoutForm({**data, "phone": phone}).is_valid())
                with self.assertRaises(ValidationError):
                    checkout(user=self.user, phone=phone, **data)
        self.assertFalse(Order.objects.exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)

    def test_cancel_restocks_once_and_requires_owner(self):
        order = place(self.user)
        with self.assertRaises(PermissionDenied):
            transition_order(actor=self.other, order_id=order.pk, to_status="cancelled")
        transition_order(actor=self.user, order_id=order.pk, to_status="cancelled")
        transition_order(actor=self.admin, order_id=order.pk, to_status="cancelled")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)
        self.assertEqual(order.status_history.count(), 2)

    def test_delivery_and_return_path(self):
        order = place(self.user)
        with self.assertRaises(ValidationError):
            transition_order(actor=self.admin, order_id=order.pk, to_status="delivered")
        for status in ["confirmed", "shipping", "delivered"]:
            transition_order(actor=self.admin, order_id=order.pk, to_status=status)
        with self.assertRaises(ValidationError):
            transition_order(actor=self.admin, order_id=order.pk, to_status="return_requested")
        request_order_return(
            user=self.user, order_id=order.pk, reason="Sản phẩm bị hỏng", evidence=evidence_upload()
        )
        with self.assertRaises(ValidationError):
            transition_order(actor=self.admin, order_id=order.pk, to_status="returned")
        for status in ["return_approved", "returned", "returned"]:
            inspections = {line.pk: line.quantity for line in order.return_request.items.all()}
            transition_order(actor=self.admin, order_id=order.pk, to_status=status, inspections=inspections)
        self.product.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.product.stock, 3)
        self.assertEqual(order.payment_status, "refunded")

    def test_cart_validation_and_removal(self):
        with self.assertRaises(ValidationError):
            set_quantity(user=self.user, product_id=self.product.pk, quantity=4)
        with self.assertRaises(ValidationError):
            set_quantity(user=self.user, product_id=self.product.pk, quantity=True)
        set_quantity(user=self.user, product_id=self.product.pk, quantity=0)
        self.assertFalse(CartItem.objects.exists())

    def test_add_to_cart_increments_existing_quantity(self):
        set_quantity(user=self.user, product_id=self.product.pk, quantity=1, increment=True)
        self.assertEqual(CartItem.objects.get().quantity, 3)
        with self.assertRaises(ValidationError):
            set_quantity(user=self.user, product_id=self.product.pk, quantity=1, increment=True)


class ConcurrentCheckoutTests(TransactionTestCase):
    def test_two_buyers_cannot_oversell_last_item(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL row locks")
        product = Product.objects.create(
            external_item_id="LAST",
            name="Last item",
            slug="last",
            price=100,
            stock=1,
            is_active=True,
        )
        users = [get_user_model().objects.create_user(username=f"buyer{i}") for i in range(2)]
        for user in users:
            set_quantity(user=user, product_id=product.pk, quantity=1)
        barrier = Barrier(2)

        def buy(user_id):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=user_id)
                barrier.wait(timeout=10)
                try:
                    place(user)
                    return "created"
                except ValidationError:
                    return "out_of_stock"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(buy, [u.pk for u in users]))
        self.assertCountEqual(results, ["created", "out_of_stock"])
        product.refresh_from_db()
        self.assertEqual(product.stock, 0)
        self.assertEqual(Order.objects.count(), 1)
