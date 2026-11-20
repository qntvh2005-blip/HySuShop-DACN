"""Device mappings from product titles and reviewed storefront metadata."""

import re
from dataclasses import dataclass

from django.db import transaction
from django.utils.text import slugify

from .models import PhoneModel, ProductCompatibility
from .reviewed_compatibility import REVIEWED_DEVICE_NAMES


@dataclass(frozen=True, order=True)
class Device:
    manufacturer: str
    name: str


APPLE_TOKEN = r"(?:SE(?:\s*20(?:16|20|22))?|XS|XR|X|(?:[3-9]|1\d|20)(?:GS|[CSG])?)(?:\s*(?:Pro\s*Max|Pro|Plus|Max|Mini))?"
SAMSUNG_TOKEN = r"(?:Z\s+Flip\s+3|Note\s*\d{1,2}|[SAMF]\d{1,3}e?)(?:\s*(?:Ultra|Plus|Edge\s*(?:Plus|\+)|Edge|FE|Active|Lite|\+))?(?:\s*5G)?"
PIXEL_TOKEN = r"\d{1,2}a?(?:\s*(?:Pro|XL))?"
APPLE_SE = re.compile(r"SE(?:\s*20(?:16|20|22))?", re.I)
SE_GENERATION_NOTE = re.compile(
    r"\s*\((?:\s*(?:20(?:16|20|22)|1st|2nd|3rd|gen(?:eration)?s?|and|[,&/-]))+\s*\)",
    re.I,
)
NEGATIVE = re.compile(
    r"\b(?:not\s+(?:(?:compatible|designed|suitable)\s+)?(?:for|with)|"
    r"not\s+(?:fit|fits|support|compatible)|does\s+not\s+(?:fit|support)|"
    r"except(?:\s+for)?|excluding|incompatible\s+with|"
    r"không\s+(?:dùng\s+cho|tương\s+thích\s+với|phù\s+hợp\s+với))\b",
    re.I,
)

# Reviewed names supported by this importer, not a guess from any arbitrary
# number in seller metadata. Unknown names remain available for manual review.
APPLE_NAMES = {
    "3G",
    "3GS",
    "4",
    "4s",
    "5",
    "5s",
    "5c",
    "6",
    "6s",
    "6 Plus",
    "6s Plus",
    "7",
    "7 Plus",
    "8",
    "8 Plus",
    "X",
    "XR",
    "XS",
    "XS Max",
    "11",
    "11 Pro",
    "11 Pro Max",
    "12",
    "12 Mini",
    "12 Pro",
    "12 Pro Max",
    "13",
    "13 Mini",
    "13 Pro",
    "13 Pro Max",
    "14",
    "14 Plus",
    "14 Pro",
    "14 Pro Max",
}
SAMSUNG_NAMES = {
    "Z Flip 3",
    "A50",
    "S2",
    "S3",
    "S4",
    "S4 Active",
    "S5",
    "S6",
    "S6 Edge",
    "S6 Edge Plus",
    "S7",
    "S7 Edge",
    "S8",
    "S8 Plus",
    "S9",
    "S9 Plus",
    "S10",
    "S10 Plus",
    "S10e",
    "S20",
    "S20 Plus",
    "S20 Ultra",
    "S20 FE",
    "S21",
    "S21 Plus",
    "S21 Ultra",
    "S21 FE",
    "S22",
    "S22 Plus",
    "S22 Ultra",
    "S23",
    "S23 Plus",
    "S23 Ultra",
    "Note 2",
    "Note 3",
    "Note 4",
    "Note 5",
    "Note 8",
    "Note 9",
    "Note 10",
    "Note 10 Plus",
    "Note 20",
    "Note 20 Ultra",
}
PIXEL_NAMES = {
    "2",
    "2 XL",
    "3",
    "3 XL",
    "3a",
    "3a XL",
    "4",
    "4 XL",
    "4a",
    "5",
    "5a",
    "6",
    "6 Pro",
    "6a",
    "7",
    "7 Pro",
    "7a",
}


