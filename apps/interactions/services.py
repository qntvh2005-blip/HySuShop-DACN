from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F

from apps.cart.services import require_customer
from apps.orders.models import Order, OrderItem

from .models import ProductReview


def reviewable_order_items(user, product):
    return OrderItem.objects.filter(
        order__user=user, order__status__in=[Order.Status.DELIVERED, Order.Status.RETURNED],
        product=product, quantity__gt=F("returned_quantity"),
    )


@transaction.atomic
def submit_review(*, user, product, rating, comment=""):
    require_customer(user)
    item = (
        reviewable_order_items(user, product)
        .order_by("-order__created_at", "-pk")
        .first()
    )
    if item is None:
        raise ValidationError("Bạn cần mua và nhận sản phẩm trước khi đánh giá.")
    order = Order.objects.select_for_update().get(pk=item.order_id)
    item.refresh_from_db()
    if order.status not in {Order.Status.DELIVERED, Order.Status.RETURNED} or item.returned_quantity >= item.quantity:
        raise ValidationError("Đơn hàng không còn ở trạng thái đã giao.")
    review = ProductReview.objects.filter(user=user, product=product).first() or ProductReview(
        user=user, product=product
    )
    review.order_item = item
    review.order_item.order = order
    review.rating, review.comment = rating, comment
    review.full_clean()
    review.save()
    return review
