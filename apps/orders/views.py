import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from apps.accounts.models import Profile
from apps.cart.services import cart_summary
from apps.common.validators import normalize_stored_phone

from .forms import CheckoutForm, OrderReturnForm
from .models import Order, OrderReturn
from .services import checkout, request_order_return, transition_order


@login_required
def checkout_view(request):
    stored = Profile.objects.filter(user=request.user).first()
    initial = {
        "checkout_key": uuid.uuid4(),
        "recipient_name": request.user.get_full_name(),
        "phone": normalize_stored_phone(stored.phone) if stored else "",
        "address": stored.default_address if stored else "",
        "payment_method": "cod",
    }
    form = CheckoutForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            order = checkout(user=request.user, **form.cleaned_data)
            messages.success(request, "Đặt hàng thành công.")
            return redirect("order_detail", number=order.number)
        except ValidationError as error:
            form.add_error(None, error)
    return render(
        request,
        "orders/checkout.html",
        {
            "form": form,
            **cart_summary(request.user),
        },
    )


@login_required
def order_list(request):
    orders = (
        Order.objects.filter(user=request.user)
        .prefetch_related("items__product__images")
        .order_by("-created_at")
    )
    return render(request, "orders/list.html", {"orders": orders})


@login_required
@require_http_methods(["GET", "POST"])
def order_detail(request, number):
    order = get_object_or_404(
        Order.objects.prefetch_related(
            "items__product__images",
            "status_history",
            Prefetch("return_request", queryset=OrderReturn.objects.defer("evidence")),
        ),
        number=number,
        user=request.user,
    )
    claim = getattr(order, "return_request", None)
    can_request = order.status == Order.Status.DELIVERED and claim is None
    form = OrderReturnForm(order=order)
    if request.method == "POST":
        if not can_request:
            messages.error(request, "Đơn hàng này không thể gửi thêm yêu cầu trả hàng.")
            return redirect("order_detail", number=number)
        form = OrderReturnForm(request.POST, request.FILES, order=order)
        if form.is_valid():
            try:
                request_order_return(user=request.user, order_id=order.pk, **form.cleaned_data)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, "Đã gửi yêu cầu trả hàng. Bạn có thể theo dõi kết quả tại đây.")
                return redirect("order_detail", number=number)
    return render(
        request,
        "orders/detail.html",
        {"order": order, "claim": claim, "return_form": form if can_request else None},
    )


@login_required
@require_safe
@never_cache
def return_evidence(request, number):
    records = OrderReturn.objects.filter(order__number=number)
    if not (request.user.is_staff and request.user.has_perm("orders.view_order")):
        records = records.filter(order__user=request.user)
    claim = get_object_or_404(records.only("evidence"))
    return HttpResponse(
        bytes(claim.evidence),
        content_type="image/jpeg",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@login_required
@require_POST
def cancel_order(request, number):
    order = get_object_or_404(Order, number=number, user=request.user)
    try:
        transition_order(
            actor=request.user,
            order_id=order.pk,
            to_status="cancelled",
            reason="Khách hàng yêu cầu",
            as_customer=True,
        )
        messages.success(request, "Đã hủy đơn hàng.")
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    return redirect("order_detail", number=number)
