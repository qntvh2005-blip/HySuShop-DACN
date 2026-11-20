"""Vietnamese storefront summaries, separate from the frozen research corpus.

Only explicit source attributes are summarized. Untranslated source paragraphs
stay in source_metadata for reference; they are never passed off as a full
translation or used to invent specifications.
"""

import re

CATEGORY_NAMES = {
    "Basic Cases": "Ốp lưng điện thoại",
    "Cradles": "Giá đỡ điện thoại trên ô tô",
    "Single Ear Bluetooth Headsets": "Tai nghe Bluetooth một bên",
    "Screen Protectors": "Miếng dán và kính bảo vệ màn hình",
    "iPhone Accessories": "Phụ kiện iPhone",
    "Tripods": "Chân máy và kẹp điện thoại",
    "Automobile Chargers": "Bộ sạc trên ô tô",
    "Battery Charger Cases": "Ốp lưng kiêm pin dự phòng",
    "Stylus Pens": "Bút cảm ứng",
    "Wall Chargers": "Củ sạc điện thoại",
    "Portable Power Banks": "Pin sạc dự phòng",
    "OTG Adapters": "Đầu chuyển OTG",
    "Holsters": "Bao đeo và ốp kẹp thắt lưng",
    "Maintenance, Upkeep & Repairs": "Vệ sinh và sửa chữa điện thoại",
    "Accessories": "Phụ kiện điện thoại",
    "Flip Cases": "Bao da và ốp nắp gập",
    "Dry Bags": "Túi chống nước điện thoại",
    "Cables & Adapters": "Cáp sạc và đầu chuyển",
    "Lens Attachments": "Ống kính gắn ngoài điện thoại",
    "Stands": "Giá đỡ điện thoại",
    "Wireless Chargers": "Bộ sạc không dây",
    "Adhesive Card Holders": "Ví đựng thẻ dán điện thoại",
    "Charging Stations": "Trạm sạc nhiều thiết bị",
    "Batteries": "Pin và bộ sạc pin rời",
    "Cases, Holsters & Sleeves": "Ốp lưng và bao bảo vệ",
    "Solar Chargers": "Bộ sạc năng lượng mặt trời",
    "Selfie Sticks": "Gậy chụp ảnh tự sướng",
    "Virtual Reality (VR) Headsets": "Kính thực tế ảo và phụ kiện",
    "Grips": "Tay cầm và vòng giữ điện thoại",
    "Pads & Mats": "Miếng đệm chống trượt",
    "Chargers & Power Adapters": "Bộ sạc và bộ đổi nguồn",
    "Lanyards & Wrist Straps": "Dây đeo điện thoại",
    "Photo & Video Kits": "Bộ phụ kiện chụp ảnh và quay phim",
    "Case & Cover Bundles": "Bộ ốp lưng và phụ kiện bảo vệ",
    "UV Phone Sterilizer Boxes": "Hộp khử khuẩn điện thoại bằng tia UV",
    "Sleeves": "Túi và bao đựng điện thoại",
    "Selfie Lights": "Đèn hỗ trợ chụp ảnh",
    "Armbands": "Bao đeo điện thoại khi tập thể thao",
    "Bumpers": "Ốp viền điện thoại",
    "iPhone X Wallet": "Ốp ví đựng thẻ cho iPhone X",
}

