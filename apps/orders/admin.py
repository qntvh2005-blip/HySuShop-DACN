from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError

from apps.common.admin import ReadOnlyAdmin

from .models import Order, OrderItem, OrderStatusHistory
from .services import transition_order


@admin.register(Order)
class OrderAdmin(ReadOnlyAdmin):
    list_display = ["number", "user", "status", "total", "created_at"]
    list_filter = ["status", "payment_method"]
    search_fields = ["number", "user__username"]
    actions = [
        "confirm_orders",
        "ship_orders",
        "deliver_orders",
        "cancel_orders",
        "receive_returns",
    ]

    def has_process_permission(self, request):
        return request.user.has_perm("orders.process_order")

    def _transition(self, request, queryset, status):
        changed, rejected = 0, 0
        for order_id in queryset.values_list("pk", flat=True):
            try:
                transition_order(
                    actor=request.user,
                    order_id=order_id,
                    to_status=status,
                    reason="Quản trị viên cập nhật qua quản trị",
                )
                changed += 1
            except (ValidationError, PermissionDenied):
                rejected += 1
        self.message_user(
            request,
            f"Đã xử lý {changed} đơn; {rejected} đơn không phù hợp với bước chuyển trạng thái.",
        )

    @admin.action(description="Xác nhận đơn đã chọn", permissions=["process"])
    def confirm_orders(self, request, queryset):
        self._transition(request, queryset, "confirmed")

    @admin.action(description="Chuyển sang đang giao", permissions=["process"])
    def ship_orders(self, request, queryset):
        self._transition(request, queryset, "shipping")

    @admin.action(description="Xác nhận đã giao hàng", permissions=["process"])
    def deliver_orders(self, request, queryset):
        self._transition(request, queryset, "delivered")

    @admin.action(description="Hủy đơn đã chọn", permissions=["process"])
    def cancel_orders(self, request, queryset):
        self._transition(request, queryset, "cancelled")

    @admin.action(description="Xác nhận đã nhận hàng trả", permissions=["process"])
    def receive_returns(self, request, queryset):
        self._transition(request, queryset, "returned")


admin.site.register(OrderItem, ReadOnlyAdmin)
admin.site.register(OrderStatusHistory, ReadOnlyAdmin)
