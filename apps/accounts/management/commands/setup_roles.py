from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.accounts.models import User
from apps.accounts.roles import configure_roles


class Command(BaseCommand):
    help = "Configure customer/admin roles and consolidate legacy managed groups."

    @transaction.atomic
    def handle(self, *args, **options):
        customer, administrator = configure_roles()
        legacy = Group.objects.filter(name__in=["Staff", "Manager"])
        for user in User.objects.prefetch_related("groups").order_by("pk"):
            groups = list(user.groups.all())
            if not groups or any(g.pk in {customer.pk, administrator.pk} or g.name in {"Staff", "Manager"} for g in groups):
                # Preserve the access flag and disabled state. Membership alone
                # must never promote a customer into a management identity.
                user.groups.remove(customer, administrator, *legacy)
                user.groups.add(administrator if user.is_staff else customer)
        legacy.delete()
        for group in (customer, administrator):
            self.stdout.write(f"{group.name}: {group.permissions.count()} permissions")
