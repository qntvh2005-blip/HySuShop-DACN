from django import forms
from django.contrib import admin

from .models import (
    Brand,
    Category,
    PhoneModel,
    Product,
    ProductCategory,
    ProductCompatibility,
    ProductImage,
)


class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = "__all__"

    def clean_features(self):
        features = self.cleaned_data.get("features") or []
        if not isinstance(features, list) or any(
            not isinstance(feature, str) for feature in features
        ):
            raise forms.ValidationError("Đặc điểm sản phẩm phải là danh sách các chuỗi văn bản.")
        return features

    def clean(self):
        data = super().clean()
        if data.get("price") is not None and data.get("currency") != "VND":
            self.add_error("currency", "Giá bán mô phỏng trên website sử dụng VND.")
        return data


class CategoryInline(admin.TabularInline):
    model = ProductCategory
    extra = 1
    min_num = 1
    validate_min = True

    def get_formset(self, request, obj=None, **kwargs):
        kwargs["validate_min"] = True
        return super().get_formset(request, obj, **kwargs)


class ImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


class CompatibilityInline(admin.TabularInline):
    model = ProductCompatibility
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = ["name", "external_item_id", "price", "stock", "is_active"]
    search_fields = ["name", "external_item_id"]
    list_filter = ["is_active", "brand", "categories"]
    inlines = [CategoryInline, ImageInline, CompatibilityInline]

    def get_readonly_fields(self, request, obj=None):
        return ["source_metadata", "price_source", *(["external_item_id"] if obj else [])]

    def has_delete_permission(self, request, obj=None):
        if obj and obj.source_metadata.get("dataset_manifest_sha256"):
            return False
        return super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        # Keep research mappings intact. Administrators can stop selling an item using
        # is_active; individual non-research items still support deletion.
        actions.pop("delete_selected", None)
        return actions

    def save_model(self, request, obj, form, change):
        if "price" in form.changed_data:
            obj.price_source = "manual_demo" if obj.price is not None else ""
        super().save_model(request, obj, form, change)


admin.site.register([Brand, Category, PhoneModel])
