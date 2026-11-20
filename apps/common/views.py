import json
import re
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Avg, Count, F, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.catalog.models import Product
from apps.interactions.models import UserInteraction
from apps.orders.models import Order, OrderItem
from apps.recommendations.models import RecommendationLog
from research.data.io import file_hash

from .access import admin_permissions


def benchmark_context(request):
    metrics = []
    group = request.GET.get("group", "all")
    if group not in {"all", "sparse", "active"}:
        group = "all"
    k = 5 if request.GET.get("k") == "5" else 10
    benchmark_config, benchmark_statistics = {}, {}
    try:
        version = settings.RECOMMENDATION_MODEL_VERSION
        pointer = Path(settings.ARTIFACT_ROOT) / "active.json"
        if pointer.exists():
            version = json.loads(pointer.read_text(encoding="utf-8"))["model_version"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", version):
            raise ValueError("Invalid model version")
        directory = Path(settings.BASE_DIR) / "reports" / version
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("status") == "complete" and manifest.get("source_kind") == "official_raw":
            if (
                file_hash(directory / "test_metrics.json")
                != manifest["outputs"]["test_metrics.json"]
            ):
                raise ValueError("Benchmark metrics checksum mismatch")
            raw_metrics = json.loads((directory / "test_metrics.json").read_text(encoding="utf-8"))
            names = {
                "popularity": "Popularity",
                "content": "Content-Based",
                "item_cf": "Item-based CF",
                "hybrid": "Hybrid",
            }
            for name in ["popularity", "content", "item_cf", "hybrid"]:
                values = raw_metrics[name][group]
                row = {
                    "algorithm": names[name],
                    "users": values["users"],
                    "mean_ms": values["mean_ms"],
                    "p95_ms": values["p95_ms"],
                    "fallback_users": values["fallback_users"],
                }
                for metric in ["precision", "recall", "ndcg", "hit_rate"]:
                    row[metric] = values[f"{metric}@{k}"]
                row["ndcg_percent"] = 100 * (row["ndcg"] or 0)
                metrics.append(row)
            benchmark_config = manifest["locked_config"]
            processed = (
                Path(
                    manifest.get(
                        "dataset_directory", Path(settings.BASE_DIR) / "data/processed/amazon-v2"
                    )
                )
                / "manifest.json"
            )
            if (
                processed.exists()
                and file_hash(processed) == benchmark_config["dataset_manifest_sha256"]
            ):
                benchmark_statistics = json.loads(processed.read_text(encoding="utf-8"))[
                    "statistics"
                ]
    except (OSError, ValueError, KeyError, TypeError):
        metrics, benchmark_config, benchmark_statistics = [], {}, {}
    return {
        "benchmark": metrics,
        "benchmark_group": group,
        "benchmark_k": k,
        "benchmark_config": benchmark_config,
        "benchmark_statistics": benchmark_statistics,
    }


@admin_permissions(
    "catalog.view_product", "orders.view_order", "recommendations.view_recommendationlog"
)
@require_GET
def dashboard(request):
    # Aggregate each source independently: joining views and order items would
    # multiply both counts. These are website events, never Amazon research rows.
    viewed = list(
        UserInteraction.objects.filter(event_type="view")
        .values("product_id")
        .annotate(value=Count("pk"))
        .order_by("-value", "product_id")[:10]
    )
    completed_sales = Order.objects.filter(
        status__in=Order.RECEIVED_STATUSES,
        payment_status__in=[Order.PaymentStatus.PAID, Order.PaymentStatus.PARTIALLY_REFUNDED],
    )
    sold = list(
        OrderItem.objects.filter(order__in=completed_sales)
        .values("product_id")
        .annotate(value=Sum(F("quantity") - F("returned_quantity")))
        .order_by("-value", "product_id")[:10]
    )
    products = Product.objects.in_bulk({row["product_id"] for row in viewed + sold})
    for row in viewed + sold:
        row["product"] = products[row["product_id"]]
    today = timezone.localdate()
    first_day = today - timedelta(days=6)
    daily = dict(
        completed_sales.filter(created_at__date__range=(first_day, today))
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(total=Sum(F("total") - F("refunded_amount")))
        .values_list("day", "total")
    )
    peak = max(daily.values(), default=0)
    sales = [
        {
            "day": first_day + timedelta(days=offset),
            "total": daily.get(first_day + timedelta(days=offset), 0),
        }
        for offset in range(7)
    ]
    for bar in sales:
        bar["height"] = float(100 * bar["total"] / peak) if peak else 0
    counts = dict(
        Order.objects.values("status").annotate(value=Count("pk")).values_list("status", "value")
    )
    return render(
        request,
        "dashboard.html",
        {
            **benchmark_context(request),
            "area": "dashboard",
            "sales_days": sales,
            "has_sales": bool(daily),
            "weekly_revenue": sum(daily.values()),
            "return_pending_count": counts.get(Order.Status.RETURN_REQUESTED, 0),
            "pending_count": counts.get("pending", 0),
            "shipping_count": counts.get("shipping", 0),
            "delivered_count": counts.get("delivered", 0),
            "low_stock_count": Product.objects.filter(is_active=True, stock__lt=5).count(),
            "product_count": Product.objects.filter(is_active=True).count(),
            "order_count": Order.objects.count(),
            "revenue": completed_sales.aggregate(value=Sum(F("total") - F("refunded_amount")))["value"] or 0,
            "recommendation_ms": RecommendationLog.objects.aggregate(value=Avg("duration_ms"))[
                "value"
            ]
            or 0,
            "recent_orders": Order.objects.select_related("user").order_by("-created_at")[:10],
            "low_stock": Product.objects.filter(is_active=True, stock__lt=5).order_by(
                "stock", "id"
            )[:10],
            "most_viewed": viewed,
            "best_sellers": sold,
        },
    )
