from django.contrib import admin

from apps.common.admin import ReadOnlyAdmin

from .models import RecommendationLog

admin.site.register(RecommendationLog, ReadOnlyAdmin)
