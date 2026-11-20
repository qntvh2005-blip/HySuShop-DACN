from .base import *  # noqa: F403

SECRET_KEY = SECRET_KEY or "local-development-only-do-not-use-in-production"  # noqa: F405
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"  # noqa: F405

if DEBUG:
    # Development templates must reflect edits even when runserver uses --noreload.
    TEMPLATES[0]["APP_DIRS"] = False  # noqa: F405
    TEMPLATES[0]["OPTIONS"]["loaders"] = [  # noqa: F405
        "django.template.loaders.filesystem.Loader",
        "django.template.loaders.app_directories.Loader",
    ]
