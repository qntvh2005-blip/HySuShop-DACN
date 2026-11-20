import json

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .models import User
from .roles import ADMIN, CUSTOMER, ROLE_CHOICES


def protected_account(user, actor=None):
    """Keep root identities and accounts with custom permissions protected."""
    groups = {group.name for group in user.groups.all()}
    allowed = {CUSTOMER, ADMIN}
    return (
        user.is_superuser
        or bool(groups - allowed)
        or bool(user.user_permissions.all())
        or (user.is_staff and ADMIN not in groups)
    )


@transaction.atomic
def update_account_access(*, actor, user_id, is_active, role):
    # Lock in a stable order and re-read permissions to reject stale sessions.
    users = {
        user.pk: user
        for user in User.objects.select_for_update()
        .filter(pk__in=[actor.pk, user_id])
        .order_by("pk")
    }
    current_actor = users.get(actor.pk)
    if (
        not current_actor
        or not current_actor.is_active
        or not current_actor.is_staff
        or not current_actor.has_perm("accounts.manage_accounts")
    ):
        raise PermissionDenied("Bạn không có quyền quản lý tài khoản.")
    target = users.get(user_id)
    if target is None:
        raise ValidationError("Tài khoản không còn tồn tại.")
    if target.pk == actor.pk or protected_account(target, current_actor):
        raise PermissionDenied("Tài khoản được bảo vệ, không thể thay đổi tại đây.")
    roles = {value for value, _ in ROLE_CHOICES}
    if role not in roles or not isinstance(is_active, bool):
        raise ValidationError("Thông tin phân quyền không hợp lệ.")
    before = {
        "is_active": target.is_active,
        "is_staff": target.is_staff,
        "groups": sorted(target.groups.values_list("name", flat=True)),
    }
    group = Group.objects.get(name=role)
    target.is_active, target.is_staff = is_active, role == ADMIN
    target.save(update_fields=["is_active", "is_staff"])
    target.groups.set([group])
    after = {"is_active": target.is_active, "is_staff": target.is_staff, "groups": [role]}
    if before != after:
        LogEntry.objects.create(
            user=current_actor,
            content_type=ContentType.objects.get_for_model(User),
            object_id=str(target.pk),
            object_repr=str(target)[:200],
            action_flag=CHANGE,
            change_message=json.dumps({"before": before, "after": after}, ensure_ascii=False),
        )
    return target
