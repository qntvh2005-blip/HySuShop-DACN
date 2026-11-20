import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.common.models import TimestampedModel


class Order(TimestampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Chờ xác nhận"
        CONFIRMED = "confirmed", "Đã xác nhận"
        SHIPPING = "shipping", "Đang giao"
        DELIVERED = "delivered", "Đã giao"
        CANCELLED = "cancelled", "Đã hủy"
        RETURN_REQUESTED = "return_requested", "Chờ duyệt trả hàng"
        RETURN_APPROVED = "return_approved", "Đã duyệt trả hàng"
        RETURNED = "returned", "Đã nhận hàng trả"

    class PaymentMethod(models.TextChoices):
        COD = "cod", "COD"
        SIMULATED = "simulated", "Mô phỏng"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Chưa thanh toán"
        PAID = "paid", "Đã thanh toán"
        REFUNDED = "refunded", "Đã hoàn"
        PARTIALLY_REFUNDED = "partially_refunded", "Đã hoàn một phần"

    RECEIVED_STATUSES = (Status.DELIVERED, Status.RETURN_REQUESTED, Status.RETURN_APPROVED, Status.RETURNED)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders"
    )
    number = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    checkout_key = models.UUIDField(unique=True, editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    payment_method = models.CharField(
        max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.COD
    )
    payment_status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )
    recipient_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=25)
    address = models.TextField()
    subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    shipping_fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default="VND")
    refunded_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    @property
    def net_total(self):
        return self.total - self.refunded_amount

    class Meta:
        permissions = [("process_order", "Can process order status")]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["status", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(subtotal__gte=0) & Q(shipping_fee__gte=0) & Q(total__gte=0),
                name="order_amounts_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(total=F("subtotal") + F("shipping_fee")),
                name="order_total_matches_amounts",
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=[
                        "pending",
                        "confirmed",
                        "shipping",
                        "delivered",
                        "cancelled",
                        "return_requested",
                        "return_approved",
                        "returned",
                    ]
                ),
                name="order_valid_status",
            ),
            models.CheckConstraint(
                condition=Q(payment_method__in=["cod", "simulated"]),
                name="order_valid_payment_method",
            ),
            models.CheckConstraint(
                condition=Q(payment_status__in=["unpaid", "paid", "refunded", "partially_refunded"]),
                name="order_valid_payment_status",
            ),
            models.CheckConstraint(
                condition=Q(refunded_amount__gte=0) & Q(refunded_amount__lte=F("total")),
                name="order_refund_within_total",
            ),
        ]

    def __str__(self):
        return str(self.number)


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT)
    external_item_id_snapshot = models.CharField(max_length=32)
    name_snapshot = models.CharField(max_length=600)
    image_snapshot = models.CharField(max_length=2000, blank=True)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    quantity = models.PositiveIntegerField()
    returned_quantity = models.PositiveIntegerField(default=0)
    line_total = models.DecimalField(max_digits=14, decimal_places=2)

    @property
    def display_image(self):
        if self.image_snapshot:
            return self.image_snapshot
        return next((image.display_url for image in self.product.display_images), "")

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(returned_quantity__lte=F("quantity")), name="returned_quantity_within_order",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0) & Q(unit_price__gte=0), name="order_item_valid_amounts"
            ),
            models.CheckConstraint(
                condition=Q(line_total=F("unit_price") * F("quantity")),
                name="order_item_total_matches",
            ),
        ]


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, choices=Order.Status.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["order", "created_at"])]


class OrderReturn(models.Model):
    class Decision(models.TextChoices):
        PENDING = "pending", "Chờ quản trị viên duyệt"
        APPROVED = "approved", "Đã chấp thuận"
        REJECTED = "rejected", "Đã từ chối"

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="return_request")
    reason = models.CharField(max_length=1000)
    evidence = models.BinaryField()
    decision = models.CharField(max_length=10, choices=Decision.choices, default=Decision.PENDING)
    decision_note = models.CharField(max_length=1000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class OrderReturnItem(models.Model):
    claim = models.ForeignKey(OrderReturn, on_delete=models.CASCADE, related_name="items")
    order_item = models.ForeignKey(OrderItem, on_delete=models.PROTECT, related_name="return_lines")
    quantity = models.PositiveIntegerField()
    resellable_quantity = models.PositiveIntegerField(null=True, blank=True)

    @property
    def refund_amount(self):
        return self.order_item.unit_price * self.quantity

    @property
    def damaged_quantity(self):
        if self.resellable_quantity is None:
            return None
        return self.quantity - self.resellable_quantity

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["claim", "order_item"], name="unique_return_order_item"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="return_quantity_positive"),
            models.CheckConstraint(
                condition=Q(resellable_quantity__isnull=True) | Q(resellable_quantity__lte=F("quantity")),
                name="resellable_within_return",
            ),
        ]