# Corrections for reviewed source records. Keep the original category path in
# source_metadata, since the research dataset still uses that path.
STOREFRONT_CATEGORIES = {
    "B005REEWYY": "Batteries",
    "B00ANALDWQ": "Basic Cases",
    "B00APUFHIA": "Basic Cases",
    "B00IHS1XI0": "Wireless Chargers",
    "B00L4RYCMU": "Cables & Adapters",
    "B00M798YZU": "Basic Cases",
    "B00MXEJ8UO": "Basic Cases",
    "B00PADY6D4": "Basic Cases",
    "B00SC7FR2E": "Basic Cases",
    "B00YG6H4XA": "Maintenance, Upkeep & Repairs",
    "B012KEIPGO": "Screen Protectors",
    "B01BHEIIR4": "Wireless Chargers",
    "B01DIUNIQG": "Selfie Sticks",
    "B01DLYEZXO": "Accessories",
    "B01KJL4XNY": "Wireless Chargers",
    "B01J21HAPK": "Accessories",
    "B01MXL14SG": "Accessories",
    "B06XCRZZTW": "Cradles",
    "B0756Z8X82": "Wireless Chargers",
    "B07G5T65JQ": "Wireless Chargers",
    "B07GFC2JQC": "Basic Cases",
    "B085W5XVV6": "Cables & Adapters",
    "B0868ZQ742": "Accessories",
    "B093BRHW8V": "Wireless Chargers",
    "B09H6H8B51": "Chargers & Power Adapters",
    "B09RSLYK5B": "Cables & Adapters",
    "B0C1DKK6FC": "Accessories",
    "B0C575KCXJ": "Chargers & Power Adapters",
}

STOREFRONT_TYPES = {
    "B00L4RYCMU": "Đầu chuyển USB-C sang tai nghe 3,5 mm",
    "B00YG6H4XA": "Bộ thay nắp cổng sạc",
    "B015CMD692": "Củ sạc điện thoại kèm cáp",
    "B01DLYEZXO": "Miếng thu sạc không dây",
    "B074481TQT": "Pin dự phòng kiêm củ sạc điện thoại",
    "B07DCRVBYX": "Ổ cắm chống quá áp có cổng USB",
    "B07GBN8HBN": "Trạm sạc điện thoại và đồng hồ",
    "B0868ZQ742": "Dây giữ đầu chuyển",
    "B09H6H8B51": "Ổ cắm tường có cổng USB",
    "B09RSLYK5B": "Đầu chuyển USB-C sang USB-A",
    "B0C1DKK6FC": "Miếng gắn cho giá đỡ nam châm",
    "B0C575KCXJ": "Đầu chuyển phích cắm du lịch có hai cổng USB",
    "B01J21HAPK": "Hộp đựng pin sạc dự phòng",
    "B01MXL14SG": "Hộp đựng pin sạc dự phòng",
}

# The items are kept in the database for research and existing references.
# Their source records are outside the shop's scope or contradict themselves.
UNLISTED_SOURCE_ITEMS = {
    "B008ASW57U",  # Kitchen thermometer title and features, screen protector description.
    "B008THTTUI",  # iPad Air title and iPhone 5/SE specifications conflict.
    "B00K5NYTCM",  # Tablet case.
    "B00MXDZFFM",  # Adapter title, screen protector features, placeholder image.
    "B016LO4UTA",  # Mixed screen protector, adapter and earbud information.
    "B07CW35VPT",  # Water bottle.
    "B00D856NOG",  # Amalen title, FUNTTZ brand, Anker store.
    "B00M3073L4",  # Anker title, GaeruRxewn brand/store.
    "B00OHE8AOI",  # XINKSD title, FUNTTZ brand/store.
    "B017JT6846",  # XINKSD title, Anker brand/store.
    "B01D8C6ULO",  # XINKSD title, WTULEY brand/store.
    "B0756Z8X82",  # Anker title/store, Samsung brand.
    "B07WR4J1GN",  # OULUOQI title, BRG brand/store.
}

CASE_CATEGORIES = {
    "Basic Cases",
    "Battery Charger Cases",
    "Bumpers",
    "Case & Cover Bundles",
    "Cases, Holsters & Sleeves",
    "Flip Cases",
    "Holsters",
}

