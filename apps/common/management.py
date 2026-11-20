import uuid

from django.contrib import messages
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.models import PreferredDevice
from apps.catalog.filtering import search_products
from apps.catalog.models import (
    Brand,
    Category,
    PhoneModel,
    Product,
    ProductCategory,
    ProductCompatibility,
    ProductImage,
)
from apps.orders.models import Order, OrderItem, OrderReturn
from apps.orders.services import transition_order
from apps.recommendations.models import RecommendationLog

from .access import admin_permissions
from .management_forms import (
    BrandEditor,
    CategoryEditor,
    CompatibilityForm,
    ImageForm,
    OrderTransitionForm,
    PhoneEditor,
    ProductEditor,
)
from .pagination import page_context


def audit(actor, obj, text, flag=CHANGE):
    LogEntry.objects.create(
        user=actor,
        content_type=ContentType.objects.get_for_model(obj),
        object_id=str(obj.pk),
        object_repr=str(obj)[:200],
        action_flag=flag,
        change_message=text,
    )


@admin_permissions("catalog.view_product")
@require_GET
def products(request):
    query = request.GET.get("q", "").strip()[:200]
    state = request.GET.get("state", "active")
    rows = (
        Product.objects.select_related("brand")
        .prefetch_related("images", "categories")
        .order_by("-updated_at", "pk")
    )
    if query:
        rows = search_products(rows, query).distinct()
    if state == "active":
        rows = rows.filter(is_active=True)
    elif state == "archived":
        rows = rows.filter(is_active=False)
    elif state == "low":
        rows = rows.filter(is_active=True, stock__lt=5)
    elif state != "all":
        rows = rows.none()
    return render(
        request,
        "management/products.html",
        {
            **page_context(request, rows),
            "area": "products",
            "query": query,
            "state": state,
            **Product.objects.aggregate(
                active_count=Count("pk", filter=Q(is_active=True)),
                archived_count=Count("pk", filter=Q(is_active=False)),
            ),
        },
    )


@admin_permissions("catalog.view_product")
@require_http_methods(["GET", "POST"])
@transaction.atomic
def product_edit(request, product_id=None):
    editing = product_id is not None
    action = "change" if editing else "add"
    if not request.user.has_perms(
        [f"catalog.{action}_product", f"catalog.{action}_productcategory"]
    ):
        raise PermissionDenied("Bạn không có quyền chỉnh sửa sản phẩm.")
    product = (
        get_object_or_404(Product.objects.select_for_update(), pk=product_id)
        if editing
        else Product()
    )
    form = ProductEditor(request.POST if request.method == "POST" else None, instance=product)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        if not editing:
            saved.slug = (slugify(saved.name)[:180] or "san-pham") + "-" + uuid.uuid4().hex[:12]
        saved.currency = "VND"
        saved.features = [
            line.strip() for line in form.cleaned_data["feature_lines"].splitlines() if line.strip()
        ]
        if "price" in form.changed_data:
            saved.price_source = "manual_demo" if saved.price is not None else ""
        saved.save()
        selected = form.cleaned_data["categories"]
        ProductCategory.objects.filter(product=saved).exclude(category__in=selected).delete()
        for category in selected:
            ProductCategory.objects.get_or_create(product=saved, category=category)
        audit(
            request.user,
            saved,
            "Cập nhật nội dung và thông tin bán hàng."
            if editing
            else "Thêm sản phẩm thủ công; không đưa vào tập thực nghiệm.",
            CHANGE if editing else ADDITION,
        )
        messages.success(request, "Đã lưu sản phẩm.")
        return redirect("manage_product_edit", product_id=saved.pk)
    return render(
        request,
        "management/product_form.html",
        {
            "form": form,
            "product": product,
            "editing": editing,
            "area": "products",
            "image_form": ImageForm(),
            "compatibility_form": CompatibilityForm(product=product if editing else None),
            "images": product.images.all() if editing else [],
            "compatibilities": product.compatibilities.select_related("phone_model").order_by(
                "phone_model__manufacturer", "phone_model__name"
            )
            if editing
            else [],
        },
    )


