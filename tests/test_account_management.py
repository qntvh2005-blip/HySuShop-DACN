from io import StringIO

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.services import update_account_access


class AccountManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("setup_roles", stdout=StringIO())
        User = get_user_model()
        cls.manager = User.objects.create_user(username="manager", is_staff=True)
        cls.manager.groups.add(Group.objects.get(name="Admin"))
        cls.staff = User.objects.create_user(username="staff", is_staff=True)
        # A management flag without assigned permissions must still be denied.
        cls.customer = User.objects.create_user(username="customer", email="customer@example.test")
        cls.root = User.objects.create_user(username="root", is_staff=True, is_superuser=True)

    def test_customer_staff_and_anonymous_cannot_manage_accounts(self):
        for user in [None, self.customer, self.staff]:
            self.client.logout()
            if user:
                self.client.force_login(user)
            expected = 403 if user else 302
            self.assertEqual(self.client.get(reverse("manage_accounts")).status_code, expected)
            self.assertEqual(
                self.client.post(
                    reverse("manage_account_access", args=[self.customer.pk]),
                    {"role": "Admin", "is_active": "on"},
                ).status_code,
                expected,
            )

    def test_administrator_promotes_demotes_and_logs_without_granting_superuser(self):
        self.client.force_login(self.manager)
        path = reverse("manage_account_access", args=[self.customer.pk])
        self.assertEqual(self.client.get(path).status_code, 200)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_staff)
        self.assertRedirects(
            self.client.post(path, {"role": "Admin", "is_active": "on", "is_superuser": "on"}),
            reverse("manage_accounts"),
        )
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_staff)
        self.assertTrue(self.customer.has_perm("orders.process_order"))
        self.assertFalse(self.customer.has_perm("accounts.change_user"))
        self.assertTrue(self.customer.has_perm("accounts.manage_accounts"))
        self.assertFalse(self.customer.is_superuser)
        self.assertEqual(
            LogEntry.objects.filter(user=self.manager, object_id=str(self.customer.pk)).count(), 1
        )
        self.client.post(path, {"role": "Customer", "is_active": "on"})
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_staff)
        self.assertEqual(set(self.customer.groups.values_list("name", flat=True)), {"Customer"})
        self.assertFalse(
            get_user_model().objects.get(pk=self.customer.pk).has_perm("orders.process_order")
        )

    def test_reserved_accounts_and_self_are_protected(self):
        special = get_user_model().objects.create_user(username="special")
        special.user_permissions.add(Permission.objects.get(codename="view_user"))
        unknown = get_user_model().objects.create_user(username="unknown")
        unknown.groups.add(Group.objects.create(name="Custom authority"))
        self.client.force_login(self.manager)
        for target in [self.manager, self.root, special, unknown]:
            path = reverse("manage_account_access", args=[target.pk])
            self.assertEqual(self.client.get(path).status_code, 403)
            self.assertEqual(self.client.post(path, {"role": "Customer"}).status_code, 403)
        self.assertEqual(LogEntry.objects.count(), 0)

    def test_invalid_role_and_missing_csrf_do_not_change_permissions(self):
        self.client.force_login(self.manager)
        path = reverse("manage_account_access", args=[self.customer.pk])
        response = self.client.post(path, {"role": "Manager", "is_active": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.manager)
        self.assertEqual(
            csrf_client.post(path, {"role": "Admin", "is_active": "on"}).status_code, 403
        )
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_staff)

    def test_locking_account_invalidates_existing_login_without_deleting_history(self):
        customer_client = Client()
        customer_client.force_login(self.customer)
        self.assertEqual(customer_client.get(reverse("interaction_history")).status_code, 200)
        self.client.force_login(self.manager)
        self.client.post(
            reverse("manage_account_access", args=[self.customer.pk]), {"role": "Customer"}
        )
        self.assertEqual(customer_client.get(reverse("interaction_history")).status_code, 302)
        self.assertTrue(
            get_user_model().objects.filter(pk=self.customer.pk, is_active=False).exists()
        )

    def test_service_rechecks_actor_access_and_managed_role_setup_is_repeatable(self):
        call_command("setup_roles", stdout=StringIO())
        self.assertFalse(self.manager.has_perm("accounts.change_user"))
        get_user_model().objects.filter(pk=self.manager.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            update_account_access(
                actor=self.manager, user_id=self.customer.pk, role="Admin", is_active=True
            )

    def test_search_and_pagination_and_protected_labels(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("manage_accounts"), {"q": "customer@example.test"})
        self.assertEqual(list(response.context["page_obj"]), [self.customer])
        self.assertContains(response, "Chỉnh sửa quyền truy cập")
        response = self.client.get(reverse("manage_accounts"), {"q": "root"})
        self.assertContains(response, "Được bảo vệ")
        self.assertNotContains(response, reverse("manage_account_access", args=[self.root.pk]))
        get_user_model().objects.bulk_create(
            [
                get_user_model()(username=f"page-user-{i}", email="page+tag@example.test")
                for i in range(26)
            ]
        )
        response = self.client.get(
            reverse("manage_accounts"), {"q": "page+tag@example.test", "page": 2}
        )
        self.assertEqual(response.context["page_obj"].paginator.count, 26)
        self.assertEqual(len(response.context["page_obj"]), 2)
        self.assertContains(response, "q=page%2Btag%40example.test&amp;page=1")
        self.assertNotIn("page=", response.context["query_string"])

    def test_administrator_creates_admin_but_cannot_forge_superuser_or_legacy_role(self):
        self.client.force_login(self.manager)
        payload = {
            "username": "new-staff",
            "email": "new@example.test",
            "password1": "Strong-passphrase-928!",
            "password2": "Strong-passphrase-928!",
            "role": "Admin",
            "is_active": "on",
            "is_superuser": "on",
        }
        self.assertRedirects(
            self.client.post(reverse("manage_account_create"), payload), reverse("manage_accounts")
        )
        user = get_user_model().objects.get(username="new-staff")
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password(payload["password1"]))
        self.assertTrue(user.has_perm("accounts.manage_accounts"))
        payload.update(username="forged-manager", role="Manager")
        response = self.client.post(reverse("manage_account_create"), payload)
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(get_user_model().objects.filter(username="forged-manager").exists())

    def test_root_can_assign_admin_without_editing_root_or_self(self):
        self.client.force_login(self.root)
        path = reverse("manage_account_access", args=[self.customer.pk])
        self.assertRedirects(
            self.client.post(path, {"role": "Admin", "is_active": "on"}),
            reverse("manage_accounts"),
        )
        user = get_user_model().objects.get(pk=self.customer.pk)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.has_perm("accounts.manage_accounts"))
        self.assertFalse(user.is_superuser)
        self.assertEqual(
            self.client.get(reverse("manage_account_access", args=[self.manager.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                reverse("manage_account_access", args=[self.root.pk]), {"role": "Customer"}
            ).status_code,
            403,
        )

    def test_create_requires_csrf_and_rejects_weak_password(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.manager)
        payload = {
            "username": "weak",
            "email": "weak@example.test",
            "password1": "123",
            "password2": "123",
            "role": "Admin",
        }
        self.assertEqual(client.post(reverse("manage_account_create"), payload).status_code, 403)
        self.client.force_login(self.manager)
        response = self.client.post(reverse("manage_account_create"), payload)
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(get_user_model().objects.filter(username="weak").exists())
