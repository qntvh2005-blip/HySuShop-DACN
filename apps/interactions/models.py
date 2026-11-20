import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.common.models import TimestampedModel


class Favorite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "product"], name="unique_favorite")]


class ProductReview(TimestampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="reviews")
    order_item = models.ForeignKey("orders.OrderItem", on_delete=models.PROTECT)
    rating = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "product"], name="unique_product_review"),
            models.CheckConstraint(
                condition=Q(rating__gte=1) & Q(rating__lte=5), name="review_rating_range"
            ),
        ]

    def clean(self):
        super().clean()
        if self.order_item_id:
            item = self.order_item
            if (
                item.order.user_id != self.user_id
                or item.product_id != self.product_id
                or item.order.status not in {"delivered", "returned"}
                or item.returned_quantity >= item.quantity
            ):
                raise ValidationError("Chỉ đánh giá sản phẩm thuộc đơn đã giao của chính bạn.")


class UserInteraction(models.Model):
    class Event(models.TextChoices):
        VIEW = "view", "Xem"
        FAVORITE = "favorite", "Yêu thích"
        ADD_TO_CART = "add_to_cart", "Thêm giỏ"
        PURCHASE = "purchase", "Đặt mua"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    session_key = models.CharField(max_length=64, null=True, blank=True)
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT)
    event_type = models.CharField(max_length=20, choices=Event.choices)
    event_key = models.UUIDField(default=uuid.uuid4, unique=True)
    order_item = models.ForeignKey(
        "orders.OrderItem", null=True, blank=True, on_delete=models.PROTECT
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "timestamp"]),
            models.Index(fields=["product", "event_type", "timestamp"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(user__isnull=False)
                | (Q(session_key__isnull=False) & ~Q(session_key="")),
                name="interaction_has_identity",
            ),
            models.CheckConstraint(
                condition=Q(event_type__in=["view", "favorite", "add_to_cart", "purchase"]),
                name="interaction_valid_type",
            ),
            models.CheckConstraint(
                condition=~Q(event_type="purchase") | Q(order_item__isnull=False),
                name="purchase_requires_order_item",
            ),
            models.UniqueConstraint(
                fields=["order_item"],
                condition=Q(event_type="purchase"),
                name="unique_purchase_per_order_item",
            ),
        ]
