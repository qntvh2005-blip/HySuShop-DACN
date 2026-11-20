from django.db import migrations


def backfill(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    Return = apps.get_model("orders", "OrderReturn")
    Line = apps.get_model("orders", "OrderReturnItem")
    alias = schema_editor.connection.alias
    for order in Order.objects.using(alias).filter(payment_status="refunded"):
        order.refunded_amount = order.total
        order.save(using=alias, update_fields=["refunded_amount"])
    for claim in Return.objects.using(alias).select_related("order"):
        completed = claim.order.status == "returned"
        for item in claim.order.items.using(alias).all():
            Line.objects.using(alias).get_or_create(
                claim=claim, order_item=item,
                defaults={"quantity": item.quantity, "resellable_quantity": item.quantity if completed else None},
            )
            if completed:
                item.returned_quantity = item.quantity
                item.save(using=alias, update_fields=["returned_quantity"])


class Migration(migrations.Migration):
    dependencies = [("orders", "0003_orderreturnitem_and_more")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
