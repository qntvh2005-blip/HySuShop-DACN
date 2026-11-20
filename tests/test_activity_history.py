import uuid
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.cart.services import set_quantity
from apps.catalog.models import Product
from apps.interactions.models import UserInteraction
from apps.orders.models import Order
from apps.orders.services import checkout


class ActivityHistoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="buyer")
        self.other = User.objects.create_user(username="other")
        self.product = Product.objects.create(
            external_item_id="ACTIVE",
            name="Current item",
            slug="active",
            is_active=True,
            price=100,
            stock=20,
        )
        self.archived = Product.objects.create(
            external_item_id="ARCHIVED",
            name="Archived item",
            slug="archived",
            is_active=False,
            price=100,
        )

    def test_history_is_private_and_does_not_create_another_view(self):
        path = reverse("interaction_history")
        self.assertEqual(self.client.get(path).status_code, 302)
        UserInteraction.objects.create(user=self.user, product=self.archived, event_type="view")
        UserInteraction.objects.create(user=self.other, product=self.product, event_type="favorite")
        UserInteraction.objects.create(
            session_key="anonymous", product=self.product, event_type="view"
        )
        self.client.force_login(self.user)
        response = self.client.get(path, {"user_id": self.other.pk})
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertContains(response, "Ngừng bán")
        self.assertNotContains(response, reverse("product_detail", args=[self.archived.slug]))
        self.assertNotContains(response, "Current item")
        self.assertEqual(UserInteraction.objects.count(), 3)

    def test_history_filter_and_pagination_preserve_event(self):
        UserInteraction.objects.bulk_create(
            [
                UserInteraction(user=self.user, product=self.product, event_type="favorite")
                for _ in range(25)
            ]
        )
        UserInteraction.objects.create(user=self.user, product=self.product, event_type="view")
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("interaction_history"), {"event": "favorite", "page": "2"}
        )
        self.assertEqual(len(response.context["page_obj"]), 1)
        self.assertEqual(response.context["page_obj"].paginator.count, 25)
        self.assertContains(response, "event=favorite&amp;page=1")
        invalid = self.client.get(reverse("interaction_history"), {"event": "unknown"})
        self.assertTrue(invalid.context["form"].errors)
        self.assertEqual(invalid.context["page_obj"].paginator.count, 0)

    def test_purchase_history_uses_snapshot_and_current_cancel_status(self):
        set_quantity(user=self.user, product_id=self.product.pk, quantity=1)
        order = checkout(
            user=self.user,
            checkout_key=uuid.uuid4(),
            recipient_name="Buyer",
            phone="0900000000",
            address="Test",
        )
        self.product.name = "Renamed item"
        self.product.save()
        Order.objects.filter(pk=order.pk).update(status="cancelled")
        self.client.force_login(self.user)
        response = self.client.get(reverse("interaction_history"), {"event": "purchase"})
        self.assertContains(response, "Current item")
        self.assertContains(response, "Đã hủy")
        self.assertContains(response, reverse("order_detail", args=[order.number]))

    def test_dashboard_counts_views_and_delivered_units_without_join_multiplication(self):
        call_command("setup_roles", stdout=StringIO())
        staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        staff.groups.add(Group.objects.get(name="Admin"))
        for status, quantity in [
            ("delivered", 3),
            ("delivered", 2),
            ("cancelled", 4),
            ("return_requested", 1),
            ("returned", 1),
            ("pending", 1),
        ]:
            set_quantity(user=self.user, product_id=self.product.pk, quantity=quantity)
            order = checkout(
                user=self.user,
                checkout_key=uuid.uuid4(),
                recipient_name="Buyer",
                phone="0900000000",
                address="Test",
            )
            Order.objects.filter(pk=order.pk).update(
                status=status,
                payment_status="paid" if status in {"delivered", "return_requested"} else "unpaid",
            )
        UserInteraction.objects.bulk_create(
            [
                UserInteraction(session_key="anonymous", product=self.product, event_type="view")
                for _ in range(7)
            ]
        )
        UserInteraction.objects.create(user=self.other, product=self.archived, event_type="view")
        self.client.force_login(staff)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(row["product_id"], row["value"]) for row in response.context["most_viewed"]],
            [(self.product.pk, 7), (self.archived.pk, 1)],
        )
        self.assertEqual(
            [(row["product_id"], row["value"]) for row in response.context["best_sellers"]],
            [(self.product.pk, 6)],
        )
        self.assertEqual(response.context["revenue"], 600)
        self.assertEqual(response.context["weekly_revenue"], 600)
        self.assertContains(response, 'class="sales-amount">600', html=False)
