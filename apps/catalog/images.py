"""Presentation rules for product photos; source metadata stays unchanged."""

from io import BytesIO
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps


MAX_PRODUCT_IMAGE_BYTES = 5 * 1024 * 1024


def prepare_product_image(upload):
    if upload.size > MAX_PRODUCT_IMAGE_BYTES:
        raise ValidationError("Vui lòng chọn ảnh tối đa 5 MB.")
    try:
        with Image.open(upload, formats=("JPEG", "PNG", "WEBP")) as source:
            if source.width * source.height > 20_000_000:
                raise ValidationError("Ảnh quá lớn. Vui lòng chọn ảnh dưới 20 megapixel.")
            image = ImageOps.exif_transpose(source)
            image.thumbnail((1600, 1600))
            mode = "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
            output = BytesIO()
            image.convert(mode).save(output, format="WEBP", quality=88)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValidationError("Vui lòng chọn ảnh JPG, PNG hoặc WebP hợp lệ.") from error
    return ContentFile(output.getvalue(), name=f"{uuid4().hex}.webp")


def is_placeholder_image(url):
    """Amazon's known 'No image available' asset is not a product photo.

    Check the exact asset ID rather than rejecting GIFs or small photographs.
    Resized versions of this same asset must also be excluded.
    """
    if not url:
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if not (host.endswith(".media-amazon.com") or host.endswith(".ssl-images-amazon.com")):
        return False
    filename = unquote(parsed.path.rsplit("/", 1)[-1])
    return filename.startswith("01RmK+J4pJL.")
