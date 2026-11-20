import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.catalog.models import Product
from research.data.fixtures import synthetic_records
from research.data.io import write_json, write_jsonl
from research.data.pipeline import ROOT, prepare


class CatalogImportTests(TestCase):
    def test_exact_mapping_idempotency_and_synthetic_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            metadata, reviews = synthetic_records()
            write_jsonl(root / "meta.jsonl", metadata)
            write_jsonl(root / "reviews.jsonl", reviews)
            config = json.loads(
                (ROOT / "research/configs/experiment.json").read_text(encoding="utf-8")
            )
            write_json(root / "config.json", config)
            prepare(
                root / "meta.jsonl",
                root / "reviews.jsonl",
                root / "dataset",
                root / "config.json",
                source_kind="synthetic_fixture",
            )
            with self.assertRaises(CommandError):
                call_command("import_research_catalog", str(root / "dataset"))
            self.assertEqual(Product.objects.count(), 0)
            call_command("import_research_catalog", str(root / "dataset"), allow_synthetic=True)
            self.assertEqual(Product.objects.count(), 12)
            self.assertEqual(
                set(Product.objects.values_list("external_item_id", flat=True)),
                {f"I{i:02d}" for i in range(12)},
            )
            Product.objects.filter(external_item_id="I00").update(
                price=99000, stock=5, is_active=True
            )
            call_command("import_research_catalog", str(root / "dataset"), allow_synthetic=True)
            product = Product.objects.get(external_item_id="I00")
            self.assertEqual((product.price, product.stock, product.is_active), (99000, 5, True))
            self.assertEqual(Product.objects.count(), 12)
