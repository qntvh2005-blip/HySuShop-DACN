from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Website identity; Amazon research user IDs remain in research files."""

    class Meta(AbstractUser.Meta):
        permissions = [("manage_accounts", "Can manage customer status and staff membership")]


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    phone = models.CharField(max_length=25, blank=True)
    default_address = models.TextField(blank=True)

    def __str__(self):
        return str(self.user)


class PreferredDevice(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="preferred_devices"
    )
    phone_model = models.ForeignKey("catalog.PhoneModel", on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "phone_model"], name="unique_preferred_device")
        ]