@admin_permissions("catalog.delete_product")
@require_POST
@transaction.atomic
def product_delete(request, product_id):
    product = get_object_or_404(Product.objects.select_for_update(), pk=product_id)
    if product.source_metadata.get("dataset_manifest_sha256"):
        raise PermissionDenied(
            "Sản phẩm nghiên cứu được bảo vệ. Có thể chuyển sang ngừng bán thay vì xóa."
        )
    files = [image.file for image in product.images.exclude(file="")]
    try:
        with transaction.atomic():
            audit(request.user, product, "Xóa sản phẩm thủ công.", DELETION)
            product.delete()
    except ProtectedError:
        messages.error(
            request, "Sản phẩm đã có lịch sử giao dịch hoặc tương tác. Hãy chuyển sang ngừng bán."
        )
        return redirect("manage_product_edit", product_id=product_id)
    for file in files:
        schedule_product_file_cleanup(file)
    messages.success(request, "Đã xóa sản phẩm.")
    return redirect("manage_products")


@admin_permissions("catalog.change_product", "catalog.add_productimage")
@require_POST
def image_add(request, product_id):
    form = ImageForm(request.POST, request.FILES)
    if not form.is_valid():
        get_object_or_404(Product, pk=product_id)
        messages.error(
            request,
            "Chưa thêm được ảnh. "
            + " ".join(str(error) for errors in form.errors.values() for error in errors),
        )
        return redirect("manage_product_edit", product_id=product_id)

    upload = form.cleaned_data["file"]
    stored_file = None
    try:
        with transaction.atomic():
            product = get_object_or_404(Product.objects.select_for_update(), pk=product_id)
            position = product.images.aggregate(value=Max("position"))["value"]
            image = ProductImage(
                product=product,
                position=0 if position is None else position + 1,
                alt=form.cleaned_data["alt"] or product.name[:300],
            )
            image.file.save(upload.name, upload, save=False)
            stored_file = image.file
            image.save()
            audit(request.user, product, "Thêm ảnh sản phẩm.")
    except Exception:
        if stored_file:
            schedule_product_file_cleanup(stored_file)
        raise
    messages.success(request, "Đã thêm ảnh.")
    return redirect(reverse("manage_product_edit", args=[product_id], fragment="product-images"))


def schedule_product_file_cleanup(file):
    def cleanup():
        if not ProductImage.objects.filter(file=file.name).exists() and not (
            OrderItem.objects.filter(image_snapshot=file.url).exists()
        ):
            file.storage.delete(file.name)

    transaction.on_commit(cleanup, robust=True)


@admin_permissions("catalog.change_product", "catalog.delete_productimage")
@require_POST
@transaction.atomic
def image_delete(request, product_id, image_id):
    product = get_object_or_404(Product.objects.select_for_update(), pk=product_id)
    image = get_object_or_404(ProductImage, pk=image_id, product=product)
    image.delete()
    if image.file:
        schedule_product_file_cleanup(image.file)
    audit(request.user, product, "Gỡ ảnh sản phẩm khỏi cửa hàng.")
    messages.success(request, "Đã gỡ ảnh.")
    return redirect("manage_product_edit", product_id=product.pk)


@admin_permissions(
    "catalog.change_product",
    "catalog.change_productcompatibility",
    "catalog.add_productcompatibility",
)
@require_POST
@transaction.atomic
def compatibility_save(request, product_id):
    product = get_object_or_404(Product.objects.select_for_update(), pk=product_id)
    form = CompatibilityForm(request.POST, product=product)
    if form.is_valid():
        ProductCompatibility.objects.update_or_create(
            product=product,
            phone_model=form.cleaned_data["phone_model"],
            defaults={"source": "manual", "verified": form.cleaned_data["verified"]},
        )
        audit(request.user, product, "Cập nhật xác nhận tương thích thiết bị.")
        messages.success(
            request,
            "Đã lưu xác nhận tương thích. Lựa chọn thủ công được giữ khi đồng bộ dữ liệu nguồn.",
        )
    else:
        messages.error(request, "Vui lòng chọn thiết bị hợp lệ.")
    return redirect("manage_product_edit", product_id=product.pk)


TAXONOMIES = {
    "danh-muc": (Category, CategoryEditor, "Danh mục", "category"),
    "thuong-hieu": (Brand, BrandEditor, "Thương hiệu", "brand"),
    "thiet-bi": (PhoneModel, PhoneEditor, "Thiết bị tương thích", "phonemodel"),
}


