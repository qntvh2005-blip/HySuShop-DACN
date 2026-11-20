from django.contrib.auth.models import Group, Permission

CUSTOMER = "Customer"
ADMIN = "Admin"
ROLE_CHOICES = ((CUSTOMER, "Khách hàng"), (ADMIN, "Quản trị viên"))
CATALOG_MODELS = {
    "category", "brand", "product", "productimage", "productcategory",
    "phonemodel", "productcompatibility",
}


def configure_roles():
    """Set the two managed roles without granting raw auth-table editing."""
    permissions = []
    for permission in Permission.objects.select_related("content_type"):
        app = permission.content_type.app_label
        model = permission.content_type.model
        action = permission.codename.split("_", 1)[0]
        if (
            (app == "catalog" and model in CATALOG_MODELS)
            or (app in {"orders", "interactions", "recommendations"} and action == "view")
            or (app == "orders" and permission.codename == "process_order")
            or (app == "accounts" and (action == "view" or permission.codename == "manage_accounts"))
        ):
            permissions.append(permission)
    customer, _ = Group.objects.get_or_create(name=CUSTOMER)
    administrator, _ = Group.objects.get_or_create(name=ADMIN)
    customer.permissions.clear()
    administrator.permissions.set(permissions)
    return customer, administrator
