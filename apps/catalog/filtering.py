import re

from django.db.models import Q

from .forms import PRICE_RANGES
from .models import Brand, Category
from .search import normalize_search


# Common short names for product types whose category labels can use different wording.
PRODUCT_TYPE_ALIASES = {
    "bao da": "bao da",
    "bao deo": "bao deo",
    "bo sac": "bo sac",
    "bo sac khong day": "sac khong day",
    "bo sac o to": "sac tren o to",
    "bo sac tren o to": "sac tren o to",
    "but cam ung": "but cam ung",
    "cap sac": "cap sac",
    "chan may": "chan may",
    "cu sac": "cu sac",
    "cu sac khong day": "sac khong day",
    "cu sac o to": "sac tren o to",
    "dau chuyen": "dau chuyen",
    "dau chuyen otg": "dau chuyen otg",
    "day deo": "day deo",
    "gay chup anh": "gay chup anh",
    "gia do": "gia do",
    "gia do dien thoai tren o to": "gia do dien thoai tren o to",
    "gia do o to": "gia do dien thoai tren o to",
    "kinh": "kinh",
    "mieng dan": "mieng dan",
    "mieng dem": "mieng dem",
    "op lung": "op lung",
    "op lung kiem pin du phong": "op lung kiem pin du phong",
    "op nap gap": "op nap gap",
    "op vien": "op vien",
    "pin du phong": "pin sac du phong",
    "pin sac du phong": "pin sac du phong",
    "sac khong day": "sac khong day",
    "sac o to": "sac tren o to",
    "sac tren o to": "sac tren o to",
    "tai nghe": "tai nghe",
    "tay cam": "tay cam",
    "tram sac": "tram sac",
    "tui chong nuoc": "tui chong nuoc",
    "vi dung the": "vi dung the",
    "vong giu": "vong giu",
}

PRODUCT_TYPE_PATTERN = re.compile(
    r"\b(?:" + "|".join(sorted(PRODUCT_TYPE_ALIASES, key=len, reverse=True)) + r")\b"
)


def search_products(products, query):
    if not query:
        return products

    category_labels = [
        (pk, normalize_search(name)) for pk, name in Category.objects.values_list("pk", "name")
    ]
    brand_labels = [
        (pk, normalize_search(name)) for pk, name in Brand.objects.values_list("pk", "name")
    ]
    normalized_query = normalize_search(query)
    if not normalized_query:
        return products.none()
    if match := PRODUCT_TYPE_PATTERN.search(normalized_query):
        category_phrase = PRODUCT_TYPE_ALIASES[match[0]]
        category_pattern = re.compile(rf"\b{category_phrase}\b")
        category_ids = [pk for pk, name in category_labels if category_pattern.search(name)]
        product_type = Q(categories__pk__in=category_ids)
        # search_document starts with the normalized product name. This keeps
        # products whose name states the type, such as a two-in-one charger.
        for alias, target in PRODUCT_TYPE_ALIASES.items():
            if target == category_phrase:
                product_type |= Q(search_text__startswith=alias + " ")
        products = products.filter(product_type)
        normalized_query = (
            normalized_query[:match.start()].rstrip(" ,:;") + " "
            + normalized_query[match.end():].lstrip(" ,:;")
        )
    for normalized in normalized_query.split():
        products = products.filter(
            Q(search_text__contains=normalized)
            | Q(brand_id__in=[pk for pk, name in brand_labels if normalized in name])
            | Q(categories__pk__in=[pk for pk, name in category_labels if normalized in name])
        )
    return products


def price_condition(price_range):
    lower, upper = PRICE_RANGES[price_range]
    condition = Q()
    if lower is not None:
        condition &= Q(price__gte=lower)
    if upper is not None:
        condition &= Q(price__lt=upper)
    return condition


def filter_conditions(form):
    data = form.cleaned_data
    conditions = []
    if category := data.get("category"):
        conditions.append(Q(categories=category))
    brand = data.get("brand")
    if brand == "other":
        conditions.append(~Q(brand_id__in=form.featured_brand_ids))
    elif brand:
        conditions.append(Q(brand_id__in=form.brand_groups[brand]))
    if phone := data.get("phone"):
        conditions.append(
            Q(is_universal_accessory=True)
            | Q(compatibilities__phone_model=phone, compatibilities__verified=True)
        )
    if price_range := data.get("price_range"):
        conditions.append(price_condition(price_range))
    return conditions
