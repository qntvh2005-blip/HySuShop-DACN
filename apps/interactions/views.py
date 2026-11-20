from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.catalog.models import Product
from apps.common.pagination import page_context

from .forms import HistoryFilterForm, ReviewForm
from .models import Favorite, UserInteraction
from .services import submit_review


@login_required
def history(request):
    form = HistoryFilterForm(request.GET)
    events = UserInteraction.objects.filter(user=request.user).select_related(
        "product", "order_item__order"
    )
    if form.is_valid():
        if form.cleaned_data["event"]:
            events = events.filter(event_type=form.cleaned_data["event"])
    else:
        events = events.none()
    return render(
        request,
        "accounts/history.html",
        {
            "form": form,
            **page_context(request, events.order_by("-timestamp", "-pk"), fields=form.fields),
        },
    )


@login_required
def favorites(request):
    products = Product.objects.filter(favorite__user=request.user, is_active=True).prefetch_related(
        "images"
    )
    return render(request, "catalog/favorites.html", {"products": products})


@login_required
@require_POST
@transaction.atomic
def toggle_favorite(request, product_id):
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    favorite, created = Favorite.objects.get_or_create(user=request.user, product=product)
    if created:
        UserInteraction.objects.create(user=request.user, product=product, event_type="favorite")
        messages.success(request, "Đã lưu vào yêu thích.")
    else:
        favorite.delete()
        messages.success(request, "Đã bỏ lưu sản phẩm.")
    return redirect("product_detail", slug=product.slug)


@login_required
@require_POST
def review_product(request, product_id):
    product = get_object_or_404(Product, pk=product_id, is_active=True)
    product_url = reverse("product_detail", kwargs={"slug": product.slug})
    form = ReviewForm(request.POST)
    if form.is_valid():
        try:
            review = submit_review(user=request.user, product=product, **form.cleaned_data)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Đã lưu đánh giá của bạn.")
            return redirect(f"{product_url}#danh-gia-{review.pk}")
    else:
        messages.error(request, "Vui lòng kiểm tra số sao và nội dung đánh giá.")
    return redirect(product_url)
