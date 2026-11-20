import uuid

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import Profile
from apps.cart.models import CartItem
from apps.cart.services import set_quantity
from apps.catalog.models import (
    Brand,
    Category,
    PhoneModel,
    Product,
    ProductCategory,
    ProductCompatibility,
)
from apps.interactions.models import Favorite, UserInteraction
from apps.orders.models import Order


class ShoppingViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="shopper", password="Strong-password-927!"
        )
        cls.product = Product.objects.create(
            external_item_id="CASE",
            name="Ốp iPhone",
            slug="case-iphone",
            price=99000,
            stock=3,
            is_active=True,
        )
        cls.inactive = Product.objects.create(
            external_item_id="HIDDEN",
            name="Hidden",
            slug="hidden",
            price=50000,
            stock=3,
            is_active=False,
        )
        category = Category.objects.create(name="Ốp lưng", slug="cases")
        ProductCategory.objects.create(product=cls.product, category=category)

    def test_public_catalog_and_detail_track_view(self):
        self.assertContains(self.client.get(reverse("home")), "HySuShop")
        response = self.client.get(reverse("product_list"), {"q": "iPhone", "sort": "price_asc"})
        self.assertContains(response, "Ốp iPhone")
        self.assertNotContains(response, "Hidden")
        self.assertEqual(
            self.client.get(reverse("product_detail", args=["hidden"])).status_code, 404
        )
        detail = self.client.get(reverse("product_detail", args=[self.product.slug]))
        self.assertContains(detail, "Thêm vào giỏ hàng")
        self.assertTrue(
            UserInteraction.objects.filter(
                product=self.product, event_type="view", user__isnull=True
            ).exists()
        )

    def test_guest_product_actions_return_to_detail_after_login(self):
        product_url = reverse("product_detail", args=[self.product.slug])
        for route, payload in [
            ("update_cart", {"mode": "add", "quantity": "2"}),
            ("toggle_favorite", {}),
        ]:
            with self.subTest(route=route):
                self.client.logout()
                action_url = reverse(route, args=[self.product.pk])
                login_page = self.client.post(action_url, payload, follow=True)
                self.assertEqual(login_page.context["next"], action_url)
                logged_in = self.client.post(
                    reverse("login"),
                    {
                        "username": self.user.username,
                        "password": "Strong-password-927!",
                        "next": login_page.context["next"],
                    },
                )
                self.assertRedirects(logged_in, product_url)
                self.assertFalse(CartItem.objects.exists())
                self.assertFalse(Favorite.objects.exists())
                self.assertEqual(self.client.get(action_url).status_code, 405)

        self.assertRedirects(
            self.client.post(
                reverse("update_cart", args=[self.product.pk]), {"mode": "add", "quantity": "2"}
            ),
            reverse("cart"),
        )
        self.assertEqual(CartItem.objects.get().quantity, 2)

    def test_cart_and_checkout_explain_stale_stock_and_allow_removal(self):
        self.client.force_login(self.user)
        set_quantity(user=self.user, product_id=self.product.pk, quantity=2)
        Product.objects.filter(pk=self.product.pk).update(stock=1)
        cart = self.client.get(reverse("cart"))
        checkout = self.client.get(reverse("checkout"))
        for response in (cart, checkout):
            self.assertContains(response, "Số lượng vượt quá tồn kho")
            self.assertFalse(response.context["can_checkout"])
            self.assertEqual(response.context["subtotal"], 0)
        self.assertNotContains(checkout, "Xác nhận đặt hàng")
        self.client.post(
            reverse("update_cart", args=[self.product.pk]), {"mode": "remove", "quantity": "2"}
        )
        self.assertContains(self.client.get(reverse("cart")), "Giỏ hàng của bạn đang trống")

    def test_cart_quantity_buttons_update_totals_and_recover_from_lower_stock(self):
        self.client.force_login(self.user)
        set_quantity(user=self.user, product_id=self.product.pk, quantity=2)
        url = reverse("update_cart", args=[self.product.pk])
        cart = self.client.get(reverse("cart"))
        self.assertContains(cart, 'aria-label="Giảm số lượng"')
        self.assertContains(cart, 'aria-label="Tăng số lượng"')
        self.assertNotContains(cart, "Cập nhật</button>")

        increased = self.client.post(url, {"quantity": "3"}, follow=True)
        self.assertEqual(increased.context["lines"][0].quantity, 3)
        self.assertEqual(increased.context["subtotal"], 297000)
        self.assertContains(
            increased,
            '<button type="submit" name="quantity" value="4" aria-label="Tăng số lượng" disabled>+</button>',
            html=True,
        )

        Product.objects.filter(pk=self.product.pk).update(stock=1)
        cart = self.client.get(reverse("cart"))
        self.assertContains(
            cart,
            '<button type="submit" name="quantity" value="1" aria-label="Giảm số lượng">−</button>',
            html=True,
        )
        decreased = self.client.post(url, {"quantity": "1"}, follow=True)
        self.assertEqual(decreased.context["subtotal"], 99000)
        self.assertTrue(decreased.context["can_checkout"])
        self.assertContains(
            decreased,
            '<button type="submit" name="quantity" value="0" aria-label="Giảm số lượng" disabled>−</button>',
            html=True,
        )

    def test_bad_filter_does_not_crash_and_device_must_be_verified(self):
        self.assertEqual(
            self.client.get(reverse("product_list"), {"min_price": "invalid"}).status_code, 200
        )
        phone = PhoneModel.objects.create(manufacturer="Apple", name="iPhone", slug="iphone")
        mapping = ProductCompatibility.objects.create(product=self.product, phone_model=phone)
        self.assertNotContains(
            self.client.get(reverse("product_list"), {"phone": phone.pk}), "Ốp iPhone"
        )
        mapping.verified = True
        mapping.save()
        self.assertContains(
            self.client.get(reverse("product_list"), {"phone": phone.pk}), "Ốp iPhone"
        )

    def test_catalog_choices_stay_available_when_combination_has_no_matches(self):
        case_category = self.product.categories.get()
        charger_category = Category.objects.create(name="Sạc", slug="charger")
        apple = PhoneModel.objects.create(manufacturer="Apple", name="iPhone", slug="iphone")
        pixel = PhoneModel.objects.create(manufacturer="Google", name="Pixel", slug="pixel")
        brand = Brand.objects.create(name="Anker", slug="anker")
        charger = Product.objects.create(
            external_item_id="CHARGER",
            name="Củ sạc",
            slug="charger",
            brand=brand,
            price=300000,
            stock=1,
            is_active=True,
        )
        ProductCategory.objects.create(product=charger, category=charger_category)
        ProductCompatibility.objects.create(product=self.product, phone_model=apple, verified=True)
        ProductCompatibility.objects.create(product=charger, phone_model=pixel, verified=True)
        ProductCompatibility.objects.create(product=self.product, phone_model=pixel, verified=False)

        url = reverse("product_list")
        initial = self.client.get(url)
        selected = self.client.get(url, {"category": case_category.pk})
        self.assertEqual(list(selected.context["page_obj"]), [self.product])
        unmatched = self.client.get(url, {"category": case_category.pk, "phone": pixel.pk})
        self.assertEqual(unmatched.context["page_obj"].paginator.count, 0)
        self.assertContains(unmatched, "Chưa tìm thấy sản phẩm")
        for field in ("category", "brand", "phone", "price_range"):
            initial_options = list(initial.context["form"].fields[field].choices)
            for response in (selected, unmatched):
                self.assertEqual(list(response.context["form"].fields[field].choices), initial_options)
        self.assertEqual(unmatched.context["form"]["phone"].value(), str(pixel.pk))

    def test_price_ranges_cover_boundary_prices_without_overlap(self):
        prices = ["99999.99", "100000", "299999.99", "300000", "500000"]
        products = [
            Product.objects.create(
                external_item_id=f"PRICE{i}",
                name=f"Sản phẩm giá {i}",
                slug=f"price-{i}",
                price=price,
                stock=1,
                is_active=True,
            )
            for i, price in enumerate(prices)
        ]
        expected = {
            "under_100": {self.product.pk, products[0].pk},
            "100_300": {products[1].pk, products[2].pk},
            "from_300": {products[3].pk, products[4].pk},
        }
        for selected, ids in expected.items():
            response = self.client.get(reverse("product_list"), {"price_range": selected})
            self.assertEqual({p.pk for p in response.context["page_obj"]}, ids)
            self.assertNotContains(response, 'name="min_price"')
            self.assertNotContains(response, 'name="max_price"')
        invalid = self.client.get(reverse("product_list"), {"price_range": "tampered"})
        self.assertEqual(invalid.context["page_obj"].paginator.count, 0)
        self.assertTrue(invalid.context["form"].errors)

    def test_price_and_brand_filter_persist_across_pages(self):
        brand = Brand.objects.create(name="Anker", slug="anker")
        for i in range(25):
            Product.objects.create(
                external_item_id=f"BRAND{i}",
                name=f"Ốp mẫu {i}",
                slug=f"brand-{i}",
                brand=brand,
                price=199000,
                stock=1,
                is_active=True,
            )
        response = self.client.get(
            reverse("product_list"),
            {"q": "ốp", "brand": brand.pk, "price_range": "100_300", "page": 2},
        )
        self.assertEqual(response.context["page_obj"].paginator.count, 25)
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 3)
        self.assertEqual(len(response.context["page_obj"]), 9)
        last = self.client.get(
            reverse("product_list"),
            {"q": "ốp", "brand": brand.pk, "price_range": "100_300", "page": 3},
        )
        self.assertEqual(len(last.context["page_obj"]), 7)
        self.assertContains(response, 'name="brand"')
        self.assertNotContains(response, "Bộ lọc nâng cao")
        self.assertIn("price_range=100_300", response.context["query_string"])
        self.assertIn(f"brand={brand.pk}", response.context["query_string"])
        self.assertNotIn("page=", response.context["query_string"])
        self.assertContains(response, "&amp;page=1")
        default = self.client.get(reverse("product_list"))
        self.assertNotContains(default, "filter-advanced")

    def test_featured_brands_and_other_group_keep_every_product_accessible(self):
        anker = Brand.objects.create(name="Anker", slug="anker")
        duplicate = Brand.objects.create(name="ANKER", slug="anker-alias")
        other = Brand.objects.create(name="Local Brand", slug="local-brand")
        products = []
        for i, brand in enumerate([anker, duplicate, other]):
            products.append(
                Product.objects.create(
                    external_item_id=f"CHOICE{i}",
                    name=f"Sản phẩm hãng {i}",
                    slug=f"choice-{i}",
                    brand=brand,
                    price=149000,
                    stock=1,
                    is_active=True,
                )
            )
        default = self.client.get(reverse("product_list"))
        choices = list(default.context["form"].fields["brand"].choices)
        self.assertEqual(
            choices,
            [("", "Tất cả thương hiệu"), (str(anker.pk), "Anker"), ("other", "Thương hiệu khác")],
        )
        selected = self.client.get(reverse("product_list"), {"brand": anker.pk})
        self.assertEqual(
            {p.pk for p in selected.context["page_obj"]}, {products[0].pk, products[1].pk}
        )
        remaining = self.client.get(reverse("product_list"), {"brand": "other"})
        self.assertEqual(
            {p.pk for p in remaining.context["page_obj"]}, {self.product.pk, products[2].pk}
        )
        self.assertEqual(default.context["page_obj"].paginator.count, 4)
        self.assertEqual(Brand.objects.count(), 3)

    def test_device_menu_lists_all_full_names_and_preserves_selected_device(self):
        phones = []
        for manufacturer, prefix in [
            ("Apple", "iPhone"),
            ("Samsung", "Galaxy"),
            ("Google", "Pixel"),
        ]:
            for i in range(8):
                phone = PhoneModel.objects.create(
                    manufacturer=manufacturer, name=f"{prefix} {i}", slug=f"{prefix.lower()}-{i}"
                )
                ProductCompatibility.objects.create(
                    product=self.product, phone_model=phone, verified=True
                )
                phones.append(phone)
        response = self.client.get(reverse("product_list"))
        choices = list(response.context["form"].fields["phone"].choices)
        ids = {int(str(value)) for value, label in choices if value}
        self.assertEqual(len(ids), 24)
        self.assertEqual(
            {str(value): label for value, label in choices if value},
            {str(phone.pk): str(phone) for phone in phones},
        )
        selected_phone = phones[-1]
        selected = self.client.get(reverse("product_list"), {"phone": selected_phone.pk})
        self.assertEqual(selected.context["page_obj"].paginator.count, 1)
        self.assertIn(
            selected_phone.pk,
            {
                int(str(value))
                for value, label in selected.context["form"].fields["phone"].choices
                if value
            },
        )
        self.assertEqual(
            ProductCompatibility.objects.filter(product=self.product, verified=True).count(), 24
        )

    def test_full_customer_purchase_retry_and_order_ownership(self):
        photo_url = "https://example.com/cart-photo.jpg"
        self.product.images.create(image_url=photo_url)
        Profile.objects.update_or_create(
            user=self.user, defaults={"phone": "+84 (90) 123-4567"}
        )
        self.client.force_login(self.user)
        self.assertRedirects(
            self.client.post(reverse("update_cart", args=[self.product.pk]), {"quantity": "2"}),
            reverse("cart"),
        )
        cart = self.client.get(reverse("cart"))
        self.assertContains(cart, "198.000")
        self.assertContains(cart, f'src="{photo_url}"')
        checkout_page = self.client.get(reverse("checkout"))
        self.assertContains(checkout_page, f'src="{photo_url}"')
        phone_html = str(checkout_page.context["form"]["phone"])
        self.assertIn('value="0901234567"', phone_html)
        self.assertIn('maxlength="10"', phone_html)
        self.assertIn('pattern="0[35789][0-9]{8}"', phone_html)
        payload = {
            "checkout_key": str(uuid.uuid4()),
            "recipient_name": "Khách hàng",
            "phone": "0900000000",
            "address": "TP.HCM",
            "payment_method": "cod",
        }
        invalid = self.client.post(reverse("checkout"), {**payload, "phone": "1045622622"})
        self.assertFormError(
            invalid.context["form"],
            "phone",
            "Nhập 10 chữ số, bắt đầu bằng 03, 05, 07, 08 hoặc 09.",
        )
        self.assertIn('aria-invalid="true"', str(invalid.context["form"]["phone"]))
        self.assertFalse(Order.objects.exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)
        self.assertContains(self.client.get(reverse("cart")), "198.000")
        response = self.client.post(reverse("checkout"), payload)
        order = Order.objects.get(user=self.user)
        self.assertRedirects(response, reverse("order_detail", args=[order.number]))
        self.client.post(reverse("checkout"), payload)
        self.assertEqual(Order.objects.count(), 1)
        orders = self.client.get(reverse("orders"))
        self.assertContains(orders, "Chờ xác nhận")
        self.assertContains(orders, self.product.name)
        self.assertContains(orders, f'src="{photo_url}"')
        self.assertNotContains(orders, "Mã đơn")
        self.client.logout()
        other = get_user_model().objects.create_user(username="intruder")
        self.client.force_login(other)
        self.assertEqual(
            self.client.get(reverse("order_detail", args=[order.number])).status_code, 404
        )
        self.assertEqual(
            self.client.post(reverse("cancel_order", args=[order.number])).status_code, 404
        )
        self.client.force_login(self.user)
        self.assertRedirects(
            self.client.post(reverse("cancel_order", args=[order.number])),
            reverse("order_detail", args=[order.number]),
        )
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)

    def test_favorite_requires_post_and_csrf(self):
        self.client.force_login(self.user)
        path = reverse("toggle_favorite", args=[self.product.pk])
        self.assertEqual(self.client.get(path).status_code, 405)
        self.client.post(path)
        self.assertTrue(Favorite.objects.filter(user=self.user, product=self.product).exists())
        self.assertContains(self.client.get(reverse("favorites")), "Ốp iPhone")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(path).status_code, 403)

    def test_signup_cannot_inject_staff_privileges(self):
        response = self.client.post(
            reverse("signup"),
            {
                "username": "new-user",
                "email": "new@example.test",
                "password1": "Strong-password-927!",
                "password2": "Strong-password-927!",
                "is_staff": "true",
                "is_superuser": "true",
            },
        )
        self.assertRedirects(response, reverse("home"))
        user = get_user_model().objects.get(username="new-user")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
