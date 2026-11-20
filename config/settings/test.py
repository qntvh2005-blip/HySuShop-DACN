from .base import *  # noqa: F403

SECRET_KEY = "isolated-test-key"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
DATABASES["default"]["CONN_MAX_AGE"] = 0  # noqa: F405
