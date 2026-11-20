from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.accounts.forms import AccountAccessForm, AccountCreationForm
from apps.accounts.roles import ADMIN, CUSTOMER, ROLE_CHOICES
from apps.accounts.services import update_account_access


class TwoRoleTests(TestCase):
    def setUp(self):
        call_command("setup_roles", stdout=StringIO())
        self.admin = get_user_model().objects.create_user(username="administrator", is_staff=True)
        self.admin.groups.add(Group.objects.get(name=ADMIN))
        self.customer = get_user_model().objects.create_user(username="customer")

    def test_forms_and_pages_expose_only_customer_and_administrator(self):
        for form in (AccountAccessForm(), AccountCreationForm()):
            self.assertEqual(tuple(form.fields["role"].choices), ROLE_CHOICES)
        self.client.force_login(self.admin)
        for name, args in [("manage_account_create", []), ("manage_account_access", [self.customer.pk])]:
            response = self.client.get(reverse(name, args=args))
            self.assertContains(response, 'value="Admin"')
            self.assertContains(response, 'value="Customer"')
            for old in ['value="Staff"', 'value="Manager"', "Nhân viên", "Quản trị viên cấp cao"]:
                self.assertNotContains(response, old)

    def test_legacy_groups_migrate_without_promoting_customers_or_unlocking_accounts(self):
        legacy = Group.objects.create(name="Staff")
        old_manager = Group.objects.create(name="Manager")
        self.admin.groups.set([legacy])
        self.customer.groups.set([old_manager])
        get_user_model().objects.filter(pk=self.admin.pk).update(is_active=False)
        call_command("setup_roles", stdout=StringIO())
        self.admin.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual(set(self.admin.groups.values_list("name", flat=True)), {ADMIN})
        self.assertEqual(set(self.customer.groups.values_list("name", flat=True)), {CUSTOMER})
        self.assertFalse(self.admin.is_active)
        self.assertFalse(self.customer.is_staff)
        self.assertFalse(Group.objects.filter(name__in=["Staff", "Manager"]).exists())

    def test_all_managed_accounts_have_only_their_current_role_after_setup(self):
        call_command("setup_roles", stdout=StringIO())
        call_command("setup_roles", stdout=StringIO())
        self.assertEqual(set(Group.objects.values_list("name", flat=True)), {CUSTOMER, ADMIN})
        self.assertEqual(set(self.customer.groups.values_list("name", flat=True)), {CUSTOMER})
        self.assertTrue(self.admin.has_perm("accounts.manage_accounts"))
        self.assertFalse(self.admin.has_perm("auth.change_group"))

    def test_demotion_revokes_an_existing_administrator_session(self):
        other = get_user_model().objects.create_user(username="other-admin", is_staff=True)
        other.groups.add(Group.objects.get(name=ADMIN))
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("manage_accounts")).status_code, 200)
        update_account_access(actor=self.admin, user_id=other.pk, role=CUSTOMER, is_active=True)
        self.assertEqual(self.client.get(reverse("manage_accounts")).status_code, 403)
        other.refresh_from_db()
        self.assertFalse(other.is_staff)
        self.assertFalse(other.has_perm("accounts.manage_accounts"))

    def test_public_signup_cannot_choose_an_administrator_role(self):
        response = self.client.post(reverse("signup"), {
            "username": "public-buyer", "email": "buyer@example.test",
            "password1": "A-strong-passphrase-857!", "password2": "A-strong-passphrase-857!",
            "role": ADMIN, "is_staff": "on", "is_superuser": "on",
        })
        self.assertRedirects(response, reverse("home"))
        user = get_user_model().objects.get(username="public-buyer")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(set(user.groups.values_list("name", flat=True)), {CUSTOMER})
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 403)
