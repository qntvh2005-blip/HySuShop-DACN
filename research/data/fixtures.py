"""Tiny, explicitly synthetic cohort for protocol tests; never benchmark evidence."""


def synthetic_records():
    metadata = [
        {
            "parent_asin": f"I{i:02d}",
            "title": f"Phone case {i}",
            "categories": ["Cell Phones & Accessories", "Cases"],
            "description": ["<b>Protective</b> cover"],
            "features": ["Lightweight"],
            "details": {"Brand": "Fixture"},
            "price": "9.99",
        }
        for i in range(12)
    ]
    reviews = []
    for u in range(10):
        for offset in range(10):
            i = (u + offset) % 12
            reviews.append(
                {
                    "user_id": f"u{u:02d}",
                    "parent_asin": f"I{i:02d}",
                    "rating": 5.0,
                    "timestamp": 1000 + offset * 100 + u,
                }
            )
        reviews.append(
            {
                "user_id": f"u{u:02d}",
                "parent_asin": f"I{(u + 10) % 12:02d}",
                "rating": 2,
                "timestamp": 1500 + u,
            }
        )
    # Latest low rating supersedes an old positive; it must remain in seen history.
    reviews.append({"user_id": "u00", "parent_asin": "I00", "rating": 1, "timestamp": 1650})
    # An ambiguous dev/test timestamp boundary excludes this user only after catalog freeze.
    for i in range(12):
        reviews.append(
            {
                "user_id": "ambiguous",
                "parent_asin": f"I{i:02d}",
                "rating": 5,
                "timestamp": 2000 + min(i, 10) * 100,
            }
        )
    metadata.append(
        {
            "parent_asin": "PHONE",
            "title": "Unlocked smartphone",
            "categories": ["Cell Phones & Accessories", "Cell Phones"],
        }
    )
    reviews.append({"user_id": "outside", "parent_asin": "PHONE", "rating": 5, "timestamp": 1000})
    reviews.append({"user_id": "", "parent_asin": "I00", "rating": 6, "timestamp": 0})
    return metadata, reviews
