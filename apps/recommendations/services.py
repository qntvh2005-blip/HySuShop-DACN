import json
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.db.models import Count, F, Q

from apps.catalog.models import Product
from apps.interactions.models import UserInteraction
from apps.orders.models import Order, OrderItem

from .models import RecommendationLog


@dataclass
class RecommendationResult:
    products: list
    algorithm: str
    model_version: str
    fallback_reason: str
    duration_ms: float


@lru_cache(maxsize=2)
def _load_artifact(path, manifest_mtime, bundle_mtime):
    from research.models.artifacts import load_bundle

    return load_bundle(path)


def active_bundle():
    version = settings.RECOMMENDATION_MODEL_VERSION
    root = Path(settings.ARTIFACT_ROOT).resolve()
    pointer = root / "active.json"
    if pointer.exists():
        version = json.loads(pointer.read_text(encoding="utf-8"))["model_version"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", version):
        raise ValueError("Invalid configured model version")
    directory = (root / version).resolve()
    if directory.parent != root:
        raise ValueError("Model outside configured artifact root")
    bundle, manifest = _load_artifact(
        str(directory),
        (directory / "manifest.json").stat().st_mtime_ns,
        (directory / "bundle.joblib").stat().st_mtime_ns,
    )
    if manifest.get("source_kind") != "official_raw" and not getattr(
        settings, "ALLOW_SYNTHETIC_RECOMMENDATIONS", False
    ):
        raise ValueError("Synthetic artifacts cannot be served as a production research model")
    return bundle, manifest


def behavior_history(user, context, event_weights=None):
    weights = event_weights or settings.RECOMMENDATION_EVENT_WEIGHTS
    events = (
        UserInteraction.objects.filter(user=user, event_type__in=weights)
        .exclude(event_type="purchase", order_item__order__status="cancelled")
        .exclude(event_type="purchase", order_item__returned_quantity__gte=F("order_item__quantity"))
        .order_by("-timestamp", "-id")
        .values_list("product__external_item_id", "event_type")[:200]
    )
    history_weights = {}
    for item, event in events:
        history_weights[item] = max(history_weights.get(item, 0), weights[event])
    if context == "cart":
        for item in Product.objects.filter(cartitem__cart__user=user).values_list("external_item_id", flat=True):
            history_weights[item] = max(history_weights.get(item, 0), weights["add_to_cart"])
    return history_weights


def recommend(*, user=None, context="popular", current_item_id=None, phone_model_id=None, limit=10):
    if context not in RecommendationLog.Context.values:
        raise ValueError("Invalid recommendation context")
    if context == "device" and not phone_model_id:
        raise ValueError("Device recommendations require a phone model")
    if not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("Recommendation limit must be 1–50")
    started = time.perf_counter()
    authenticated = user is not None and user.is_authenticated and user.is_active
    queryset = Product.objects.filter(
        is_active=True, stock__gt=0, price__isnull=False, currency="VND"
    )
    if current_item_id:
        queryset = queryset.exclude(external_item_id=current_item_id)
    if phone_model_id:
        queryset = queryset.filter(
            compatibilities__phone_model_id=phone_model_id, compatibilities__verified=True
        )
    if authenticated and context in {"personalized", "cart", "device"}:
        purchased = OrderItem.objects.filter(
            order__user=user,
            order__status__in=["pending", "confirmed", "shipping", *Order.RECEIVED_STATUSES],
            quantity__gt=F("returned_quantity"),
        ).values("product_id")
        queryset = queryset.exclude(pk__in=purchased)
        if context == "cart":
            queryset = queryset.exclude(cartitem__cart__user=user)
    # Rank lightweight IDs first; fetch images only for the final displayed items.
    candidate_ids = list(
        queryset.order_by("external_item_id").values_list("external_item_id", flat=True).distinct()
    )
    history = []
    history_weights = {}
    if authenticated:
        history_weights = behavior_history(user, context)
        history = list(history_weights)
    reason, algorithm, version = "", "operational_popularity", "untrained"
    ranked_ids = []
    score_evidence, logged_scores = {}, None
    try:
        bundle, manifest = active_bundle()
        known_candidates = [item for item in candidate_ids if item in bundle.item_index]
        version = manifest.get("model_version", settings.RECOMMENDATION_MODEL_VERSION)
        if context == "similar" and current_item_id:
            ranking = bundle.similar(current_item_id, known_candidates, limit)
        else:
            selected = (
                manifest.get("serving_algorithm", "hybrid")
                if context in {"personalized", "cart", "device"}
                else "popularity"
            )
            ranking = bundle.rank(
                selected, history, known_candidates, limit, history_weights=history_weights
            )
        algorithm, reason, ranked_ids = ranking.algorithm, ranking.fallback_reason, ranking.item_ids
        logged_scores = dict(zip(ranking.item_ids, ranking.scores))
        if not reason:
            from .explanations import explain_ranking

            score_evidence = explain_ranking(
                bundle, ranking, history, known_candidates, history_weights, current_item_id
            )
    except (OSError, ValueError, KeyError, ImportError, EOFError, TypeError) as error:
        reason = f"artifact_unavailable:{type(error).__name__}"
    if len(ranked_ids) < limit:
        remaining = queryset.exclude(external_item_id__in=ranked_ids)
        remaining = remaining.annotate(
            delivered_sales=Count(
                "orderitem",
                filter=Q(orderitem__order__status__in=Order.RECEIVED_STATUSES),
                distinct=True,
            )
        ).order_by("-delivered_sales", "id")
        fill_ids = list(
            remaining.values_list("external_item_id", flat=True)[: limit - len(ranked_ids)]
        )
        ranked_ids.extend(fill_ids)
        if fill_ids and algorithm != "operational_popularity":
            reason = reason or "operational_fill"
    products = {
        p.external_item_id: p
        for p in queryset.filter(external_item_id__in=ranked_ids)
        .select_related("brand")
        .prefetch_related("images")
        .distinct()
    }
    ranked_ids = [item for item in ranked_ids if item in products]
    elapsed = (time.perf_counter() - started) * 1000
    RecommendationLog.objects.create(
        user=user if authenticated else None,
        context=context,
        algorithm=algorithm,
        model_version=version,
        item_ids=ranked_ids,
        duration_ms=elapsed,
        fallback_reason=reason,
        scores=logged_scores,
        evidence=score_evidence,
    )
    return RecommendationResult(
        [products[item] for item in ranked_ids], algorithm, version, reason, elapsed
    )
