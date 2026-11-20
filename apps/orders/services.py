import uuid
from decimal import Decimal
from io import BytesIO

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from PIL import Image, ImageOps

from apps.cart.models import Cart
from apps.cart.services import purchase_issue, require_customer
from apps.catalog.models import Product
from apps.common.validators import validate_phone_number
from apps.interactions.models import UserInteraction

from .models import Order, OrderItem, OrderReturn, OrderReturnItem, OrderStatusHistory


def _existing_order(checkout_key, user):
    order = Order.objects.filter(checkout_key=checkout_key).first()
    if order and order.user_id != user.pk:
        raise PermissionDenied("Mã đặt hàng không thuộc tài khoản của bạn.")
    return order


@transaction.atomic
def checkout(*, user, checkout_key, recipient_name, phone, address, payment_method="cod"):
    require_customer(user)
    try:
        checkout_key = uuid.UUID(str(checkout_key))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValidationError("Mã đặt hàng không hợp lệ.") from error
    existing = _existing_order(checkout_key, user)
    if existing:
        return existing
    if any(not isinstance(value, str) for value in [recipient_name, phone, address]):
        raise ValidationError("Thông tin nhận hàng không hợp lệ.")
    values = {
        "recipient_name": recipient_name.strip(),
        "phone": phone,
        "address": address.strip(),
    }
    if (
        not all(values.values())
        or len(values["recipient_name"]) > 150
        or len(values["address"]) > 2000
    ):
        raise ValidationError("Vui lòng kiểm tra thông tin nhận hàng.")
    if payment_method not in Order.PaymentMethod.values:
        raise ValidationError("Phương thức thanh toán không hợp lệ.")
    validate_phone_number(values["phone"])
    # All cart writers acquire this lock, so retries and cart changes serialize per customer.
    try:
        cart = Cart.objects.select_for_update().get(user=user)
    except Cart.DoesNotExist as error:
        raise ValidationError("Giỏ hàng trống.") from error
    existing = _existing_order(checkout_key, user)
    if existing:
        return existing
    lines = list(cart.items.order_by("product_id"))
    if not lines:
        raise ValidationError("Giỏ hàng trống.")
    # Stable lock order prevents crossed product locks across concurrent checkouts.
    products = {
        p.pk: p
        for p in Product.objects.select_for_update()
        .filter(pk__in=[line.product_id for line in lines])
        .prefetch_related("images")
        .order_by("pk")
    }
    subtotal = Decimal("0.00")
    for line in lines:
        product = products[line.product_id]
        if issue := purchase_issue(product, line.quantity):
            raise ValidationError(f"{product.name}: {issue}")
        subtotal += product.price * line.quantity
    if subtotal > Decimal("999999999999.99"):
        raise ValidationError("Giá trị đơn vượt giới hạn hệ thống.")
    try:
        with transaction.atomic():
            order = Order.objects.create(
                user=user,
                checkout_key=checkout_key,
                **values,
                payment_method=payment_method,
                payment_status="paid" if payment_method == "simulated" else "unpaid",
                subtotal=subtotal,
                shipping_fee=0,
                total=subtotal,
                currency="VND",
            )
    except IntegrityError:
        existing = _existing_order(checkout_key, user)
        if existing:
            return existing
        raise
    for line in lines:
        product = products[line.product_id]
        product.stock -= line.quantity
        product.save(update_fields=["stock", "updated_at"])
        item = OrderItem.objects.create(
            order=order,
            product=product,
            external_item_id_snapshot=product.external_item_id,
            name_snapshot=product.name,
            image_snapshot=next((image.display_url for image in product.display_images), ""),
            unit_price=product.price,
            quantity=line.quantity,
            line_total=product.price * line.quantity,
        )
        UserInteraction.objects.create(
            user=user,
            product=product,
            event_type="purchase",
            order_item=item,
            event_key=uuid.uuid5(order.number, str(item.pk)),
        )
    OrderStatusHistory.objects.create(
        order=order, from_status="", to_status=order.status, actor=user
    )
    cart.items.all().delete()
    return order


