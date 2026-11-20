"""Sensitivity of live top-10 lists to operational weights, without accuracy claims."""

import argparse
import os
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits


def run(output):
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    django.setup()
    from django.contrib.auth import get_user_model
    from django.db.models import F
    from apps.catalog.models import Product
    from apps.orders.models import Order, OrderItem
    from apps.recommendations.services import active_bundle, behavior_history
    from research.data.io import write_json

    if Path(output).exists():
        raise ValueError("Use a fresh result file")
    bundle, manifest = active_bundle()
    configurations = {
        "uniform": {"view": 1, "favorite": 1, "add_to_cart": 1, "purchase": 1},
        "moderate": {"view": 1, "favorite": 2, "add_to_cart": 3, "purchase": 4},
        "current": {"view": 1, "favorite": 3, "add_to_cart": 4, "purchase": 5},
    }
    cases = []
    for user in get_user_model().objects.filter(is_active=True, is_staff=False).order_by("pk"):
        profiles = {name: behavior_history(user, "personalized", weights) for name, weights in configurations.items()}
        if not any(item in bundle.item_index for item in profiles["current"]):
            continue
        owned = OrderItem.objects.filter(order__user=user, order__status__in=["pending", "confirmed", "shipping", *Order.RECEIVED_STATUSES], quantity__gt=F("returned_quantity")).values("product_id")
        candidates = list(Product.objects.filter(is_active=True, stock__gt=0, price__isnull=False, currency="VND").exclude(pk__in=owned).order_by("external_item_id").values_list("external_item_id", flat=True))
        candidates = [item for item in candidates if item in bundle.item_index]
        lists = {name: bundle.rank("hybrid", list(profile), candidates, 10, history_weights=profile).item_ids for name, profile in profiles.items()}
        current = set(lists["current"])
        cases.append({
            "case": len(cases) + 1, "known_history_items": len(bundle.history_indices(list(profiles["current"]))),
            "distinct_history_weights": len(set(profiles["current"].values())),
            "history_weights": profiles, "candidate_ids": candidates,
            "lists": lists, "jaccard": {name: len(current & set(items)) / len(current | set(items)) if current or items else 1.0 for name, items in lists.items()},
        })
    write_json(output, {
        "model": manifest["model_version"], "configurations": configurations,
        "scope": "Replay of current per-account histories and available candidates; no future outcome labels, no test-based selection, no claim of optimal weights",
        "case_count": len(cases), "mean_jaccard_to_current": {name: float(np.mean([case["jaccard"][name] for case in cases])) if cases else None for name in configurations},
        "cases": cases,
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        run(args.output)
