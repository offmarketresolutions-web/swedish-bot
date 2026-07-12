"""Django settings for the Nordland VVS support bot.

Lean, single-file, env-driven (ponytail/Karpathy). Reads a local .env in dev;
in Docker the env is injected by compose. i18n is ON from day one so the Swedish
flip (plan §11) is translation-only, never a code change.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _env_list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


# ── Core ──────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = _env_bool("DJANGO_DEBUG", "0")  # fail-safe: production unless explicitly on
ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

# Origins permitted to embed the widget / hit the chat API (CORS, plan §10).
WIDGET_ALLOWED_ORIGINS = _env_list("WIDGET_ALLOWED_ORIGINS", "http://localhost:8000")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    # local apps
    "core",
    "kb",
    "chat",
    "crm",
    "dashboard",
    "voice",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.WidgetCorsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",  # i18n (plan §11)
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.DemoAutoLoginMiddleware",  # LOCAL/DEMO ONLY: open admin (flag-gated)
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
            ],
        },
    },
]

# ── Database ──────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "nordland"),
        "USER": os.environ.get("POSTGRES_USER", "nordland"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "nordland"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

# ── i18n / l10n (plan §11) ────────────────────────────────────────────
LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("sv", "Svenska")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Europe/Stockholm"
USE_I18N = True
USE_TZ = True

# ── Static / media ────────────────────────────────────────────────────
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
MEDIA_URL = "uploads/"
MEDIA_ROOT = BASE_DIR / "data" / "uploads"

# Absolute base URL for building outbound file links (n8n Drive mirror). Blank in dev.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Email (lead sink; console backend in dev) ─────────────────────────
EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
LEAD_EMAIL_TO = os.environ.get("LEAD_EMAIL_TO", "")
LEAD_EMAIL_FROM = os.environ.get("LEAD_EMAIL_FROM", "bot@nordlandvvs.se")

# ── Security hardening (V2 §S5/S6/S7) ─────────────────────────────────
# Phone-hash pepper for returning-customer recognition — MUST differ from SECRET_KEY.
PHONE_HASH_PEPPER = os.environ.get("PHONE_HASH_PEPPER", "dev-pepper-change-me")

# Upload + body limits (oversized-body / decompression-bomb guards).
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# Anonymous chat endpoint rate limits + abuse ceilings.
RATE_LIMIT_SESSION = int(os.environ.get("RATE_LIMIT_SESSION", "20"))   # sessions / IP / window
RATE_LIMIT_MESSAGE = int(os.environ.get("RATE_LIMIT_MESSAGE", "40"))   # messages / session / window
RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", "300"))
MAX_TOTAL_TURNS = int(os.environ.get("MAX_TOTAL_TURNS", "25"))         # hard per-conversation ceiling
MAX_IMAGES_PER_CONVERSATION = int(os.environ.get("MAX_IMAGES_PER_CONVERSATION", "8"))

# Embedding-backed semantic search: machine-identification fallback (when trigram
# is unsure) + most-relevant FAQ/guide retrieval. Trigram + full-PDF-in-context
# stay the primary, reliable path; this only augments. On by default at runtime;
# the test suite disables it (autouse fixture) so unit tests stay offline.
SEMANTIC_SEARCH_ENABLED = _env_bool("SEMANTIC_SEARCH_ENABLED", "1")

# LOCAL/DEMO ONLY (fail-safe OFF). When on: auto-authenticate as a superuser so
# /admin + /dashboard need no login, and expose the /playground test console + its
# debug internals. NEVER enable in production — it bypasses all staff auth.
DEMO_OPEN_ADMIN = _env_bool("DEMO_OPEN_ADMIN", "0")

CSRF_TRUSTED_ORIGINS = _env_list("CSRF_TRUSTED_ORIGINS", "")

# ── Voice / phone channel (Vapi) + WhatsApp Cloud API + n8n ───────────────────
# All DB-editable from the dashboard credentials catalog (live-applied over these .env defaults).
VAPI_PRIVATE_KEY = os.environ.get("VAPI_PRIVATE_KEY", "")
VAPI_WEBHOOK_SECRET = os.environ.get("VAPI_WEBHOOK_SECRET", "")
VAPI_PHONE_NUMBER_ID = os.environ.get("VAPI_PHONE_NUMBER_ID", "")
VAPI_ASSISTANT_ID = os.environ.get("VAPI_ASSISTANT_ID", "")
VAPI_ASSISTANT_MODEL = os.environ.get("VAPI_ASSISTANT_MODEL", "")
VAPI_VOICE_ID = os.environ.get("VAPI_VOICE_ID", "")
VAPI_SIGNATURE_HEADER = os.environ.get("VAPI_SIGNATURE_HEADER", "X-Vapi-Signature")
VAPI_SECRET_HEADER = os.environ.get("VAPI_SECRET_HEADER", "X-Vapi-Secret")

WA_PHONE_NUMBER_ID = os.environ.get("WA_PHONE_NUMBER_ID", "")
WA_ACCESS_TOKEN = os.environ.get("WA_ACCESS_TOKEN", "")
WA_APP_SECRET = os.environ.get("WA_APP_SECRET", "")
WA_VERIFY_TOKEN = os.environ.get("WA_VERIFY_TOKEN", "")
WA_PHOTO_TEMPLATE_NAME = os.environ.get("WA_PHOTO_TEMPLATE_NAME", "")
WA_GRAPH_VERSION = os.environ.get("WA_GRAPH_VERSION", "v21.0")

N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")

# Local-dev webhook bypass — honored ONLY when DEBUG (fail-closed in prod, see boot guard below).
VOICE_WEBHOOK_DEV_BYPASS = _env_bool("VOICE_WEBHOOK_DEV_BYPASS", "0")

if not DEBUG:
    from django.core.exceptions import ImproperlyConfigured

    # Fail-closed: never run production with the dev secret.
    if SECRET_KEY == "dev-insecure-change-me":
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set in production (DEBUG=0).")
    # Fail-closed: EU data residency for Swedish customer PII (GDPR). Override only
    # with ALLOW_NON_EU_RESIDENCY=1 (e.g. the temporary us-central1 demo SA).
    _loc = (os.environ.get("GOOGLE_CLOUD_LOCATION") or "").lower()
    if not (_loc.startswith("europe") or _loc == "eu") and not _env_bool("ALLOW_NON_EU_RESIDENCY", "0"):
        raise ImproperlyConfigured(
            f"Vertex location '{_loc or '(unset)'}' is not EU (GDPR). Set GOOGLE_CLOUD_LOCATION "
            "to a europe-* region, or ALLOW_NON_EU_RESIDENCY=1 to override (NOT for real PII)."
        )
    # Fail-closed: the phone-hash pepper must differ from SECRET_KEY (cross-channel join key).
    if PHONE_HASH_PEPPER == SECRET_KEY:
        raise ImproperlyConfigured("PHONE_HASH_PEPPER must differ from DJANGO_SECRET_KEY.")
    # Fail-closed: the voice channel webhooks are signature-authed — refuse to boot with the
    # channel enabled but its shared secrets unset. Set VOICE_ENABLED=0 to run without the channel.
    if _env_bool("VOICE_ENABLED", "1"):
        _missing = [n for n in ("VAPI_WEBHOOK_SECRET", "WA_APP_SECRET") if not os.environ.get(n)]
        if _missing:
            raise ImproperlyConfigured(
                f"Voice channel enabled but {', '.join(_missing)} unset (fail-closed). "
                "Set them, or VOICE_ENABLED=0 to disable the phone/WhatsApp channel."
            )

    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_HTTPONLY = True
    X_FRAME_OPTIONS = "DENY"
    # TLS-dependent flags: on only behind real HTTPS (the http demo sets HTTPS_ENABLED off).
    if _env_bool("HTTPS_ENABLED", "0"):
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
        SECURE_SSL_REDIRECT = True
        SECURE_HSTS_SECONDS = 31536000
        SECURE_HSTS_INCLUDE_SUBDOMAINS = True
        SECURE_HSTS_PRELOAD = True
        SESSION_COOKIE_SECURE = True
        CSRF_COOKIE_SECURE = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
