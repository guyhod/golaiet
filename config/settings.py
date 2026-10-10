"""Django settings. Everything deploy-specific comes from the environment
(.env at the repo root via python-dotenv), so the same tree runs on the Mac
and in docker compose."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "scheduler",
    "chat",
    "agent",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "golaiet"),
        "USER": os.getenv("DB_USER", "golaiet"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5435"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-us"
# Guy's clock: cron schedules and admin display. DB timestamps are stored UTC.
TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "Asia/Jerusalem")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Telegram (the presence of both values is the switch; no separate flag) ---
# Where the Bot API lives. The end-to-end stack points it at tests/e2e/fake_telegram.py.
TELEGRAM_API_BASE = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --- Claude headless agent ---
CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "sonnet")
AGENT_TIMEOUT_SEC = int(os.getenv("AGENT_TIMEOUT_SEC", "900"))
# Where the CLI keeps its own state (session store, settings). Pointed at a
# directory of our own so a session never loads this machine's user-level
# plugins, hooks and MCP servers: measured 2026-10-09, the same tool-calling
# probe took 27 s and 67k input tokens with the host config, 4 s and 50k with
# an empty one. In docker compose this is the claude_state volume.
CLAUDE_CONFIG_DIR = os.getenv("CLAUDE_CONFIG_DIR", str(BASE_DIR / ".claude-state"))
# Per-run MCP config files land here (gitignored).
AGENT_RUNS_DIR = BASE_DIR / "agent" / "runs"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "apscheduler": {"level": "WARNING"},
        # httpx logs full request URLs at INFO, and the Telegram URL carries the bot token.
        "httpx": {"level": "WARNING"},
    },
}
