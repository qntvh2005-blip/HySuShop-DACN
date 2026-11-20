from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.localization import (
    CATEGORY_NAMES,
    UNLISTED_SOURCE_ITEMS,
    category_name,
    localized_product,
    source_category,
    storefront_category,
)
from apps.catalog.models import Category, Product, ProductCategory, ProductImage
from apps.catalog.search import search_document

from .import_research_catalog import stable_slug


class Command(BaseCommand):
    help = "Write Vietnamese storefront summaries from retained source metadata."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true", help="Save changes; otherwise preview only."
        )
        parser.add_argument(
            "--repair-filters", action="store_true", help="Correct reviewed storefront listings."
        )

    @transaction.atomic
    def handle(self, *args, **options):
        products = []
        moves = []
        unlisted = []
        queryset = Product.objects.select_related("brand").order_by("pk")
        if options["apply"]:
            queryset = queryset.select_for_update(of=("self",))
        if options["repair_filters"]:
            queryset = queryset.prefetch_related("categories")
        for product in queryset:
            source = product.source_metadata
            if not source.get("title") or not source.get("dataset_manifest_sha256"):
                continue
            if options["repair_filters"]:
                original = source_category(source)
                corrected = storefront_category(source)
                if original != corrected:
                    for category in product.categories.all():
                        if category.slug == stable_slug(original):
                            moves.append((product, category, corrected))
                if product.is_active and product.external_item_id in UNLISTED_SOURCE_ITEMS:
                    unlisted.append(product)
            localized = localized_product(source, product.brand.name if product.brand else "")
            unchanged = all(getattr(product, key) == value for key, value in localized.items())
            for key, value in localized.items():
                setattr(product, key, value)
            search_text = search_document(product)
            if unchanged and product.search_text == search_text:
                continue
            product.search_text = search_text
            products.append(product)
        categories = list(Category.objects.filter(name__in=CATEGORY_NAMES))
        for category in categories:
            category.name = CATEGORY_NAMES[category.name]
        self.stdout.write(f"Products: {len(products)}; categories: {len(categories)}.")
        for product in products[:8]:
            self.stdout.write(f"{product.external_item_id}: {product.name}")
        if options["repair_filters"]:
            self.stdout.write(f"Category corrections: {len(moves)}; unlisted: {len(unlisted)}.")
            for product, category, corrected in moves:
                self.stdout.write(
                    f"{product.external_item_id}: {category.name} → {category_name(corrected)}"
                )
            for product in unlisted:
                self.stdout.write(f"{product.external_item_id}: {product.source_metadata['title']}")
        if options["apply"]:
            Product.objects.bulk_update(
                products, ["name", "description", "features", "search_text"], batch_size=200
            )
            Category.objects.bulk_update(categories, ["name"], batch_size=200)
            for product, category, corrected in moves:
                target, _ = Category.objects.get_or_create(
                    slug=stable_slug(corrected), defaults={"name": category_name(corrected)}
                )
                ProductCategory.objects.get_or_create(product=product, category=target)
                ProductCategory.objects.filter(product=product, category=category).delete()
            Product.objects.filter(pk__in=[product.pk for product in unlisted]).update(
                is_active=False
            )
            # Image alternative text must follow the same language everywhere.
            names = dict(Product.objects.values_list("pk", "name"))
            images = list(ProductImage.objects.filter(product_id__in=[p.pk for p in products]))
            for image in images:
                image.alt = names[image.product_id][:300]
            ProductImage.objects.bulk_update(images, ["alt"], batch_size=200)
            self.stdout.write(
                self.style.SUCCESS(
                    "Vietnamese storefront content saved. Original metadata retained."
                )
            )
        else:
            self.stdout.write("Preview only. Use --apply to save.")
