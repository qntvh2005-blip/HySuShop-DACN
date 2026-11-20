from django.db import models
from django.db.models import Q

from apps.common.models import TimestampedModel


class Category(models.Model):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=180, unique=True)

    def __str__(self):
        return self.name


class Brand(models.Model):
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=180, unique=True)

    def __str__(self):
        return self.name


class Product(TimestampedModel):
    external_item_id = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=600)
    slug = models.SlugField(max_length=240, unique=True)
    brand = models.ForeignKey(Brand, null=True, blank=True, on_delete=models.SET_NULL)
    categories = models.ManyToManyField(
        Category, through="ProductCategory", related_name="products"
    )
    description = models.TextField(blank=True)
    features = models.JSONField(default=list, blank=True)
    source_metadata = models.JSONField(default=dict, blank=True)
    search_text = models.TextField(blank=True, default="", editable=False)
    price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default="VND")
    price_source = models.CharField(max_length=50, blank=True)
    stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=False)
    is_universal_accessory = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(price__isnull=True) | Q(price__gte=0), name="product_price_nonnegative"
            ),
            models.CheckConstraint(
                condition=Q(is_active=False) | Q(price__isnull=False),
                name="active_product_requires_price",
            ),
            models.CheckConstraint(
                condition=~Q(external_item_id=""), name="product_external_id_not_empty"
            ),
        ]
        indexes = [models.Index(fields=["is_active", "price"])]

    def __str__(self):
        return self.name

    @property
    def display_images(self):
        return [image for image in self.images.all() if image.display_url]

    def save(self, *args, **kwargs):
        from .search import search_document

        fields = kwargs.get("update_fields")
        if fields is None or set(fields) & {
            "name",
            "description",
            "features",
            "source_metadata",
            "external_item_id",
        }:
            self.search_text = search_document(self)
            if fields is not None:
                kwargs["update_fields"] = set(fields) | {"search_text"}
        return super().save(*args, **kwargs)


class ProductCategory(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["product", "category"], name="unique_product_category")
        ]


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image_url = models.URLField(max_length=2000, blank=True)
    file = models.FileField(upload_to="products/", blank=True)
    position = models.PositiveIntegerField(default=0)
    alt = models.CharField(max_length=300, blank=True)

    @property
    def display_url(self):
        from .images import is_placeholder_image

        if self.file:
            return self.file.url
        return "" if is_placeholder_image(self.image_url) else self.image_url

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "position"], name="unique_product_image_position"
            ),
            models.CheckConstraint(
                condition=~Q(image_url="") | ~Q(file=""), name="product_image_has_source"
            ),
        ]


class PhoneModel(models.Model):
    manufacturer = models.CharField(max_length=100)
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=200, unique=True)

    def __str__(self):
        if self.name.casefold().startswith(f"{self.manufacturer.casefold()} "):
            return self.name
        return f"{self.manufacturer} {self.name}"


class ProductCompatibility(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual", "Nhập thủ công"
        METADATA = "metadata", "Metadata"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="compatibilities")
    phone_model = models.ForeignKey(PhoneModel, on_delete=models.CASCADE)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    verified = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["product", "phone_model"], name="unique_product_compatibility"
            )
        ]
