from django.db.models import Q

from .models import PhoneModel


def available_phone_models(*, include_id=None):
    """Full device names shared by account preferences and storefront filters."""
    available = Q(
        productcompatibility__verified=True,
        productcompatibility__product__is_active=True,
    )
    if include_id is not None:
        available |= Q(pk=include_id)
    return PhoneModel.objects.filter(available).distinct().order_by("manufacturer", "name", "pk")