COLORS = {
    "black": "Đen",
    "white": "Trắng",
    "clear": "Trong suốt",
    "transparent": "Trong suốt",
    "crystal clear": "Trong suốt",
    "matte black": "Đen nhám",
    "blue": "Xanh dương",
    "red": "Đỏ",
    "silver": "Bạc",
    "gold": "Vàng",
    "rose gold": "Vàng hồng",
    "grey": "Xám",
    "gray": "Xám",
    "green": "Xanh lá",
    "pink": "Hồng",
    "purple": "Tím",
    "orange": "Cam",
    "yellow": "Vàng",
    "brown": "Nâu",
    "beige": "Be",
    "navy": "Xanh hải quân",
    "navy blue": "Xanh hải quân",
    "gunmetal": "Xám kim loại",
    "burgundy": "Đỏ rượu vang",
    "teal": "Xanh mòng két",
    "mint": "Xanh bạc hà",
    "coral": "Cam san hô",
    "lavender": "Tím oải hương",
    "turquoise": "Xanh ngọc",
    "aqua": "Xanh ngọc",
    "champagne gold": "Vàng champagne",
    "satin silver": "Bạc satin",
    "hot pink": "Hồng đậm",
    "light blue": "Xanh dương nhạt",
    "dark blue": "Xanh dương đậm",
    "light pink": "Hồng nhạt",
    "space gray": "Xám không gian",
    "space grey": "Xám không gian",
    "midnight green": "Xanh rêu",
    "multicolor": "Nhiều màu",
    "multi-color": "Nhiều màu",
    "rainbow": "Cầu vồng",
}
MATERIALS = {
    "tempered glass": "Kính cường lực",
    "ballistic glass": "Kính bảo vệ",
    "glass": "Kính",
    "thermoplastic polyurethane": "Nhựa TPU",
    "polycarbonate": "Nhựa PC",
    "poly-carbonate": "Nhựa PC",
    "tpu": "Nhựa TPU",
    "polyethylene terephthalate": "Nhựa PET",
    "pet film": "Màng PET",
    "synthetic rubber": "Cao su tổng hợp",
    "rubber": "Cao su",
    "plastic": "Nhựa",
    "silicone": "Silicone",
    "silicon": "Silicone",
    "faux leather": "Da nhân tạo",
    "pu leather": "Da PU",
    "leather": "Da",
    "microfiber": "Sợi vi mảnh",
    "aluminum alloy": "Hợp kim nhôm",
    "aluminum": "Nhôm",
    "aluminium": "Nhôm",
    "metal": "Kim loại",
    "steel": "Thép",
    "stainless steel": "Thép không gỉ",
    "crystal": "Pha lê",
    "nylon": "Nylon",
    "neoprene": "Cao su neoprene",
    "urethane": "Urethane",
    "polyurethane": "Nhựa PU",
    "polyvinyl chloride": "Nhựa PVC",
    "carbon fiber": "Sợi carbon",
    "acrylic": "Nhựa acrylic",
    "cork": "Bần",
    "wood": "Gỗ",
    "gel": "Gel",
    "pc": "Nhựa PC",
    "pet": "Nhựa PET",
}
FEATURES = {
    "scratch resistant": "Hạn chế trầy xước",
    "anti-scratch": "Hạn chế trầy xước",
    "anti-fingerprint": "Hạn chế bám vân tay",
    "anti fingerprint": "Hạn chế bám vân tay",
    "smudge resistant": "Hạn chế bám bẩn",
    "oil resistant": "Hạn chế bám dầu",
    "anti glare": "Hạn chế chói",
    "anti-glare": "Hạn chế chói",
    "touch sensitive": "Hỗ trợ thao tác cảm ứng",
    "touch accuracy": "Hỗ trợ thao tác cảm ứng",
    "9h surface hardness": "Độ cứng bề mặt 9H",
    "9 h surface hardness": "Độ cứng bề mặt 9H",
    "9h hardness": "Độ cứng bề mặt 9H",
    "rounded edge": "Cạnh bo tròn",
    "2.5d rounded edge": "Cạnh bo tròn 2.5D",
    "bubble proof": "Hạn chế bọt khí khi dán",
    "easy installation": "Dễ lắp đặt",
    "case-friendly": "Thiết kế dùng cùng ốp lưng",
    "self-healing": "Tự phục hồi vết xước nhỏ",
    "flexible": "Có độ dẻo",
    "fast charging": "Hỗ trợ sạc nhanh",
    "fast charge": "Hỗ trợ sạc nhanh",
    "fast charger": "Hỗ trợ sạc nhanh",
    "wireless charging": "Hỗ trợ sạc không dây",
    "wireless charger": "Sạc không dây",
    "wireless": "Kết nối không dây",
    "magnetic": "Có nam châm",
    "short circuit protection": "Bảo vệ ngắn mạch",
    "foldable": "Có thể gấp gọn",
    "adjustable": "Có thể điều chỉnh",
    "rotatable": "Có thể xoay",
    "lightweight": "Trọng lượng nhẹ",
    "portable": "Dễ mang theo",
    "portable charger": "Sạc di động",
    "travel": "Thuận tiện khi di chuyển",
    "microphone": "Có micrô",
    "noise_cancellation": "Hỗ trợ giảm tiếng ồn",
    "noise cancellation": "Hỗ trợ giảm tiếng ồn",
    "water-resistant": "Hạn chế thấm nước",
    "water resistant": "Hạn chế thấm nước",
    "drop resistant": "Hạn chế tác động khi rơi",
    "shock resistant": "Hỗ trợ giảm chấn",
    "shock absorbent": "Hỗ trợ giảm chấn",
    "shockproof": "Hỗ trợ giảm chấn",
    "kickstand": "Có chân chống",
    "belt clip": "Có kẹp thắt lưng",
    "card slot": "Có ngăn đựng thẻ",
    "grip": "Hỗ trợ cầm nắm",
    "reusable": "Có thể tái sử dụng",
    "ultra thin": "Thiết kế mỏng",
}