REJECT_RETURN = "reject_return"

TRANSITIONS = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"shipping", "cancelled"},
    "shipping": {"delivered"},
    "delivered": set(),
    "return_requested": {"return_approved", REJECT_RETURN},
    "return_approved": {"returned"},
    "cancelled": set(),
    "returned": set(),
}

MAX_EVIDENCE_BYTES = 5 * 1024 * 1024


def _evidence_jpeg(upload):
    if not upload or not 0 < upload.size <= MAX_EVIDENCE_BYTES:
        raise ValidationError("Vui lòng chọn ảnh bằng chứng tối đa 5 MB.")
    try:
        with Image.open(upload, formats=("JPEG", "PNG", "WEBP")) as image:
            if image.width * image.height > 20_000_000:
                raise ValidationError("Ảnh bằng chứng quá lớn. Hãy chọn ảnh nhỏ hơn.")
            image = ImageOps.exif_transpose(image)
            image.thumbnail((1600, 1600))
            output = BytesIO()
            image.convert("RGB").save(output, format="JPEG", quality=88)
            return output.getvalue()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValidationError("Ảnh bằng chứng phải là ảnh JPG, PNG hoặc WebP hợp lệ.") from error


@transaction.atomic
def request_order_return(*, user, order_id, reason, evidence, quantities=None):
    require_customer(user)
    order = Order.objects.select_for_update().get(pk=order_id)
    if order.user_id != user.pk:
        raise PermissionDenied("Đơn hàng không thuộc tài khoản của bạn.")
    if order.status != Order.Status.DELIVERED or hasattr(order, "return_request"):
        raise ValidationError("Đơn hàng này không thể gửi thêm yêu cầu trả hàng.")
    reason = reason.strip() if isinstance(reason, str) else ""
    if not reason or len(reason) > 1000:
        raise ValidationError("Vui lòng nhập lý do trả hàng tối đa 1.000 ký tự.")
    items = {item.pk: item for item in order.items.all()}
    # Existing callers requesting the entire order remain supported.
    if quantities is None:
        quantities = {pk: item.quantity for pk, item in items.items()}
    if not isinstance(quantities, dict) or not quantities:
        raise ValidationError("Chọn ít nhất một sản phẩm cần trả.")
    for pk, quantity in quantities.items():
        if (
            pk not in items or isinstance(quantity, bool) or not isinstance(quantity, int)
            or not 1 <= quantity <= items[pk].quantity - items[pk].returned_quantity
        ):
            raise ValidationError("Số lượng trả phải nằm trong số lượng đã mua của chính đơn này.")
    claim = OrderReturn.objects.create(order=order, reason=reason, evidence=_evidence_jpeg(evidence))
    OrderReturnItem.objects.bulk_create([
        OrderReturnItem(claim=claim, order_item=items[pk], quantity=quantity)
        for pk, quantity in quantities.items()
    ])
    order.status = Order.Status.RETURN_REQUESTED
    order.save(update_fields=["status", "updated_at"])
    OrderStatusHistory.objects.create(
        order=order,
        from_status=Order.Status.DELIVERED,
        to_status=order.status,
        actor=user,
    )
    return order


