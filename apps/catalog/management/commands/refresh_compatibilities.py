from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.compatibility import devices_from_source, sync_product_compatibilities
from apps.catalog.models import Product
from apps.catalog.reviewed_compatibility import REVIEWED_DEVICE_NAMES, UNIVERSAL_ITEMS


class Command(BaseCommand):
    help = "Preview or refresh phone compatibility from retained metadata, preserving manual links."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument(
            "--reviewed-only", action="store_true",
            help="Refresh reviewed model lists and apply reviewed shared-accessory flags.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        counts = Counter()
        created = removed = 0
        shared = 0
        products = Product.objects.order_by("pk")
        if options["reviewed_only"]:
            products = products.filter(external_item_id__in=UNIVERSAL_ITEMS | REVIEWED_DEVICE_NAMES.keys())
        if options["apply"]:
            products = products.select_for_update()
        for product in products:
            if not product.source_metadata.get("dataset_manifest_sha256"):
                continue
            if options["reviewed_only"] and product.external_item_id in UNIVERSAL_ITEMS:
                if not product.is_universal_accessory:
                    shared += 1
                    if options["apply"]:
                        product.is_universal_accessory = True
                        product.save(update_fields=["is_universal_accessory", "updated_at"])
                continue
            devices = devices_from_source(product.source_metadata)
            counts.update(device.manufacturer for device in devices)
            if options["apply"]:
                added, deleted = sync_product_compatibilities(product, devices)
                created += added
                removed += deleted
        self.stdout.write(f"Explicit device links: {dict(counts)}")
        self.stdout.write(
            f"Created: {created}; obsolete generated links removed: {removed}. Manual links preserved."
        )
        if options["reviewed_only"]:
            self.stdout.write(f"New shared accessory flags: {shared}.")
        if not options["apply"]:
            self.stdout.write("Preview only; use --apply to save.")