def clean(value):
    return " ".join(str(value or "").split())


def matched_terms(value, terms):
    """Consume longest known phrases once; do not translate unknown prose."""
    remaining = clean(value).lower()
    result = []
    for source in sorted(terms, key=len, reverse=True):
        pattern = re.compile(r"(?<!\w)" + re.escape(source) + r"(?!\w)", re.I)
        if pattern.search(remaining):
            result.append(terms[source])
            remaining = pattern.sub(" ", remaining)
    return list(dict.fromkeys(result))


def category_name(name):
    return CATEGORY_NAMES.get(name, name)


def source_category(item):
    return (item.get("categories") or ["Phụ kiện điện thoại"])[-1]


def storefront_category(item):
    return STOREFRONT_CATEGORIES.get(item.get("item_id"), source_category(item))


def product_type(item):
    title = clean(item.get("title")).lower()
    leaf = storefront_category(item)
    override = STOREFRONT_TYPES.get(item.get("item_id"))
    if override:
        return override
    if re.search(r"\btv (?:wall )?mount\b", title):
        return "Giá treo tivi"
    if leaf in {"Charging Stations", "Wireless Chargers"} and re.search(
        r"\b(?:apple watch|iwatch|watches|watch)\b", title
    ) and re.search(r"\b(?:charger|charging station)\b", title):
        return (
            "Trạm sạc điện thoại và đồng hồ"
            if re.search(r"\b(?:iphone|phones?|smartphones?)\b", title)
            else "Bộ sạc đồng hồ"
        )
    if leaf == "Virtual Reality (VR) Headsets" and re.search(r"\b(?:case|bag)\b", title):
        return "Bao bảo vệ kính thực tế ảo"
    if re.search(r"\bbattery case\b|\bcharger case\b", title):
        return "Ốp lưng kiêm pin dự phòng"
    if re.search(r"\b(?:wallet case|flip (?:cover )?case)\b", title) and leaf in CASE_CATEGORIES:
        return "Ốp ví và bao nắp gập"
    if leaf == "Battery Charger Cases" and re.search(
        r"\b(?:hard case|case cover|back cover|protective.*case)\b", title
    ):
        return "Ốp lưng điện thoại"
    # Case listings can mention a screen protector as an included or excluded
    # part. Keep the label of the main product and preserve bundle categories.
    if leaf in CASE_CATEGORIES:
        return category_name(leaf)
    if re.search(r"\b(?:screen protectors?|screen protection|protective film)\b", title):
        material = clean((item.get("attributes") or {}).get("Material")).lower()
        return (
            "Kính cường lực bảo vệ màn hình"
            if "tempered glass" in material
            else "Miếng dán bảo vệ màn hình"
        )
    if re.search(r"\bcar charger\b", title):
        return "Bộ sạc trên ô tô"
    if leaf == "Batteries" and re.search(r"\bbattery charger\b", title):
        return "Bộ sạc pin rời"
    if leaf in {"Wall Chargers", "Chargers & Power Adapters"} and re.search(
        r"\bwall charger\b", title
    ):
        return "Củ sạc điện thoại"
    if leaf in {"Cables & Adapters", "Accessories", "Phụ kiện điện thoại", "iPhone Accessories"} and (
        re.search(r"\b(?:charging cable|charger cable|sync.*cable|data cable)\b", title)
    ):
        return "Cáp sạc và truyền dữ liệu"
    if re.search(r"\b(?:camera shutter|shutter remote)\b", title):
        return "Nút bấm chụp ảnh từ xa"
    if "card holder" in title and leaf == "Sleeves":
        return "Ví đựng thẻ dán điện thoại"
    if "tripod" in title and leaf == "Stands":
        return "Chân máy ảnh"
    if leaf in {"Basic Cases", "iPhone Accessories", "Phụ kiện điện thoại"} and re.search(
        r"\bcase\b", title
    ):
        return "Ốp lưng điện thoại"
    return category_name(leaf)