def taxonomy_config(request, kind, action):
    if kind not in TAXONOMIES:
        from django.http import Http404

        raise Http404
    model, form, label, code = TAXONOMIES[kind]
    if not request.user.has_perm(f"catalog.{action}_{code}"):
        raise PermissionDenied("Bạn không có quyền thực hiện thao tác này.")
    return model, form, label, code


@admin_permissions()
@require_GET
def taxonomy_list(request, kind):
    model, _, label, code = taxonomy_config(request, kind, "view")
    query = request.GET.get("q", "").strip()[:150]
    rows = model.objects.order_by("name", "pk")
    scope = "all" if request.GET.get("scope") == "all" else "active"
    if query:
        rows = (
            rows.filter(Q(name__icontains=query) | Q(manufacturer__icontains=query))
            if model is PhoneModel
            else rows.filter(name__icontains=query)
        )
    relation = {Category: "products", Brand: "product", PhoneModel: "productcompatibility__product"}[
        model
    ]
    active = Q(**{f"{relation}__is_active": True})
    if model is PhoneModel:
        active &= Q(productcompatibility__verified=True)
    rows = rows.annotate(
        product_count=Count(relation, distinct=True),
        active_count=Count(relation, filter=active, distinct=True),
    )
    if model is PhoneModel:
        rows = rows.annotate(preference_count=Count("preferreddevice", distinct=True))
    if scope == "active":
        rows = rows.filter(active_count__gt=0)
    return render(
        request,
        "management/taxonomy_list.html",
        {
            **page_context(request, rows),
            "kind": kind,
            "label": label,
            "area": kind,
            "query": query,
            "scope": scope,
            "can_add": request.user.has_perm(f"catalog.add_{code}"),
            "can_change": request.user.has_perm(f"catalog.change_{code}"),
            "can_delete": request.user.has_perm(f"catalog.delete_{code}"),
        },
    )


@admin_permissions()
@require_http_methods(["GET", "POST"])
@transaction.atomic
def taxonomy_edit(request, kind, object_id=None):
    model, form_class, label, _ = taxonomy_config(request, kind, "change" if object_id else "add")
    obj = (
        get_object_or_404(model.objects.select_for_update(), pk=object_id) if object_id else model()
    )
    form = form_class(request.POST if request.method == "POST" else None, instance=obj)
    if request.method == "POST" and form.is_valid():
        duplicate = model.objects.filter(name__iexact=form.cleaned_data["name"]).exclude(pk=obj.pk)
        if model is PhoneModel:
            duplicate = duplicate.filter(manufacturer__iexact=form.cleaned_data["manufacturer"])
        if duplicate.exists():
            form.add_error("name", "Tên này đã có. Hãy sử dụng mục hiện có để tránh trùng lặp.")
        else:
            saved = form.save(commit=False)
            if not saved.pk:
                saved.slug = (
                    (slugify(" ".join(str(v) for v in form.cleaned_data.values()))[:140] or "muc")
                    + "-"
                    + uuid.uuid4().hex[:12]
                )
            saved.save()
            audit(
                request.user,
                saved,
                f"Cập nhật {label.lower()}." if object_id else f"Thêm {label.lower()}.",
                CHANGE if object_id else ADDITION,
            )
            messages.success(request, "Đã lưu thay đổi.")
            list_url = reverse(
                "manage_taxonomy",
                kwargs={"kind": kind},
                query={"scope": "all", "q": saved.name},
            )
            return redirect(list_url)
    return render(
        request,
        "management/taxonomy_form.html",
        {"form": form, "object": obj, "label": label, "kind": kind, "area": kind},
    )


@admin_permissions()
@require_POST
@transaction.atomic
def taxonomy_delete(request, kind, object_id):
    model, _, label, _ = taxonomy_config(request, kind, "delete")
    obj = get_object_or_404(model.objects.select_for_update(), pk=object_id)
    used = (
        ProductCategory.objects.filter(category=obj).exists()
        if model is Category
        else Product.objects.filter(brand=obj).exists()
        if model is Brand
        else ProductCompatibility.objects.filter(phone_model=obj).exists()
        or PreferredDevice.objects.filter(phone_model=obj).exists()
    )
    if used:
        messages.error(
            request, "Mục này đang được sử dụng. Không thể xóa vì sẽ làm mất liên kết dữ liệu."
        )
    else:
        try:
            with transaction.atomic():
                audit(request.user, obj, f"Xóa {label.lower()} chưa sử dụng.", DELETION)
                obj.delete()
            messages.success(request, "Đã xóa mục chưa sử dụng.")
        except ProtectedError:
            messages.error(request, "Mục này đang được sử dụng, không thể xóa.")
    return redirect("manage_taxonomy", kind=kind)


