from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import Resolver404, resolve, reverse
from django.views.decorators.http import require_GET, require_http_methods

from apps.catalog.models import Product
from apps.common.access import admin_permissions
from apps.common.pagination import page_context
from apps.common.validators import normalize_stored_phone

from .forms import AccountAccessForm, AccountCreationForm, ProfileForm, SignUpForm
from .models import PreferredDevice, Profile, User
from .roles import ADMIN, CUSTOMER
from .services import protected_account, update_account_access


class ShopLoginView(LoginView):
    template_name = "accounts/login.html"

    def get_success_url(self):
        url = super().get_success_url()
        try:
            target = resolve(urlsplit(url).path)
        except Resolver404:
            return url

        # Login redirects with a GET, so return to the page that owns the action.
        if target.url_name not in {"update_cart", "toggle_favorite"}:
            return url
        slug = Product.objects.filter(pk=target.kwargs["product_id"], is_active=True).values_list(
            "slug", flat=True
        ).first()
        if slug is None:
            messages.warning(self.request, "Sản phẩm này hiện không còn mở bán.")
            return reverse("product_list")
        action = "thêm vào giỏ hàng" if target.url_name == "update_cart" else "lưu sản phẩm yêu thích"
        messages.info(self.request, f"Bạn đã đăng nhập. Hãy {action} để tiếp tục.")
        return reverse("product_detail", kwargs={"slug": slug})


@transaction.atomic
def signup(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = SignUpForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        customer, _ = Group.objects.get_or_create(name=CUSTOMER)
        user.groups.add(customer)
        login(request, user)
        messages.success(request, "Tài khoản đã sẵn sàng. Chào mừng bạn!")
        return redirect("home")
    return render(
        request, "accounts/form.html", {"form": form, "title": "Tạo tài khoản", "button": "Đăng ký"}
    )


@login_required
@transaction.atomic
def profile(request):
    stored, _ = Profile.objects.get_or_create(user=request.user)
    initial = {
        field: getattr(request.user, field) for field in ["first_name", "last_name", "email"]
    }
    phone = normalize_stored_phone(stored.phone)
    initial.update(phone=phone or stored.phone, default_address=stored.default_address)
    initial["preferred_devices"] = (
        PreferredDevice.objects.filter(user=request.user)
        .order_by("pk")
        .values_list("phone_model_id", flat=True)
        .first()
    )
    form = ProfileForm(request.POST if request.method == "POST" else None, initial=initial)
    if not form.is_bound and stored.phone and not phone:
        form.fields["phone"].widget.attrs["aria-invalid"] = "true"
    if request.method == "POST" and form.is_valid():
        for field in ["first_name", "last_name", "email"]:
            setattr(request.user, field, form.cleaned_data[field])
        request.user.save(update_fields=["first_name", "last_name", "email"])
        stored.phone, stored.default_address = (
            form.cleaned_data["phone"],
            form.cleaned_data["default_address"],
        )
        stored.save()
        device = form.cleaned_data["preferred_devices"]
        selected = [device] if device else []
        PreferredDevice.objects.filter(user=request.user).exclude(phone_model__in=selected).delete()
        for device in selected:
            PreferredDevice.objects.get_or_create(user=request.user, phone_model=device)
        messages.success(request, "Đã lưu thông tin của bạn.")
        return redirect("profile")
    return render(
        request,
        "accounts/form.html",
        {"form": form, "title": "Thông tin tài khoản", "button": "Lưu thay đổi"},
    )


@admin_permissions("accounts.manage_accounts")
@require_GET
def account_list(request):
    query = request.GET.get("q", "").strip()[:150]
    users = User.objects.prefetch_related("groups", "user_permissions").order_by("username", "pk")
    if query:
        users = users.filter(Q(username__icontains=query) | Q(email__icontains=query))
    context = page_context(request, users, fields=("q",))
    for user in context["page_obj"]:
        user.access_protected = user.pk == request.user.pk or protected_account(user, request.user)
        user.role_label = "Quản trị viên" if user.is_staff else "Khách hàng"
    return render(
        request, "accounts/manage_list.html", {**context, "query": query, "area": "accounts"}
    )


@admin_permissions("accounts.manage_accounts")
@require_http_methods(["GET", "POST"])
def account_access(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    if target.pk == request.user.pk or protected_account(target, request.user):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied("Tài khoản được bảo vệ, không thể thay đổi tại đây.")
    role = ADMIN if target.is_staff else CUSTOMER
    form = AccountAccessForm(
        request.POST if request.method == "POST" else None,
        initial={"is_active": target.is_active, "role": role},
    )
    if request.method == "POST" and form.is_valid():
        try:
            update_account_access(actor=request.user, user_id=target.pk, **form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Đã cập nhật quyền truy cập tài khoản.")
            return redirect("manage_accounts")
    return render(
        request,
        "accounts/manage_access.html",
        {"form": form, "target_user": target, "area": "accounts"},
    )


@admin_permissions("accounts.manage_accounts")
@require_http_methods(["GET", "POST"])
@transaction.atomic
def account_create(request):
    form = AccountCreationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_account_access(
            actor=request.user,
            user_id=user.pk,
            role=form.cleaned_data["role"],
            is_active=form.cleaned_data["is_active"],
        )
        messages.success(request, "Đã tạo tài khoản và phân quyền.")
        return redirect("manage_accounts")
    return render(request, "management/account_create.html", {"form": form, "area": "accounts"})
