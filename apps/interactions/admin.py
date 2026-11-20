from django.contrib import admin

from apps.common.admin import ReadOnlyAdmin

from .models import Favorite, ProductReview, UserInteraction

admin.site.register(UserInteraction, ReadOnlyAdmin)
admin.site.register(ProductReview, ReadOnlyAdmin)
admin.site.register(Favorite, ReadOnlyAdmin)
