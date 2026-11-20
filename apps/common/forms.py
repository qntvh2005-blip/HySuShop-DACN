from django import forms

from .validators import MOBILE_PHONE_MESSAGE, MOBILE_PHONE_PATTERN, validate_phone_number


class MobilePhoneField(forms.CharField):
    def __init__(self, *, required=True):
        super().__init__(
            label="Số điện thoại",
            required=required,
            strip=False,
            validators=[validate_phone_number],
            widget=forms.TextInput(
                attrs={
                    "type": "tel",
                    "inputmode": "numeric",
                    "autocomplete": "tel-national",
                    "maxlength": 10,
                    "pattern": MOBILE_PHONE_PATTERN,
                    "title": MOBILE_PHONE_MESSAGE,
                    "class": "mobile-phone-input",
                }
            ),
            help_text=MOBILE_PHONE_MESSAGE,
        )
