from django.conf import settings
from django.db import models
from django.db.models import Q


class RecommendationLog(models.Model):
    class Context(models.TextChoices):
        POPULAR = "popular", "Sản phẩm được quan tâm"
        SIMILAR = "similar", "Sản phẩm tương tự"
        PERSONALIZED = "personalized", "Gợi ý dành cho bạn"
        CART = "cart", "Giỏ hàng"
        DEVICE = "device", "Phụ kiện cho điện thoại của bạn"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    context = models.CharField(
        max_length=30, choices=Context.choices
    )
    algorithm = models.CharField(max_length=50)
    model_version = models.CharField(max_length=100)
    item_ids = models.JSONField(default=list)
    scores = models.JSONField(null=True, blank=True)
    evidence = models.JSONField(default=dict, blank=True)
    duration_ms = models.FloatField()
    fallback_reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["context", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(duration_ms__gte=0), name="recommendation_duration_nonnegative"
            )
        ]