def _se_devices(context):
    years = set(re.findall(r"\b(?:2016|2020|2022)\b", context))
    years.update(re.findall(r"\bSE\s*(2016|2020|2022)\b", context, re.I))
    ordinal_years = {"1st": "2016", "2nd": "2020", "3rd": "2022"}
    ordinal = r"(?:1st|2nd|3rd)"
    for match in re.finditer(
        rf"\b({ordinal}(?:\s*(?:,|/|&|and)\s*{ordinal})*)\s*gen(?:eration)?s?\b",
        context,
        re.I,
    ):
        years.update(ordinal_years[value] for value in re.findall(ordinal, match[1].lower()))
    # An explicit SE 2/SE 3 is also a generation, not a generic SE.
    for generation, year in [("2", "2020"), ("3", "2022")]:
        if re.search(r"\bSE\s+" + generation + r"\b(?!\s*[- ]?pack\b)", context, re.I):
            years.add(year)
    return {Device("Apple", f"iPhone SE ({year})") for year in years}


def _extract(text):
    devices = set()
    families = [
        (r"\biPhone\s*", APPLE_TOKEN, "Apple"),
        (r"\b(?:Samsung\s+)?Galaxy\s+|\bSamsung\s+(?=[SAMF]\d|Note)", SAMSUNG_TOKEN, "Samsung"),
        (r"\b(?:Google\s+)?Pixel\s*", PIXEL_TOKEN, "Google"),
    ]
    for prefix, token, manufacturer in families:
        # Seller lists often end with screen sizes or pack quantities. These
        # numbers are not another phone model (for example: "8,7,6, 4.7-Inch").
        model_end = r'(?=\W|$)(?!\.\d)(?!\s*[- ]?(?:inch(?:es)?\b|in\b|["″]|packs?\b|pcs\b|pieces\b))'
        pattern = re.compile(r"(?:" + prefix + r")(?P<model>" + token + r")" + model_end, re.I)
        continuation = re.compile(r"\s*(?:/|,|&|\band\b)\s*(?P<model>" + token + r")" + model_end, re.I)
        for match in pattern.finditer(text):
            models = []
            current = match
            while current:
                model = current.group("model")
                finish = current.end()
                models.append((model, current.start(), finish))
                if manufacturer == "Apple" and APPLE_SE.fullmatch(model):
                    note = SE_GENERATION_NOTE.match(text, finish)
                    if note:
                        finish = note.end()
                current = continuation.match(text, finish)
            for model, start, finish in models:
                model = " ".join(model.split())
                model = re.sub(r"(?<=[\dXSR])(?=Pro|Plus|Max|Mini|XL)", " ", model, flags=re.I)
                if manufacturer == "Apple" and APPLE_SE.fullmatch(model):
                    suffix = re.split(
                        r"\biPhone\b|\bGalaxy\b|\bPixel\b", text[finish : finish + 60], flags=re.I
                    )[0]
                    # Only explicit years/generations: generic SE stays unverified.
                    devices.update(
                        _se_devices(text[max(0, start - 15) : start] + " " + model + " " + suffix)
                    )
                elif manufacturer == "Apple":
                    base, *rest = model.split()
                    base = base.upper() if base.upper() in {"X", "XS", "XR"} else base.lower()
                    model = " ".join([base, *[v.title() for v in rest]])
                    model = {
                        "10": "X",
                        "10s": "XS",
                        "10s Max": "XS Max",
                        "4g": "4",
                        "3g": "3G",
                        "3gs": "3GS",
                    }.get(model, model)
                    if model in APPLE_NAMES:
                        devices.add(Device(manufacturer, "iPhone " + model))
                elif manufacturer == "Samsung":
                    model = re.sub(r"^z flip ", "Z Flip ", model, flags=re.I)
                    model = re.sub(
                        r"(?<=\d)(?=Ultra|Plus|Edge|FE|Active|Lite|5G)", " ", model, flags=re.I
                    )
                    model = re.sub(r"\bnote\s*", "Note ", model, flags=re.I)
                    model = re.sub(
                        r"\b([samf])(\d+)", lambda m: m[1].upper() + m[2], model, flags=re.I
                    )
                    model = re.sub(r"(?<=\d)e\b", "e", model, flags=re.I)
                    model = re.sub(r"\s*\+", " Plus", model)
                    model = re.sub(
                        r"\b(?:ultra|plus|edge|active|lite)\b",
                        lambda m: m[0].title(),
                        model,
                        flags=re.I,
                    )
                    model = re.sub(r"\bfe\b", "FE", model, flags=re.I)
                    model = re.sub(r"\b5g\b", "5G", model, flags=re.I)
                    if re.sub(r" 5G$", "", model) in SAMSUNG_NAMES:
                        devices.add(Device(manufacturer, "Galaxy " + model))
                else:
                    model = re.sub(r"(?<=\d)a\b", "a", model, flags=re.I)
                    model = re.sub(r"\bpro\b", "Pro", model, flags=re.I)
                    model = re.sub(r"\bxl\b", "XL", model, flags=re.I)
                    if model in PIXEL_NAMES:
                        devices.add(Device(manufacturer, "Pixel " + model))
    # Common first-generation wording: "2016 1st Gen SE" after iPhone 5/5S.
    if re.search(r"\biPhone\b", text, re.I):
        for match in re.finditer(
            r"\b(?:2016|2020|2022)\s+(?:[123](?:st|nd|rd)\s+Gen\s+)?SE\b", text, re.I
        ):
            devices.update(_se_devices(match[0]))
    nexus_model = r"(?:5X|5|6P|6)"
    for match in re.finditer(rf"\bNexus\s+({nexus_model}(?:\s*/\s*{nexus_model})*)\b", text, re.I):
        devices.update(
            Device("Google", f"Nexus {model.strip().upper()}") for model in match[1].split("/")
        )
    for match in re.finditer(r"\bLG\s+(G3|G4|V10|V20)(?![\w+]|\s+Stylus\b)", text, re.I):
        devices.add(Device("LG", f"LG {match[1].upper()}"))
    return devices


