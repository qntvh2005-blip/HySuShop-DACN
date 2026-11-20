from django.contrib.admin.models import ADDITION, LogEntry
from django.db.models import Q
from django.db.models.functions import Lower

from apps.catalog.device_choices import available_phone_models
from apps.catalog.forms import FEATURED_BRANDS
from apps.catalog.models import Brand, Category, PhoneModel


def _added_in_management(model):
    ids = LogEntry.objects.filter(
        action_flag=ADDITION,
        content_type__app_label="catalog",
        content_type__model=model._meta.model_name,
    ).values_list("object_id", flat=True)
    return [int(value) for value in ids if value and value.isdecimal()]


def brand_choices(current=None):
    featured = (
        Brand.objects.filter(product__is_active=True)
        .annotate(normalized=Lower("name"))
        .filter(normalized__in=FEATURED_BRANDS)
        .order_by("pk")
        .distinct()
        .values_list("pk", "normalized")
    )
    groups = {}
    for pk, name in featured:
        groups.setdefault(name, pk)
    return Brand.objects.filter(
        Q(pk__in=[*groups.values(), *_added_in_management(Brand), current])
        | Q(product__isnull=True)
    ).distinct().order_by("name", "pk")


def category_choices(current=()):
    return Category.objects.filter(
        Q(products__is_active=True)
        | Q(products__isnull=True)
        | Q(pk__in=[*_added_in_management(Category), *current])
    ).distinct().order_by("name", "pk")


def phone_choices(current=()):
    return PhoneModel.objects.filter(
        Q(pk__in=available_phone_models().values("pk"))
        | Q(productcompatibility__isnull=True)
        | Q(pk__in=[*_added_in_management(PhoneModel), *current])
    ).distinct().order_by("manufacturer", "name", "pk")
