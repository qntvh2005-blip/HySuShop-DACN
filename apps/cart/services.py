from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.catalog.models import Product
from apps.interactions.models import UserInteraction

from .models import Cart, CartItem

MAX_QUANTITY = 999


def purchase_issue(product, quantity):
    if not product.is_active or product.price is None or product.currency != "VND":
        return "Sản phẩm hiện chưa mở bán."
    if not 1 <= quantity <= min(product.stock, MAX_QUANTITY):
        return "Số lượng vượt quá tồn kho hoặc giới hạn mỗi đơn."
    return ""


def cart_summary(user):
    lines = list(
        CartItem.objects.filter(cart__user=user)
        .select_related("product")
        .prefetch_related("product__images")
        .order_by("pk")
    )
    for line in lines:
        line.purchase_issue = purchase_issue(line.product, line.quantity)
        line.line_total = None if line.purchase_issue else line.product.price * line.quantity
        line.quantity_limit = min(line.product.stock, MAX_QUANTITY)
        line.can_change_quantity = not purchase_issue(line.product, 1)
        line.quantity_down = min(line.quantity - 1, line.quantity_limit)
    return {
        "lines": lines,
        "subtotal": sum(line.line_total for line in lines if line.line_total is not None),
        "can_checkout": bool(lines) and all(not line.purchase_issue for line in lines),
    }


def require_customer(user):
    if not user or not user.is_authenticated or not user.is_active:
        raise PermissionDenied("Vui lòng đăng nhập.")


@transaction.atomic
def set_quantity(*, user, product_id, quantity, increment=False):
    require_customer(user)
    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity < 0
        or quantity > MAX_QUANTITY
    ):
        raise ValidationError("Số lượng phải là số nguyên từ 0 đến 999.")
    cart, _ = Cart.objects.get_or_create(user=user)
    cart = Cart.objects.select_for_update().get(pk=cart.pk)
    previous = (
        CartItem.objects.filter(cart=cart, product_id=product_id)
        .values_list("quantity", flat=True)
        .first()
        or 0
    )
    if increment:
        if quantity == 0 or previous + quantity > MAX_QUANTITY:
            raise ValidationError("Số lượng thêm vào giỏ không hợp lệ.")
        quantity += previous
    if quantity == 0:
        CartItem.objects.filter(cart=cart, product_id=product_id).delete()
        return cart
    product = Product.objects.get(pk=product_id)
    if issue := purchase_issue(product, quantity):
        raise ValidationError(issue)
    CartItem.objects.update_or_create(cart=cart, product=product, defaults={"quantity": quantity})
    if quantity > previous:
        UserInteraction.objects.create(
            user=user,
            product=product,
            event_type="add_to_cart",
            metadata={"quantity_added": quantity - previous},
        )
    return cart
