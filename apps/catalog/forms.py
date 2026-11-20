from django import forms
from django.db.models.functions import Lower

from .device_choices import available_phone_models
from .models import Brand, Category, Product

PRICE_RANGES = {
    "under_100": (None, 100000),
    "100_300": (100000, 300000),
    "from_300": (300000, None),
}

# Curated storefront choices only. Other brands and their products remain in
# the database and frozen research catalog, accessible under "Thương hiệu khác".
FEATURED_BRANDS = {
    "apple": "Apple",
    "samsung": "Samsung",
    "anker": "Anker",
    "belkin": "Belkin",
    "ugreen": "UGREEN",
    "spigen": "Spigen",
    "otterbox": "OtterBox",
    "esr": "ESR",
    "jetech": "JETech",
    "supcase": "SUPCASE",
    "caseology": "Caseology",
    "ringke": "Ringke",
    "speck": "Speck",
    "urban armor gear": "UAG (Urban Armor Gear)",
    "amazon basics": "Amazon Basics",
}


class CatalogFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        max_length=200,
        label="Tìm kiếm",
        widget=forms.TextInput(attrs={"placeholder": "Tên sản phẩm, thương hiệu, mã mẫu…"}),
    )
    category = forms.ModelChoiceField(
        Category.objects.filter(products__is_active=True).distinct().order_by("name"),
        required=False,
        label="Danh mục",
        empty_label="Tất cả danh mục",
    )
    brand = forms.ChoiceField(required=False, label="Thương hiệu")
    phone = forms.ModelChoiceField(
        available_phone_models(),
        required=False,
        label="Thiết bị tương thích",
        empty_label="Tất cả thiết bị",
        widget=forms.Select(attrs={"class": "form-select device-select"}),
    )
    price_range = forms.ChoiceField(
        required=False,
        label="Giá",
        choices=[
            ("", "Tất cả mức giá"),
            ("under_100", "Dưới 100.000 đồng"),
            ("100_300", "Từ 100.000 đến dưới 300.000 đồng"),
            ("from_300", "Từ 300.000 đồng trở lên"),
        ],
    )
    sort = forms.ChoiceField(
        required=False,
        choices=[
            ("newest", "Mới nhất"),
            ("price_asc", "Giá tăng dần"),
            ("price_desc", "Giá giảm dần"),
        ],
        label="Sắp xếp",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        brands = (
            Brand.objects.filter(product__is_active=True)
            .annotate(normalized_name=Lower("name"))
            .filter(normalized_name__in=FEATURED_BRANDS)
            .distinct()
            .order_by("pk")
        )
        groups = {}
        for brand in brands:
            groups.setdefault(brand.normalized_name, []).append(brand.pk)
        self.brand_groups = {}
        choices = [("", "Tất cả thương hiệu")]
        for key, label in FEATURED_BRANDS.items():
            if key in groups:
                value = str(groups[key][0])
                self.brand_groups[value] = groups[key]
                choices.append((value, label))
        self.featured_brand_ids = [pk for ids in self.brand_groups.values() for pk in ids]
        if (
            Product.objects.filter(is_active=True)
            .exclude(brand_id__in=self.featured_brand_ids)
            .exists()
        ):
            choices.append(("other", "Thương hiệu khác"))
        self.fields["brand"].choices = choices
