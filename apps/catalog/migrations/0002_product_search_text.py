import unicodedata
from django.db import migrations, models


def backfill(apps, schema_editor):
    Product = apps.get_model("catalog", "Product")
    batch = []
    for product in Product.objects.using(schema_editor.connection.alias).iterator(chunk_size=200):
        source = product.source_metadata or {}
        features = [str(value).split(":", 1)[-1] for value in product.features]
        description = product.description.split("Vui lòng đối chiếu", 1)[0]
        parts = [product.name, description, product.external_item_id,
                 source.get("title", ""), *features,
                 *source.get("attributes", {}).values()]
        value = " ".join(str(part) for part in parts).casefold().replace("đ", "d")
        product.search_text = " ".join("".join(c for c in unicodedata.normalize("NFKD", value)
                                               if not unicodedata.combining(c)).split())
        batch.append(product)
        if len(batch) == 200:
            Product.objects.using(schema_editor.connection.alias).bulk_update(batch, ["search_text"])
            batch.clear()
    if batch:
        Product.objects.using(schema_editor.connection.alias).bulk_update(batch, ["search_text"])


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]
    operations = [
        migrations.AddField(model_name="product", name="search_text",
                            field=models.TextField(blank=True, default="", editable=False)),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
