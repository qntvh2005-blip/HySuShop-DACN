from django import forms
from django.contrib.auth.forms import UserCreationForm

from apps.catalog.device_choices import available_phone_models
from apps.common.forms import MobilePhoneField

from .models import User
from .roles import ROLE_CHOICES


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True, label="Email", max_length=254)

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]


class ProfileForm(forms.Form):
    first_name = forms.CharField(label="Tên", max_length=150, required=False)
    last_name = forms.CharField(label="Họ", max_length=150, required=False)
    email = forms.EmailField(label="Email", required=False, max_length=254)
    phone = MobilePhoneField(required=False)
    default_address = forms.CharField(
        label="Địa chỉ mặc định",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=False,
        max_length=2000,
    )
    preferred_devices = forms.ModelChoiceField(
        available_phone_models(),
        label="Điện thoại bạn đang dùng (không bắt buộc)",
        help_text="Dùng cho nhóm phụ kiện tương thích riêng. Bạn vẫn nhận gợi ý khi chưa chọn.",
        required=False,
        empty_label="Chưa chọn điện thoại",
        widget=forms.Select(attrs={"class": "form-select device-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        selected = self.initial.get("preferred_devices")
        if selected:
            self.fields["preferred_devices"].queryset = available_phone_models(include_id=selected)


class AccountAccessForm(forms.Form):
    is_active = forms.BooleanField(label="Cho phép đăng nhập", required=False)
    role = forms.ChoiceField(
        label="Vai trò", choices=ROLE_CHOICES
    )

class AccountCreationForm(UserCreationForm):
    email = forms.EmailField(label="Email", required=True, max_length=254)
    role = forms.ChoiceField(
        label="Vai trò", choices=ROLE_CHOICES
    )
    is_active = forms.BooleanField(label="Cho phép đăng nhập", required=False, initial=True)

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]

