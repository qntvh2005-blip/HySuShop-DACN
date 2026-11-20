"""Create explicitly simulated selling fields for the verified research catalog only."""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.compatibility import sync_product_compatibilities
from apps.catalog.localization import UNLISTED_SOURCE_ITEMS
from apps.catalog.models import Product
from apps.catalog.reviewed_compatibility import UNIVERSAL_ITEMS
from research.data.dataset import ResearchDataset
from research.data.io import digest


class Command(BaseCommand):
    help = "Activate unpriced research items with deterministic simulated VND prices/stock; never overwrite existing selling data."

    def add_arguments(self, parser):
        parser.add_argument("dataset")

    @transaction.atomic
    def handle(self, *args, **options):
        dataset = ResearchDataset(options["dataset"])
        if dataset.manifest["source_kind"] != "official_raw":
            raise CommandError(
                "Only the verified real research catalog may be activated by this command."
            )
        tiers = [49000, 79000, 99000, 149000, 199000, 249000, 349000, 499000]
        changed, mappings = 0, 0
        products = (
            Product.objects.filter(external_item_id__in=dataset.item_ids)
            .exclude(external_item_id__in=UNLISTED_SOURCE_ITEMS)
            .order_by("id")
        )
        for product in products:
            if (
                product.price is None
                and not product.price_source
                and not product.is_active
                and product.stock == 0
            ):
                product.price = Decimal(
                    tiers[int(digest(product.external_item_id)[:8], 16) % len(tiers)]
                )
                product.price_source = "demo_generated_v1"
                product.stock = 20
                product.is_active = True
                if product.external_item_id in UNIVERSAL_ITEMS:
                    product.is_universal_accessory = True
                product.save(
                    update_fields=[
                        "price", "price_source", "stock", "is_active", "is_universal_accessory", "updated_at",
                    ]
                )
                changed += 1
            added, _ = sync_product_compatibilities(product)
            mappings += added
        self.stdout.write(
            f"Demo catalog: {changed} newly activated items; {mappings} explicit title-derived mappings. All generated prices and stock are simulated."
        )