@admin_permissions("orders.view_order")
@require_GET
def orders(request):
    query = request.GET.get("q", "").strip()[:150]
    state = request.GET.get("state", "")
    rows = Order.objects.select_related("user").order_by("-created_at", "-pk")
    if query:
        rows = rows.filter(
            Q(user__username__icontains=query)
            | Q(recipient_name__icontains=query)
            | Q(phone__icontains=query)
            | Q(number__icontains=query)
        )
    if state in Order.Status.values:
        rows = rows.filter(status=state)
    elif state:
        rows = rows.none()
    return render(
        request,
        "management/orders.html",
        {
            **page_context(request, rows),
            "area": "orders",
            "query": query,
            "state": state,
            "statuses": Order.Status.choices,
        },
    )


@admin_permissions("orders.view_order")
@require_GET
def order_detail(request, order_id):
    order = get_object_or_404(
        Order.objects.select_related("user").prefetch_related(
            "items",
            "status_history__actor",
            Prefetch("return_request", queryset=OrderReturn.objects.defer("evidence")),
        ),
        pk=order_id,
    )
    form = OrderTransitionForm(order=order)
    return render(
        request,
        "management/order_detail.html",
        {
            "order": order,
            "area": "orders",
            "form": form,
            "claim": getattr(order, "return_request", None),
            "can_transition": bool(form.fields["to_status"].choices)
            and request.user.has_perm("orders.process_order"),
        },
    )


@admin_permissions("orders.view_order", "orders.process_order")
@require_POST
def order_transition(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    form = OrderTransitionForm(request.POST, order=order)
    if form.is_valid():
        try:
            transition_order(actor=request.user, order_id=order_id, **form.cleaned_data)
            messages.success(request, "Đã cập nhật trạng thái đơn hàng.")
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
    else:
        messages.error(
            request, "Trạng thái yêu cầu không phù hợp với đơn hàng hiện tại hoặc ghi chú quá dài."
        )
    return redirect("manage_order_detail", order_id=order_id)


@admin_permissions("recommendations.view_recommendationlog")
@require_GET
def recommendations(request):
    from .views import benchmark_context

    rows = RecommendationLog.objects.select_related("user").order_by("-created_at", "-pk")
    return render(
        request,
        "management/recommendations.html",
        {**benchmark_context(request), **page_context(request, rows), "area": "recommendations"},
    )


@admin_permissions("recommendations.view_recommendationlog")
@require_GET
def recommendation_detail(request, log_id):
    entry = get_object_or_404(RecommendationLog.objects.select_related("user"), pk=log_id)
    evidence = entry.evidence or {}
    ids = set(entry.item_ids)
    for row in evidence.get("items", []):
        ids.update(source["item_id"] for source in row.get("sources", []))
    names = dict(Product.objects.filter(external_item_id__in=ids).values_list("external_item_id", "name"))
    rows = evidence.get("items", [])
    for row in rows:
        row["name"] = names.get(row["item_id"], row["item_id"])
        for source in row.get("sources", []):
            source["name"] = names.get(source["item_id"], source["item_id"])
    return render(request, "management/recommendation_detail.html", {
        "entry": entry, "evidence": evidence, "rows": rows, "area": "recommendations",
    })


@admin_permissions("catalog.view_product", "orders.view_order")
@require_GET
def activity(request):
    rows = LogEntry.objects.select_related("user", "content_type").order_by("-action_time", "-pk")
    context = page_context(request, rows)
    for entry in context["page_obj"]:
        entry.display_message = (
            "Cập nhật trạng thái và quyền truy cập tài khoản."
            if entry.change_message.startswith("{")
            else entry.get_change_message()
        )
    return render(request, "management/activity.html", {**context, "area": "activity"})
