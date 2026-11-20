import json
import re
from pathlib import Path

from django import forms
from django.conf import settings

from apps.catalog.images import prepare_product_image
from apps.catalog.models import Brand, Category, PhoneModel, Product
from apps.catalog.localization import UNLISTED_SOURCE_ITEMS

from .catalog_choices import brand_choices, category_choices, phone_choices


class ProductEditor(forms.ModelForm):
    categories = forms.ModelMultipleChoiceField(
        Category.objects.none(),
        label="Danh mục",
        widget=forms.CheckboxSelectMultiple,
    )
    feature_lines = forms.CharField(
        label="Đặc điểm sản phẩm",
        required=False,
        help_text="Mỗi dòng là một đặc điểm hoặc thông số đã xác nhận.",
        widget=forms.Textarea(attrs={"rows": 5}),
        max_length=20000,
    )
    revision = forms.CharField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = Product
        fields = [
            "name", "external_item_id", "brand", "price", "stock", "is_active",
            "description", "is_universal_accessory",
        ]
        labels = {
            "name": "Tên sản phẩm",
            "external_item_id": "Mã sản phẩm",
            "brand": "Thương hiệu",
            "price": "Giá bán (đ)",
            "stock": "Số lượng tồn",
            "is_active": "Đang mở bán",
            "description": "Mô tả",
            "is_universal_accessory": "Phụ kiện dùng chung cho nhiều thiết bị",
        }
        help_texts = {
            "is_universal_accessory": "Xuất hiện khi lọc bất kỳ mẫu máy nào. Ghi điều kiện sử dụng trong mô tả.",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "stock": forms.NumberInput(attrs={"max": 2147483647}),
            "price": forms.NumberInput(attrs={
                "min": 0,
                "max": "999999999999.99",
                "data-stepper-steps": 100000,  # 1,000 đ at the field's 0.01 precision.
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        category_ids = []
        self.fields["brand"].queryset = brand_choices(self.instance.brand_id)
        self.initial["feature_lines"] = "\n".join(self.instance.features or [])
        if self.instance.pk:
            self.fields["external_item_id"].disabled = True
            category_ids = list(self.instance.categories.values_list("pk", flat=True))
            self.initial["categories"] = category_ids
            self.initial["revision"] = self.instance.updated_at.isoformat()
            self.fields["revision"].required = True
        self.fields["categories"].queryset = category_choices(category_ids)

    def clean_revision(self):
        revision = self.cleaned_data.get("revision", "")
        if self.instance.pk and revision != self.instance.updated_at.isoformat():
            raise forms.ValidationError(
                "Sản phẩm vừa thay đổi. Tải lại trang để xem giá và tồn kho mới nhất trước khi lưu."
            )
        return revision

    def clean(self):
        data = super().clean()
        if data.get("is_active") and data.get("price") is None:
            self.add_error("price", "Cần có giá bán trước khi mở bán sản phẩm.")
        if data.get("is_active") and self.instance.external_item_id in UNLISTED_SOURCE_ITEMS:
            self.add_error("is_active", "Hồ sơ nguồn chưa xác minh được, cần giữ ngừng bán.")
        # Archived research rows must not silently re-enter the selected sample.
        if (
            self.instance.pk
            and not self.instance.is_active
            and data.get("is_active")
            and self.instance.source_metadata.get("dataset_manifest_sha256")
        ):
            try:
                version = settings.RECOMMENDATION_MODEL_VERSION
                pointer = Path(settings.ARTIFACT_ROOT) / "active.json"
                if pointer.exists():
                    version = json.loads(pointer.read_text(encoding="utf-8"))["model_version"]
                if not re.fullmatch(r"[A-Za-z0-9_-]+", version):
                    raise ValueError("Invalid version")
                from research.data.dataset import ResearchDataset

                dataset = ResearchDataset(Path(settings.DATA_ROOT) / "processed" / version)
                if self.instance.external_item_id not in dataset.item_ids:
                    self.add_error(
                        "is_active",
                        "Sản phẩm nằm ngoài tập nghiên cứu đang dùng. Giữ ngừng bán để không lẫn dữ liệu.",
                    )
            except (OSError, ValueError, KeyError, TypeError):
                self.add_error(
                    "is_active",
                    "Chưa đối chiếu được tập nghiên cứu. Chưa thể mở bán lại sản phẩm này.",
                )
        return data


class ImageForm(forms.Form):
    file = forms.FileField(
        label="Chọn ảnh từ máy",
        widget=forms.ClearableFileInput(attrs={"accept": ".jpg,.jpeg,.png,.webp"}),
        help_text="Chọn ảnh JPG, PNG hoặc WebP, tối đa 5 MB.",
    )
    alt = forms.CharField(label="Mô tả ảnh", required=False, max_length=300)

    def clean_file(self):
        return prepare_product_image(self.cleaned_data["file"])


class CompatibilityForm(forms.Form):
    phone_model = forms.ModelChoiceField(
        PhoneModel.objects.none(), label="Thiết bị"
    )
    verified = forms.BooleanField(label="Xác nhận tương thích", required=False, initial=True)

    def __init__(self, *args, product=None, **kwargs):
        super().__init__(*args, **kwargs)
        current = product.compatibilities.values_list("phone_model_id", flat=True) if product else []
        self.fields["phone_model"].queryset = phone_choices(current)


class CategoryEditor(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name"]
        labels = {"name": "Tên danh mục"}


class BrandEditor(forms.ModelForm):
    class Meta:
        model = Brand
        fields = ["name"]
        labels = {"name": "Tên thương hiệu"}


class PhoneEditor(forms.ModelForm):
    class Meta:
        model = PhoneModel
        fields = ["manufacturer", "name"]
        labels = {"manufacturer": "Hãng thiết bị", "name": "Tên thiết bị"}


class OrderTransitionForm(forms.Form):
    to_status = forms.ChoiceField(label="Chuyển trạng thái", choices=[])
    reason = forms.CharField(
        label="Ghi chú xử lý",
        max_length=1000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, order, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.orders.models import Order
        from apps.orders.services import REJECT_RETURN, TRANSITIONS

        choices = [
            (value, label)
            for value, label in Order.Status.choices
            if value in TRANSITIONS.get(order.status, set())
        ]
        if order.status == Order.Status.RETURN_REQUESTED:
            choices = [
                ("", "Chọn quyết định"),
                (Order.Status.RETURN_APPROVED, "Chấp thuận yêu cầu trả hàng"),
                (REJECT_RETURN, "Từ chối yêu cầu trả hàng"),
            ]
            self.fields["reason"].help_text = "Bắt buộc nhập lý do nếu từ chối."
        self.fields["to_status"].choices = choices
        self.return_lines = []
        if order.status == Order.Status.RETURN_APPROVED:
            self.return_lines = list(order.return_request.items.select_related("order_item"))
            for line in self.return_lines:
                self.fields[f"resellable_{line.pk}"] = forms.IntegerField(
                    label=f"{line.order_item.name_snapshot} — số lượng bán lại được",
                    min_value=0, max_value=line.quantity,
                    help_text=f"Nhận trả {line.quantity}. Nhập 0 nếu toàn bộ hàng trả bị hỏng.",
                )

    def clean(self):
        data = super().clean()
        if self.return_lines:
            data["inspections"] = {
                line.pk: data.pop(f"resellable_{line.pk}", None) for line in self.return_lines
            }
        return data
