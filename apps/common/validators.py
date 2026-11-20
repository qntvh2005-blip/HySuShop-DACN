import re

from django.core.exceptions import ValidationError

MOBILE_PHONE_PATTERN = r"0[35789][0-9]{8}"
MOBILE_PHONE_MESSAGE = "Nhập 10 chữ số, bắt đầu bằng 03, 05, 07, 08 hoặc 09."


def validate_phone_number(value):
    if not re.fullmatch(MOBILE_PHONE_PATTERN, value):
        raise ValidationError(MOBILE_PHONE_MESSAGE)


def normalize_stored_phone(value):
    phone = re.sub(r"[\s().-]", "", value)
    if phone.startswith("+84"):
        phone = "0" + phone[3:]
    return phone if re.fullmatch(MOBILE_PHONE_PATTERN, phone) else ""