def devices_from_title(title):
    title = str(title or "")
    title = re.sub(r"\bGalaxy\s+S\s+III\b", "Galaxy S3", title, flags=re.I)
    title = re.sub(r"\biPhone\s+Series\s+(?=\d)", "iPhone ", title, flags=re.I)
    title = re.sub(r"\bApple SE\s*(?=\(20(?:16|20|22)\))", "iPhone SE ", title, flags=re.I)
    excluded, spans = set(), []
    for match in NEGATIVE.finditer(title):
        end = re.search(r"[\]);]", title[match.end() :])
        stop = match.end() + end.start() if end else len(title)
        clause = title[match.start() : stop]
        excluded.update(_extract(clause))
        # Seller exclusions also abbreviate the family: "iPhone 12 Pro Max
        # (not for 12 Pro)". Carry only the nearest explicit family here.
        body = title[match.end() : stop].strip()
        family_pattern = (
            r"\biPhone(?:\s*SE)?\b|\b(?:Samsung\s+)?Galaxy\b|"
            r"\b(?:Google\s+)?(?:Pixel|Nexus)\b|\bLG\b"
        )
        if not re.search(family_pattern, body, re.I):
            previous = list(re.finditer(family_pattern, title[: match.start()], re.I))
            if previous:
                excluded.update(_extract(previous[-1][0] + " " + body))
        spans.append((match.start(), stop))
    merged = []
    for start, stop in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(stop, merged[-1][1]))
        else:
            merged.append((start, stop))
    positive = title
    for start, stop in reversed(merged):
        positive = positive[:start] + " " + positive[stop:]
    return sorted(_extract(positive) - excluded)


def devices_from_source(source, fallback=""):
    item_id = source.get("item_id")
    if item_id == "B0042FV2SI":
        # Both the explicit model attribute and the feature list confirm the
        # ambiguous "Phone 4" wording in the title for this specific item.
        return [Device("Apple", "iPhone 4"), Device("Apple", "iPhone 4s")]
    if item_id == "B01DLYEZXO":
        # Title, phone model attribute and features disagree on this variant.
        return []
    if item_id in REVIEWED_DEVICE_NAMES:
        return [
            Device(manufacturer, name)
            for manufacturer, names in REVIEWED_DEVICE_NAMES[item_id].items()
            for name in names.split("|")
        ]
    return devices_from_title(source.get("title") or fallback)


