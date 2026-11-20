from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from apps.catalog.localization import category_name, localized_product, storefront_category
from apps.catalog.models import Brand, Category, ProductImage
from apps.catalog.services import import_research_product
from research.data.dataset import ResearchDataset
from research.data.io import digest
from research.validate import validate


def stable_slug(name):
    return f"{slugify(name)[:140] or 'item'}-{digest(name)[:10]}"


class Command(BaseCommand):
    help = "Import the exact validated research catalog; preserve live price/stock/activation."

    def add_arguments(self, parser):
        parser.add_argument("dataset", type=Path)
        parser.add_argument(
            "--allow-synthetic",
            action="store_true",
            help="Explicitly permit synthetic fixtures for tests only.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            dataset = ResearchDataset(options["dataset"])
            if dataset.manifest["source_kind"] != "official_raw" and not options["allow_synthetic"]:
                raise CommandError(
                    "Synthetic data is blocked; use --allow-synthetic only for test fixtures."
                )
            validate(options["dataset"])
            created_count = 0
            updated_count = 0
            for item in dataset.rows("catalog"):
                category = storefront_category(item)
                slug = stable_slug(category)
                Category.objects.update_or_create(
                    slug=slug, defaults={"name": category_name(category)[:150]}
                )
                brand_name = item["attributes"].get("Brand") or item["store"]
                localized = localized_product(item, brand_name)
                product, created = import_research_product(
                    external_item_id=item["item_id"],
                    category_slugs=[slug],
                    **localized,
                    source_metadata={**item, "dataset_manifest_sha256": digest(dataset.manifest)},
                )
                if brand_name:
                    brand, _ = Brand.objects.get_or_create(
                        slug=stable_slug(brand_name), defaults={"name": brand_name[:150]}
                    )
                    product.brand = brand
                    product.save(update_fields=["brand", "updated_at"])
                for position, url in enumerate(item["image_urls"]):
                    ProductImage.objects.get_or_create(
                        product=product,
                        position=position,
                        defaults={"image_url": url, "alt": product.name[:300]},
                    )
                created_count += int(created)
                updated_count += int(not created)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Catalog imported: {created_count} created, {updated_count} updated. Price/stock/activation preserved."
                )
            )
        except (ValueError, OSError, KeyError) as error:
            raise CommandError(str(error)) from error
