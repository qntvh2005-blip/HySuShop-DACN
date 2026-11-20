from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import PreferredDevice, Profile, User

admin.site.register(User, UserAdmin)
admin.site.register(Profile)
admin.site.register(PreferredDevice)
