import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.cart.models import Cart, CartItem
from apps.catalog.models import Category, Product
from apps.catalog.services import import_research_product
from apps.interactions.models import Favorite, ProductReview, UserInteraction
from apps.orders.models import Order, OrderItem


class FoundationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="customer", password="test-pass")
        cls.other = get_user_model().objects.create_user(username="other")
        Category.objects.create(name="Ốp lưng", slug="cases")
        cls.product, _ = import_research_product(
            external_item_id="B000TEST01", name="Ốp điện thoại", category_slugs=["cases"]
        )

    def assert_rejected(self, operation):
        with self.assertRaises(IntegrityError), transaction.atomic():
            operation()

    def test_product_identity_unique_and_stock_nonnegative(self):
        self.assert_rejected(
            lambda: Product.objects.create(
                external_item_id=self.product.external_item_id, name="Duplicate", slug="duplicate"
            )
        )
        self.assert_rejected(lambda: Product.objects.filter(pk=self.product.pk).update(stock=-1))
        self.assert_rejected(
            lambda: Product.objects.filter(pk=self.product.pk).update(is_active=True)
        )

    def test_import_idempotent_preserves_operational_fields(self):
        Product.objects.filter(pk=self.product.pk).update(price=99000, stock=7, is_active=True)
        imported, created = import_research_product(
            external_item_id="B000TEST01", name="Tên mới", category_slugs=["cases"]
        )
        self.assertFalse(created)
        self.assertEqual(imported.pk, self.product.pk)
        self.assertEqual(
            (imported.price, imported.stock, imported.is_active), (Decimal("99000"), 7, True)
        )
        self.assertEqual(imported.categories.count(), 1)

    def test_import_without_category_is_atomic(self):
        with self.assertRaises(ValidationError):
            import_research_product(external_item_id="INVALID", name="Invalid", category_slugs=[])
        self.assertFalse(Product.objects.filter(external_item_id="INVALID").exists())

    def test_cart_and_favorite_constraints(self):
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=self.product, quantity=1)
        self.assert_rejected(
            lambda: CartItem.objects.create(cart=cart, product=self.product, quantity=2)
        )
        self.assert_rejected(lambda: CartItem.objects.filter(cart=cart).update(quantity=0))
        Favorite.objects.create(user=self.user, product=self.product)
        self.assert_rejected(lambda: Favorite.objects.create(user=self.user, product=self.product))

    def make_order_item(self):
        order = Order.objects.create(
            user=self.user,
            checkout_key=uuid.uuid4(),
            recipient_name="Test",
            phone="0900000000",
            address="Test",
            subtotal=100,
            total=100,
        )
        item = OrderItem.objects.create(
            order=order,
            product=self.product,
            external_item_id_snapshot=self.product.external_item_id,
            name_snapshot=self.product.name,
            unit_price=100,
            quantity=1,
            line_total=100,
        )
        return order, item

    def test_order_amounts_and_checkout_key(self):
        order, item = self.make_order_item()
        self.assert_rejected(lambda: Order.objects.filter(pk=order.pk).update(total=101))
        self.assert_rejected(lambda: OrderItem.objects.filter(pk=item.pk).update(line_total=99))
        self.assert_rejected(lambda: Order.objects.filter(pk=order.pk).update(status="unknown"))
        Product.objects.filter(pk=self.product.pk).update(price=500)
        item.refresh_from_db()
        self.assertEqual(item.unit_price, 100)

    def test_review_ownership_delivery_and_rating(self):
        order, item = self.make_order_item()
        review = ProductReview(user=self.user, product=self.product, order_item=item, rating=5)
        with self.assertRaises(ValidationError):
            review.full_clean()
        order.status = Order.Status.DELIVERED
        order.save()
        item.order = order
        review.full_clean()
        review.save()
        self.assert_rejected(lambda: ProductReview.objects.filter(pk=review.pk).update(rating=6))
        review.user = self.other
        with self.assertRaises(ValidationError):
            review.full_clean()

    def test_event_identity_and_purchase_deduplication(self):
        self.assert_rejected(
            lambda: UserInteraction.objects.create(product=self.product, event_type="view")
        )
        _, item = self.make_order_item()
        UserInteraction.objects.create(
            user=self.user, product=self.product, event_type="purchase", order_item=item
        )
        self.assert_rejected(
            lambda: UserInteraction.objects.create(
                user=self.user, product=self.product, event_type="purchase", order_item=item
            )
        )

    def test_roles_idempotent_without_raw_auth_permissions(self):
        call_command("setup_roles", verbosity=0)
        before = Group.objects.get(name="Admin").permissions.count()
        call_command("setup_roles", verbosity=0)
        self.assertEqual(Group.objects.get(name="Admin").permissions.count(), before)
        self.user.groups.add(Group.objects.get(name="Admin"))
        self.assertTrue(self.user.has_perm("catalog.change_product"))
        self.assertTrue(self.user.has_perm("orders.process_order"))
        self.assertFalse(self.user.has_perm("accounts.change_user"))
        self.assertFalse(self.user.has_perm("auth.change_group"))
        self.assertFalse(self.user.has_perm("orders.change_order"))
        self.assertFalse(self.user.is_staff)

    def test_home_and_admin_access(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get("/admin/"), "/quan-ly/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/quan-ly/").status_code, 403)

    def test_staff_audit_tables_are_read_only(self):
        call_command("setup_roles", verbosity=0)
        self.user.groups.add(Group.objects.get(name="Admin"))
        self.user.is_staff = True
        self.user.save()
        order, _ = self.make_order_item()
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/quan-ly/don-hang/").status_code, 200)
        response = self.client.post(f"/quan-ly/don-hang/{order.pk}/", {"status": "delivered"})
        self.assertEqual(response.status_code, 405)
        order.refresh_from_db()
        self.assertEqual(order.status, "pending")
