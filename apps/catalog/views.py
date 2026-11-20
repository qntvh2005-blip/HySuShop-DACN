from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render

from apps.cart.services import MAX_QUANTITY
from apps.common.pagination import page_context
from apps.interactions.forms import ReviewForm
from apps.interactions.models import Favorite, UserInteraction
from apps.interactions.services import reviewable_order_items
from apps.recommendations.services import recommend

from .compatibility import compatibility_guidance
from .filtering import filter_conditions, search_products
from .forms import CatalogFilterForm
from .models import Category, Product

CATEGORY_ICONS = (
    ("sạc", "bolt"),
    ("tai nghe", "headphones"),
    ("màn hình", "shield"),
    ("ốp", "phone"),
)


def home(request):
    recommendation = recommend(
        user=request.user,
        context="personalized" if request.user.is_authenticated else "popular",
        limit=8,
    )
    personalized = (
        request.user.is_authenticated
        and recommendation.algorithm in {"content", "item_cf", "hybrid"}
        and recommendation.fallback_reason not in {"no_known_history", "zero_scores"}
    )
    preferred_device = None
    device_recommendation = None
    if request.user.is_authenticated:
        preference = (
            request.user.preferred_devices.select_related("phone_model").order_by("pk").first()
        )
        if preference:
            preferred_device = preference.phone_model
            device_recommendation = recommend(
                user=request.user,
                context="device",
                phone_model_id=preferred_device.pk,
                limit=4,
            )
    categories = list(
        Category.objects.filter(products__is_active=True)
        .annotate(item_count=Count("products", distinct=True))
        .order_by("-item_count", "name")[:6]
    )
    for category in categories:
        category.icon = next(
            (icon for term, icon in CATEGORY_ICONS if term in category.name.lower()), "grid"
        )
    available = (
        Product.objects.filter(is_active=True, stock__gt=0)
        .select_related("brand")
        .prefetch_related("images")
    )
    hero_products = recommendation.products[:3]
    brands = [
        (value, label)
        for value, label in CatalogFilterForm().fields["brand"].choices
        if value and value != "other"
    ][:6]
    return render(
        request,
        "home.html",
        {
            "recommendation": recommendation,
            "has_personalized_recommendation": personalized,
            "preferred_device": preferred_device,
            "device_recommendation": device_recommendation,
            "categories": categories,
            "hero_products": hero_products,
            "home_brands": brands,
            "charging_category": Category.objects.filter(
                name__icontains="sạc", products__is_active=True
            )
            .order_by("name")
            .first(),
            "new_products": available.exclude(
                pk__in=[product.pk for product in recommendation.products]
            ).order_by("-created_at", "pk")[:4],
        },
    )


def product_list(request):
    form = CatalogFilterForm(request.GET)
    queryset = Product.objects.none()
    if form.is_valid():
        sort_field = {"price_asc": "price", "price_desc": "-price"}.get(
            form.cleaned_data.get("sort"), "-created_at"
        )
        queryset = (
            search_products(Product.objects.filter(is_active=True), form.cleaned_data["q"])
            .filter(*filter_conditions(form))
            .select_related("brand")
            .prefetch_related("images", "categories")
            .order_by(sort_field, "id")
        )
    return render(
        request,
        "catalog/list.html",
        {
            "form": form,
            **page_context(request, queryset.distinct(), size=9, fields=form.fields),
        },
    )


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.prefetch_related(
            "images", "categories", "compatibilities__phone_model", "reviews__user"
        ),
        slug=slug,
        is_active=True,
    )
    if not request.session.session_key:
        request.session.create()
    UserInteraction.objects.create(
        user=request.user if request.user.is_authenticated else None,
        session_key=request.session.session_key,
        product=product,
        event_type="view",
    )
    favorite = (
        request.user.is_authenticated
        and Favorite.objects.filter(user=request.user, product=product).exists()
    )
    recommendation = recommend(
        user=request.user, context="similar", current_item_id=product.external_item_id, limit=4
    )
    current_review = None
    if request.user.is_authenticated:
        current_review = next(
            (review for review in product.reviews.all() if review.user_id == request.user.pk), None
        )
    review_form = ReviewForm(
        initial={"rating": current_review.rating, "comment": current_review.comment}
        if current_review else None
    )
    return render(
        request,
        "catalog/detail.html",
        {
            "product": product,
            "is_favorite": favorite,
            "recommendation": recommendation,
            "compatibilities": [c for c in product.compatibilities.all() if c.verified],
            "compatibility_guidance": compatibility_guidance(product.source_metadata),
            "review_form": review_form,
            "current_review": current_review,
            "can_review": request.user.is_authenticated
            and reviewable_order_items(request.user, product).exists(),
            "purchase_limit": min(product.stock, MAX_QUANTITY),
        },
    )
