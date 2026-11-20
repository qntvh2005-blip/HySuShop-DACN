from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from apps.accounts import views as accounts
from apps.cart import views as cart
from apps.catalog import views as catalog
from apps.common import management
from apps.common.views import dashboard
from apps.interactions import views as interactions
from apps.orders import views as orders

urlpatterns = [
    path("", catalog.home, name="home"),
    path("san-pham/", catalog.product_list, name="product_list"),
    path("san-pham/<slug:slug>/", catalog.product_detail, name="product_detail"),
    path("tai-khoan/dang-ky/", accounts.signup, name="signup"),
    path(
        "tai-khoan/dang-nhap/",
        accounts.ShopLoginView.as_view(),
        name="login",
    ),
    path("tai-khoan/dang-xuat/", auth_views.LogoutView.as_view(), name="logout"),
    path("tai-khoan/", accounts.profile, name="profile"),
    path("tai-khoan/lich-su/", interactions.history, name="interaction_history"),
    path(
        "tai-khoan/doi-mat-khau/",
        auth_views.PasswordChangeView.as_view(
            template_name="accounts/form.html",
            extra_context={"title": "Đổi mật khẩu", "button": "Lưu mật khẩu"},
            success_url="/tai-khoan/",
        ),
        name="password_change",
    ),
    path("yeu-thich/", interactions.favorites, name="favorites"),
    path("yeu-thich/<int:product_id>/", interactions.toggle_favorite, name="toggle_favorite"),
    path("danh-gia/<int:product_id>/", interactions.review_product, name="review_product"),
    path("gio-hang/", cart.cart_detail, name="cart"),
    path("gio-hang/<int:product_id>/", cart.update_cart, name="update_cart"),
    path("dat-hang/", orders.checkout_view, name="checkout"),
    path("don-hang/", orders.order_list, name="orders"),
    path("don-hang/<uuid:number>/", orders.order_detail, name="order_detail"),
    path("don-hang/<uuid:number>/huy/", orders.cancel_order, name="cancel_order"),
    path("don-hang/<uuid:number>/anh-tra-hang/", orders.return_evidence, name="return_evidence"),
    path("admin/", RedirectView.as_view(pattern_name="dashboard", permanent=False)),
    path("quan-ly/", dashboard, name="dashboard"),
    path("quan-ly/tai-khoan/", accounts.account_list, name="manage_accounts"),
    path("quan-ly/tai-khoan/<int:user_id>/", accounts.account_access, name="manage_account_access"),
    path("quan-ly/tai-khoan/them/", accounts.account_create, name="manage_account_create"),
    path("quan-ly/san-pham/", management.products, name="manage_products"),
    path("quan-ly/san-pham/them/", management.product_edit, name="manage_product_create"),
    path("quan-ly/san-pham/<int:product_id>/", management.product_edit, name="manage_product_edit"),
    path(
        "quan-ly/san-pham/<int:product_id>/xoa/",
        management.product_delete,
        name="manage_product_delete",
    ),
    path("quan-ly/san-pham/<int:product_id>/anh/", management.image_add, name="manage_image_add"),
    path(
        "quan-ly/san-pham/<int:product_id>/anh/<int:image_id>/xoa/",
        management.image_delete,
        name="manage_image_delete",
    ),
    path(
        "quan-ly/san-pham/<int:product_id>/tuong-thich/",
        management.compatibility_save,
        name="manage_compatibility_save",
    ),
    path("quan-ly/danh-sach/<slug:kind>/", management.taxonomy_list, name="manage_taxonomy"),
    path(
        "quan-ly/danh-sach/<slug:kind>/them/",
        management.taxonomy_edit,
        name="manage_taxonomy_create",
    ),
    path(
        "quan-ly/danh-sach/<slug:kind>/<int:object_id>/",
        management.taxonomy_edit,
        name="manage_taxonomy_edit",
    ),
    path(
        "quan-ly/danh-sach/<slug:kind>/<int:object_id>/xoa/",
        management.taxonomy_delete,
        name="manage_taxonomy_delete",
    ),
    path("quan-ly/don-hang/", management.orders, name="manage_orders"),
    path("quan-ly/don-hang/<int:order_id>/", management.order_detail, name="manage_order_detail"),
    path(
        "quan-ly/don-hang/<int:order_id>/trang-thai/",
        management.order_transition,
        name="manage_order_transition",
    ),
    path("quan-ly/goi-y/", management.recommendations, name="manage_recommendations"),
    path("quan-ly/goi-y/<int:log_id>/", management.recommendation_detail, name="manage_recommendation_detail"),
    path("quan-ly/nhat-ky/", management.activity, name="manage_activity"),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