@transaction.atomic
def transition_order(*, actor, order_id, to_status, reason="", as_customer=False, inspections=None):
    require_customer(actor)
    order = Order.objects.select_for_update().get(pk=order_id)
    administrator = not as_customer and actor.is_staff and actor.has_perm("orders.process_order")
    if not administrator and (
        order.user_id != actor.pk
        or order.status != Order.Status.PENDING
        or to_status != Order.Status.CANCELLED
    ):
        raise PermissionDenied("Bạn không có quyền thay đổi trạng thái đơn này.")
    if to_status == order.status and administrator:
        return order
    if to_status not in TRANSITIONS.get(order.status, set()):
        raise ValidationError("Không thể chuyển sang trạng thái yêu cầu.")
    previous = order.status
    if previous == Order.Status.RETURN_REQUESTED:
        claim = getattr(order, "return_request", None)
        if claim is None or claim.decision != OrderReturn.Decision.PENDING:
            raise ValidationError("Đơn hàng chưa có hồ sơ trả hàng hợp lệ để duyệt.")
        reason = reason.strip() if isinstance(reason, str) else ""
        if len(reason) > 1000:
            raise ValidationError("Ghi chú xử lý tối đa 1.000 ký tự.")
        if to_status == REJECT_RETURN and not reason:
            raise ValidationError("Vui lòng nhập lý do từ chối để khách hàng xem.")
        claim.decision = (
            OrderReturn.Decision.APPROVED
            if to_status == Order.Status.RETURN_APPROVED
            else OrderReturn.Decision.REJECTED
        )
        claim.decision_note = reason
        claim.save(update_fields=["decision", "decision_note"])
        if to_status == REJECT_RETURN:
            to_status = Order.Status.DELIVERED
    if to_status == "cancelled":
        quantities = {}
        for product_id, quantity in order.items.values_list("product_id", "quantity"):
            quantities[product_id] = quantities.get(product_id, 0) + quantity
        for product in Product.objects.select_for_update().filter(pk__in=quantities).order_by("pk"):
            product.stock += quantities[product.pk]
            product.save(update_fields=["stock", "updated_at"])
        if order.payment_status == "paid":
            order.payment_status = "refunded"
            order.refunded_amount = order.total
    if to_status == "returned":
        claim = getattr(order, "return_request", None)
        if claim is None or claim.decision != OrderReturn.Decision.APPROVED:
            raise ValidationError("Cần có yêu cầu trả hàng đã được chấp thuận.")
        lines = list(claim.items.select_related("order_item").order_by("order_item_id"))
        if not lines or not isinstance(inspections, dict) or set(inspections) != {line.pk for line in lines}:
            raise ValidationError("Nhập số lượng bán lại được cho từng sản phẩm nhận trả; nhập 0 nếu tất cả bị hỏng.")
        quantities = {}
        for line in lines:
            resellable = inspections[line.pk]
            if isinstance(resellable, bool) or not isinstance(resellable, int) or not 0 <= resellable <= line.quantity:
                raise ValidationError("Số lượng bán lại được phải từ 0 đến số lượng nhận trả.")
            if line.order_item.order_id != order.pk or line.order_item.returned_quantity + line.quantity > line.order_item.quantity:
                raise ValidationError("Dòng trả hàng không khớp đơn mua.")
            line.resellable_quantity = resellable
            line.save(update_fields=["resellable_quantity"])
            line.order_item.returned_quantity += line.quantity
            line.order_item.save(update_fields=["returned_quantity"])
            product_id = line.order_item.product_id
            quantities[product_id] = quantities.get(product_id, 0) + resellable
        for product in Product.objects.select_for_update().filter(pk__in=quantities).order_by("pk"):
            product.stock += quantities[product.pk]
            product.save(update_fields=["stock", "updated_at"])
        refund = sum(line.refund_amount for line in lines)
        if order.payment_status != Order.PaymentStatus.PAID:
            raise ValidationError("Chỉ hoàn tiền cho đơn đã thanh toán.")
        order.refunded_amount = refund
        order.payment_status = (
            Order.PaymentStatus.REFUNDED if refund == order.total else Order.PaymentStatus.PARTIALLY_REFUNDED
        )
    if previous == Order.Status.SHIPPING and to_status == Order.Status.DELIVERED:
        order.payment_status = "paid"
    order.status = to_status
    order.save(update_fields=["status", "payment_status", "refunded_amount", "updated_at"])
    OrderStatusHistory.objects.create(
        order=order, from_status=previous, to_status=to_status, actor=actor, reason=reason
    )
    return order