def device_names(value):
    """Use the same exclusions and SE generations as verified device links."""
    from .compatibility import devices_from_title

    return [device.name for device in devices_from_title(value)]


def title_series(title):
    # These are proper product-line names, retained rather than translated.
    patterns = [
        r"\bPowerCore\+?(?:\s+(?:mini|Slim|Essential|Select|Fusion|Metro|Speed|II|III))?",
        r"\bAnker\s+(\d{3})\b",
        r"\b(?:Pro CD-M|CD-Air|Magnetos CD)\b",
        r"\bPowerPort(?:\s+(?:Speed|Atom|Solar|mini|PD|III))?",
        r"\b(?:Defender|Commuter|Symmetry|Pursuit|Strada)\b",
        r"\b(?:(?:Tough|Rugged|Slim)\s+Armor|Liquid\s+Crystal|Neo Hybrid|Ultra Hybrid)\b",
        r"\b(?:Unicorn Beetle(?:\s+Pro)?|MilitaryShield|TechSkin|Easy One Touch|CandyShell)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, title, re.I)
        if match:
            return clean(match.group(1) if match.lastindex else match.group())
    return ""


def localized_product(item, brand=""):
    attributes = item.get("attributes") or {}
    title = clean(item.get("title"))
    kind = product_type(item)
    brand = clean(brand or attributes.get("Brand") or item.get("store"))
    model = clean(attributes.get("Item model number"))
    code_like = bool(
        re.search(r"\d", model)
        or re.fullmatch(r"[A-Z]{2,12}(?:-[A-Z]{1,12})*", model)
        or re.fullmatch(r"[A-Za-z]{2,12}(?:-[A-Za-z]{1,12}){1,2}", model)
    )
    if (
        len(model) > 65
        or not re.fullmatch(r"[\w .+/#()\-]+", model)
        or not code_like
        or device_names(model)
    ):
        model = ""
    colors = matched_terms(attributes.get("Color"), COLORS)
    materials = matched_terms(
        attributes.get("Material") or attributes.get("Material Type"), MATERIALS
    )
    # Attribute device lists are often copied across variants. Titles are the
    # reviewed source for both summaries and generated compatibility records.
    from .compatibility import devices_from_source

    devices = [device.name for device in devices_from_source(item)]
    name = kind + (f" {brand}" if brand else "")
    series = title_series(title)
    if series and series.lower() not in name.lower():
        name += " " + series
    if "car mount" in title.lower():
        if re.search(r"\bair vent\b", title, re.I):
            name += " gắn khe gió"
        elif re.search(r"\bdashboard\b", title, re.I):
            name += " gắn bảng điều khiển"
        elif re.search(r"\bCD slot\b", title, re.I):
            name += " gắn khe CD"
        if re.search(r"\btwist[ -]lock\b", title, re.I):
            name += " khóa vặn"
        if re.search(r"\brectangle\b", title, re.I):
            name += " hình chữ nhật"
        elif re.search(r"\bsquare\b", title, re.I):
            name += " hình vuông"
    if devices:
        name += " cho " + ", ".join(devices[:3])
    if model and model.lower() not in name.lower():
        name += f" ({model})"
    if colors:
        name += " – " + "/".join(colors[:3])
    capacities = list(dict.fromkeys(re.findall(r"\b\d+(?:\.\d+)?\s*mAh\b", title, re.I)))
    if capacities and "pin" in kind.lower():
        name += " – " + "/".join(capacities[:2])
    pack = re.search(r"\b([1-9]\d*)[ -]?pack\b", title, re.I)
    if pack:
        name += f" – Bộ {pack[1]} chiếc"

    features = []
    if colors:
        features.append("Màu sắc: " + ", ".join(colors) + ".")
    if materials:
        features.append("Chất liệu: " + ", ".join(materials) + ".")
    connectors = clean(attributes.get("Connector Type"))
    connector_names = matched_terms(
        connectors,
        {
            "usb type c": "USB-C",
            "usb type-c": "USB-C",
            "usb c": "USB-C",
            "usb-c": "USB-C",
            "usb type a": "USB-A",
            "usb-a": "USB-A",
            "micro usb type b": "Micro USB-B",
            "micro usb": "Micro USB",
            "micro-usb": "Micro USB",
            "lightning": "Lightning",
            "magsafe": "MagSafe",
            "usb 3.0": "USB 3.0",
            "usb 2.0": "USB 2.0",
            "usb": "USB",
            "wireless": "Không dây",
            "otg": "OTG",
            "auxiliary": "Âm thanh AUX",
        },
    )
    if connector_names:
        features.append("Kết nối: " + ", ".join(connector_names) + ".")
        if "sạc" in kind.lower() or "cáp" in kind.lower():
            name += " · " + "/".join(connector_names[:2])
    if pack:
        features.append(f"Số lượng ghi trong tên sản phẩm: {pack[1]} chiếc/bộ.")
    # Only translate enumerated attribute values. Do not mine advertising
    # sentences, where a matching word may occur in a negation or comparison.
    source_features = []
    for key in ("Special Feature", "Special features", "Special Features"):
        source_features.extend(re.split(r"[,;]", clean(attributes.get(key))))
    translated = list(
        dict.fromkeys(
            FEATURES[v.strip().lower()] for v in source_features if v.strip().lower() in FEATURES
        )
    )
    features.extend(translated)
    for unit, label in (
        ("mAh", "Dung lượng ghi trong tên sản phẩm"),
        ("W", "Công suất ghi trong tên sản phẩm"),
    ):
        values = list(
            dict.fromkeys(re.findall(r"\b(\d+(?:\.\d+)?\s*" + unit + r")\b", title, re.I))
        )
        if values:
            features.append(label + ": " + ", ".join(values[:4]) + ".")
    if model:
        features.append("Mã mẫu: " + model + ".")
    if item.get("item_id"):
        features.append("Mã sản phẩm: " + item["item_id"] + ".")
    description = kind + (f" của thương hiệu {brand}" if brand else "") + "."
    if devices:
        description += (
            " Thiết bị được nhắc đến trong thông tin nguồn: " + ", ".join(devices[:10]) + "."
        )
    description += " Vui lòng đối chiếu đúng mẫu thiết bị và thông số trước khi chọn mua."
    return {"name": name[:600], "description": description, "features": features}
