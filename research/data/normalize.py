import html
import json
import math
import re
import unicodedata
from decimal import Decimal, InvalidOperation

from research.data.io import digest


def clean_text(value):
    if value is None:
        return ""
    value = re.sub(r"<[^>]*>", " ", str(value))
    return " ".join(unicodedata.normalize("NFKC", html.unescape(value)).split())


def text_list(value):
    if isinstance(value, list):
        return [item for part in value for item in text_list(part)]
    value = clean_text(value)
    return [value] if value else []


class AccessoryFilter:
    def __init__(self, rules):
        self.rules = rules
        self.patterns = {
            key: [re.compile(pattern, re.I) for pattern in rules[key]]
            for key in [
                "category_allow_patterns",
                "category_deny_leaf_patterns",
                "title_allow_patterns",
                "title_deny_patterns",
                "category_deny_patterns",
            ]
        }

    def decide(self, record):
        title = clean_text(record.get("title"))
        if (
            not isinstance(record.get("parent_asin"), str)
            or not record["parent_asin"].strip()
            or not title
        ):
            return False, "missing_id_or_title"
        if record["parent_asin"].strip() in self.rules.get("reviewed_exclusions", {}):
            return False, "reviewed_out_of_scope"
        if any(
            re.search(pattern, title, re.I)
            for pattern in self.rules.get("non_phone_title_patterns", [])
        ):
            phone_evidence = any(
                re.search(pattern, title, re.I)
                for pattern in self.rules.get("phone_evidence_patterns", [])
            )
            if not phone_evidence:
                return False, "non_phone_accessory_title"
        categories = text_list(record.get("categories", []))
        if any(
            pattern.search(category)
            for category in categories
            for pattern in self.patterns["category_deny_patterns"]
        ):
            return False, "denied_category_branch"
        leaf = categories[-1] if categories else ""
        if any(pattern.search(leaf) for pattern in self.patterns["category_deny_leaf_patterns"]):
            return False, "denied_leaf_category"
        if any(pattern.search(title) for pattern in self.patterns["title_deny_patterns"]):
            return False, "denied_title"
        # The root 'Cell Phones & Accessories' is not an accessory subtype.
        subcategories = " ".join(
            c
            for c in categories
            if c.lower() not in {"cell phones & accessories", "cell phones and accessories"}
        )
        if any(
            pattern.search(subcategories) for pattern in self.patterns["category_allow_patterns"]
        ):
            return True, "allowed_category"
        if any(pattern.search(title) for pattern in self.patterns["title_allow_patterns"]):
            return True, "allowed_title"
        return False, "no_accessory_evidence"


def normalize_metadata(record):
    details = record.get("details") or {}
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except ValueError:
            details = {}
    if not isinstance(details, dict):
        details = {}
    selected = {
        clean_text(k): clean_text(v)
        for k, v in details.items()
        if re.search(
            r"brand|material|color|connector|compatible|connectivity|model|form factor|special feature",
            str(k),
            re.I,
        )
    }
    images = record.get("images") or []
    if isinstance(images, dict):
        images = [{"large": value} for value in images.get("large", []) if value]
    image_urls = []
    if isinstance(images, list):
        for image in images:
            if isinstance(image, dict):
                url = image.get("large") or image.get("hi_res") or image.get("thumb")
                if isinstance(url, str) and url.startswith("https://") and url not in image_urls:
                    image_urls.append(url)
    try:
        price = Decimal(str(record.get("price")))
        source_price = str(price) if price.is_finite() and price >= 0 else None
    except (InvalidOperation, ValueError):
        source_price = None
    result = {
        "item_id": record["parent_asin"].strip(),
        "title": clean_text(record["title"]),
        "categories": text_list(record.get("categories", [])),
        "description": text_list(record.get("description", [])),
        "features": text_list(record.get("features", [])),
        "attributes": dict(sorted(selected.items())),
        "store": clean_text(record.get("store")),
        "image_urls": image_urls,
        "source_price": source_price,
        "source_currency": "USD",
        "source_dataset": "Amazon Reviews 2023",
    }
    result["content_text"] = " ".join(
        [
            result["title"],
            *result["categories"],
            *result["description"],
            *result["features"],
            *(f"{k} {v}" for k, v in result["attributes"].items()),
        ]
    )
    return result


def normalize_review(record):
    user = record.get("user_id")
    item = record.get("parent_asin")
    if (
        not isinstance(user, str)
        or not user.strip()
        or not isinstance(item, str)
        or not item.strip()
    ):
        return None
    try:
        if isinstance(record.get("rating"), bool):
            return None
        rating = float(record["rating"])
        value = record.get("timestamp", record.get("sort_timestamp"))
        if isinstance(value, bool):
            return None
        timestamp = int(value)
        if (
            str(timestamp) != str(value)
            or timestamp <= 0
            or not math.isfinite(rating)
            or not 1 <= rating <= 5
        ):
            return None
    except (KeyError, ValueError, TypeError, OverflowError):
        return None
    normalized = {
        "user_id": user.strip(),
        "item_id": item.strip(),
        "rating": rating,
        "timestamp": timestamp,
    }
    normalized["tie_hash"] = digest(normalized)
    return normalized
