from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.catalog.models import Product
from apps.recommendations.services import recommend

from .services import cart_summary, set_quantity


@login_required
def cart_detail(request):
    return render(
        request,
        "cart/detail.html",
        {
            **cart_summary(request.user),
            "recommendation": recommend(user=request.user, context="cart", limit=4),
        },
    )


@login_required
@require_POST
def update_cart(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    try:
        mode = request.POST.get("mode")
        if mode not in {None, "", "add", "remove"}:
            raise ValidationError("Thao tác giỏ hàng không hợp lệ.")
        quantity = 0 if mode == "remove" else int(request.POST.get("quantity", ""))
        set_quantity(
            user=request.user,
            product_id=product.pk,
            quantity=quantity,
            increment=mode == "add",
        )
        messages.success(request, "Đã cập nhật giỏ hàng.")
    except (ValueError, ValidationError) as error:
        messages.error(
            request,
            " ".join(error.messages)
            if isinstance(error, ValidationError)
            else "Số lượng không hợp lệ.",
        )
    return redirect("cart")
