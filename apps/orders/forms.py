from django import forms

from apps.common.forms import MobilePhoneField

from .models import Order


class CheckoutForm(forms.Form):
    checkout_key = forms.UUIDField(widget=forms.HiddenInput)
    recipient_name = forms.CharField(label="Họ tên người nhận", max_length=150)
    phone = MobilePhoneField()
    address = forms.CharField(
        label="Địa chỉ nhận hàng", widget=forms.Textarea(attrs={"rows": 3}), max_length=2000
    )
    payment_method = forms.ChoiceField(label="Thanh toán", choices=Order.PaymentMethod.choices)


class OrderReturnForm(forms.Form):
    reason = forms.CharField(
        label="Lý do trả hàng",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    evidence = forms.FileField(
        label="Ảnh bằng chứng",
        help_text="Chọn một ảnh JPG, PNG hoặc WebP, tối đa 5 MB.",
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )

    def __init__(self, *args, order, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_items = list(order.items.all())
        for item in self.order_items:
            self.fields[f"return_{item.pk}"] = forms.IntegerField(
                label=f"{item.name_snapshot} — đã mua {item.quantity}", required=False,
                min_value=0, max_value=item.quantity - item.returned_quantity, initial=0,
            )

    def clean(self):
        data = super().clean()
        quantities = {
            item.pk: data.get(f"return_{item.pk}") for item in self.order_items
            if data.get(f"return_{item.pk}", 0)
        }
        if not quantities:
            raise forms.ValidationError("Nhập số lượng cần trả ở ít nhất một sản phẩm.")
        data["quantities"] = quantities
        for item in self.order_items:
            data.pop(f"return_{item.pk}", None)
        return data
