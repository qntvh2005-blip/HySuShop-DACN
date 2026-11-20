from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def admin_permissions(*permissions):
    """Management entry requires an active administrator flag and the requested permissions."""

    def decorate(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if (
                not request.user.is_active
                or not request.user.is_staff
                or not request.user.has_perms(permissions)
            ):
                raise PermissionDenied("Bạn không có quyền truy cập chức năng quản trị này.")
            return view(request, *args, **kwargs)

        return wrapped

    return decorate
