from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Category, Product, ProductCategory


@transaction.atomic
def import_research_product(
    *, external_item_id, name, category_slugs, description="", features=None, source_metadata=None
):
    """Update source fields only. Never overwrite operational price, stock or activation."""
    if not external_item_id or not external_item_id.strip() or not name.strip():
        raise ValidationError("Mã nguồn và tên sản phẩm không được để trống.")
    slugs = set(category_slugs)
    categories = list(Category.objects.filter(slug__in=slugs))
    if not slugs or len(categories) != len(slugs):
        raise ValidationError("Phải cung cấp ít nhất một danh mục hợp lệ.")
    product, created = Product.objects.get_or_create(
        external_item_id=external_item_id,
        defaults={"name": name, "slug": f"item-{external_item_id.lower()}"},
    )
    product = Product.objects.select_for_update().get(pk=product.pk)
    product.name = name
    product.description = description
    product.features = features if features is not None else []
    product.source_metadata = source_metadata if source_metadata is not None else {}
    product.full_clean(exclude=["categories"])
    product.save(update_fields=["name", "description", "features", "source_metadata", "updated_at"])
    ProductCategory.objects.filter(product=product).exclude(category__in=categories).delete()
    for category in categories:
        ProductCategory.objects.get_or_create(product=product, category=category)
    return product, created
