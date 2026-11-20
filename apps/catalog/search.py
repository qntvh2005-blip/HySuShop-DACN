import unicodedata


def normalize_search(value):
    value = str(value).casefold().replace("đ", "d")
    return " ".join(
        "".join(
            c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)
        ).split()
    )


def search_document(product):
    source = product.source_metadata or {}
    # Generic labels such as "Màu sắc" must not make every colored product
    # match "sac". Index attribute values and omit the repeated buying advice.
    features = [str(value).split(":", 1)[-1] for value in product.features]
    description = product.description.split("Vui lòng đối chiếu", 1)[0]
    parts = [
        product.name,
        description,
        product.external_item_id,
        source.get("title", ""),
        *features,
        *source.get("attributes", {}).values(),
    ]
    return normalize_search(" ".join(str(part) for part in parts))
