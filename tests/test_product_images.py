from django.template.loader import render_to_string
from django.test import SimpleTestCase

from apps.catalog.images import is_placeholder_image
from apps.catalog.models import Product, ProductImage

PLACEHOLDER = "https://m.media-amazon.com/images/I/01RmK+J4pJL._AC_.gif"
PHOTO = "https://m.media-amazon.com/images/I/actual-product.jpg"


class ProductImageDisplayTests(SimpleTestCase):
    def product_with_images(self, *images):
        product = Product(
            pk=1,
            external_item_id="TEST",
            slug="test",
            name="Sản phẩm thử",
            price=99000,
            stock=20,
            is_active=True,
        )
        product._prefetched_objects_cache = {"images": list(images), "reviews": []}
        return product

    def test_known_placeholder_and_resized_encoded_variants_are_filtered(self):
        for url in [
            PLACEHOLDER,
            "https://m.media-amazon.com/images/I/01RmK%2BJ4pJL._AC_SL500_.gif?x=1",
            "https://images-na.ssl-images-amazon.com/images/I/01RmK+J4pJL.gif",
        ]:
            with self.subTest(url=url):
                self.assertTrue(is_placeholder_image(url))
                self.assertEqual(ProductImage(image_url=url).display_url, "")

    def test_real_gifs_and_unrelated_urls_remain_available(self):
        for url in [
            PHOTO,
            "https://m.media-amazon.com/images/I/real-photo.gif",
            "https://example.com/01RmK+J4pJL.gif",
        ]:
            with self.subTest(url=url):
                self.assertFalse(is_placeholder_image(url))
                self.assertEqual(ProductImage(image_url=url).display_url, url)

    def test_local_photo_takes_precedence_over_remote_placeholder(self):
        image = ProductImage(file="products/photo.png", image_url=PLACEHOLDER)
        self.assertEqual(image.display_url, "/media/products/photo.png")

    def test_real_secondary_photo_becomes_card_photo_without_changing_sources(self):
        missing = ProductImage(image_url=PLACEHOLDER, position=0)
        photo = ProductImage(image_url=PHOTO, position=1)
        product = self.product_with_images(missing, photo)
        self.assertEqual(product.display_images, [photo])
        card = render_to_string("catalog/card.html", {"product": product})
        self.assertIn(f'src="{PHOTO}"', card)
        self.assertNotIn(PLACEHOLDER, card)
        self.assertEqual(missing.image_url, PLACEHOLDER)
        self.assertEqual(missing.position, 0)

    def test_missing_and_placeholder_photos_render_accessible_fallback(self):
        for images in [[], [ProductImage(image_url=PLACEHOLDER)]]:
            product = self.product_with_images(*images)
            for template in ["catalog/card.html", "catalog/detail.html"]:
                with self.subTest(images=len(images), template=template):
                    html = render_to_string(template, {"product": product})
                    self.assertIn('aria-label="Chưa có ảnh sản phẩm"', html)
                    self.assertNotIn(PLACEHOLDER, html)
                    self.assertNotIn("data-product-image", html)

    def test_available_photo_keeps_error_fallback_hidden_until_needed(self):
        product = self.product_with_images(ProductImage(image_url=PHOTO))
        html = render_to_string("catalog/card.html", {"product": product})
        self.assertIn("data-product-image", html)
        self.assertIn('loading="lazy"', html)
        self.assertRegex(html, r'aria-label="Chưa có ảnh sản phẩm"\s+hidden')
