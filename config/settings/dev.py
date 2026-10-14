from .base import *  # noqa: F401,F403

DEBUG = env.bool("DEBUG", default=True)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"