MODEL_GUIDANCE = {
    "B00CM0PL1E": "Cáp dùng đầu Apple Dock 30 chân. Đối chiếu cổng trên thiết bị trước khi chọn.",
    "B00GM0OZ4O": "Điện thoại cần có cổng Micro USB và hỗ trợ OTG để kết nối thiết bị ngoại vi.",
    "B00HY3HT1Y": "Cần bề mặt phẳng để dán. Một số mặt lưng kính cần dùng ốp có bề mặt phù hợp.",
    "B015CMD692": "Cáp đi kèm dùng đầu Micro USB. Nếu điện thoại dùng cổng khác, hãy chọn cáp phù hợp và đối chiếu thông số sạc.",
    "B01A6L85CC": "Cáp sạc tích hợp dùng đầu Lightning. Đối chiếu loại đầu cắm trên điện thoại.",
    "B07586VK1V": "Cáp đi kèm dùng đầu Lightning, phù hợp với thiết bị Apple có cổng này.",
    "B0C575KCXJ": "Đầu chuyển du lịch có hai cổng USB. Chọn cáp phù hợp với cổng sạc của điện thoại. Phần chuyển phích cắm không đổi điện áp.",
    "B01DLYEZXO": "Miếng thu sạc dùng đầu Micro USB. Thông tin nguồn về mẫu máy chưa thống nhất, cần đối chiếu đúng kiểu cổng và chiều cắm của biến thể trước khi mua.",
    "B01J21HAPK": "Hộp đựng cho pin dự phòng Anker PowerCore 20100 mAh.",
    "B01MXL14SG": "Hộp đựng cho Anker PowerCore 26800 và PowerCore III Elite 25600 PD.",
    "B0868ZQ742": "Dây giữ đầu chuyển. Đối chiếu kích thước dây và đầu chuyển đang dùng.",
    "B01DKEXMVG": "Miếng kim loại thay thế. Kiểm tra loại đế gắn nam châm đang dùng.",
    "B0722DWXSY": "Miếng kim loại thay thế cho đế gắn nam châm Spigen QNMP.",
    "B0C1DKK6FC": "Miếng gắn thay thế cho giá đỡ nam châm Scosche MagicMount.",
    "B07CNBJFFT": "Đầu bút thay thế cho bút The Friendly Swede 5,5 inch có đầu nhỏ tháo rời.",
    "B09M36MTJR": "Giá gắn khe gió dành cho tay cầm PopSockets.",
}


def compatibility_guidance(source):
    from .localization import storefront_category

    item_id = source.get("item_id")
    if item_id in MODEL_GUIDANCE:
        return MODEL_GUIDANCE[item_id]
    category = storefront_category(source)
    if category in {"Wall Chargers", "Portable Power Banks", "Automobile Chargers", "Chargers & Power Adapters"}:
        return "Chọn theo cổng sạc, loại cáp và công suất mà điện thoại hỗ trợ."
    if category in {"Wireless Chargers", "Charging Stations"}:
        if re.search(r"\bqi\b", source.get("title") or "", re.I):
            return "Sản phẩm dùng chuẩn sạc không dây Qi. Kiểm tra thiết bị của bạn có hỗ trợ chuẩn Qi."
        return "Kiểm tra chuẩn sạc và kiểu kết nối của từng vị trí sạc trước khi chọn."
    if category in {"Cables & Adapters", "OTG Adapters"}:
        return "Kiểm tra loại cổng ở hai đầu. Với đầu chuyển OTG, điện thoại cần hỗ trợ OTG."
    if category in {"Cradles", "Tripods", "Stands", "Selfie Sticks", "Armbands", "Dry Bags", "Photo & Video Kits", "UV Phone Sterilizer Boxes"}:
        return "Đối chiếu kích thước điện thoại, kể cả ốp nếu có, với phần kẹp hoặc ngăn giữ của phụ kiện."
    if category in {"Grips", "Pads & Mats", "Adhesive Card Holders"}:
        return "Kiểm tra kích thước và bề mặt đặt hoặc dán của điện thoại hay ốp lưng."
    if category == "Single Ear Bluetooth Headsets":
        return "Kết nối qua Bluetooth. Kiểm tra thiết bị có hỗ trợ âm thanh qua Bluetooth."
    if category == "Stylus Pens":
        return "Kiểm tra màn hình cảm ứng và loại bút mà thiết bị hỗ trợ."
    return ""


@transaction.atomic
def sync_product_compatibilities(product, devices=None):
    """Replace generated links, preserving every manual decision and phone ID."""
    devices = (
        devices
        if devices is not None
        else devices_from_source(product.source_metadata, product.name)
    )
    desired = set()
    created = 0
    for device in devices:
        phone = PhoneModel.objects.filter(
            manufacturer=device.manufacturer, name=device.name
        ).first()
        if phone is None:
            phone = PhoneModel.objects.create(
                manufacturer=device.manufacturer,
                name=device.name,
                slug=slugify(f"{device.manufacturer} {device.name}"),
            )
        desired.add(phone.pk)
        link, added = ProductCompatibility.objects.get_or_create(
            product=product, phone_model=phone, defaults={"source": "metadata", "verified": True}
        )
        if link.source == "metadata" and not link.verified:
            link.verified = True
            link.save(update_fields=["verified"])
        created += int(added)
    removed, _ = (
        ProductCompatibility.objects.filter(product=product, source="metadata")
        .exclude(phone_model_id__in=desired)
        .delete()
    )
    return created, removed
