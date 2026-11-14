"""Django settings. All deployment-sensitive values come from environment variables."""

import os
import sys
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

from config.env import env_float, env_int

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


DEBUG = env_bool("DEBUG", True)

# A throwaway key is only acceptable in DEBUG; refuse to start in production without one.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DEBUG is off.")

def env_list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
# Full origins (scheme + host) allowed to send POST/DELETE, e.g. https://my-app.vercel.app
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# Vercel sets VERCEL=1 and the deployment's own host names; allow them without extra setup.
ON_VERCEL = os.environ.get("VERCEL") == "1"
if ON_VERCEL:
    for var in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
        host = os.environ.get(var, "").strip()
        if host:
            ALLOWED_HOSTS.append(host)
            CSRF_TRUSTED_ORIGINS.append(f"https://{host}")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "profiles",
    "opportunities",
    "matching",
    "ai",
    "shortlist",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serves /static/ (Vercel has no separate static server)
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
                "ai.context_processors.ai_mode",
                "config.context_processors.static_version",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# DATABASE_URL (e.g. Neon Postgres) or local SQLite. conn_max_age=0: serverless functions should not hold
# connections open; use Neon's pooled ("-pooler") host. The test suite always uses its own SQLite database.
TESTING = "pytest" in sys.modules
if TESTING:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "test_db.sqlite3"}}
else:
    DATABASES = {
        "default": dj_database_url.config(
            default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
            conn_max_age=0,
            conn_health_checks=True,
        )
    }
    if "postgresql" in DATABASES["default"]["ENGINE"]:
        DATABASES["default"].setdefault("OPTIONS", {}).setdefault("sslmode", "require")  # Neon needs TLS
    if ON_VERCEL and DATABASES["default"]["ENGINE"].endswith("sqlite3"):
        raise RuntimeError("DATABASE_URL must be set on Vercel: its disk is read-only and not kept between requests.")

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
# WhiteNoise serves straight from static/ (no collectstatic build step, no STATIC_ROOT); ?v= busts caches.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG

# --- HTTPS / cookies: on whenever DEBUG is off (always the case on Vercel) ---
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 3600, min_value=0, max_value=63_072_000)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- CV upload ---
CV_MAX_UPLOAD_MB = env_int("CV_MAX_UPLOAD_MB", 10, min_value=1, max_value=50)
CV_MIN_WORDS_PER_PAGE = env_int("CV_MIN_WORDS_PER_PAGE", 50, min_value=0, max_value=1000)  # below this: treated as scanned
CV_MAX_CHARS_SENT = env_int("CV_MAX_CHARS_SENT", 15_000, min_value=1_000, max_value=200_000)  # bounds tokens per CV

# Uploads are processed in memory and never written to disk. CVs over CV_MAX_UPLOAD_MB get a clear
# message; anything over that + 2 MB is dropped by the handler and also reported as too large.
FILE_UPLOAD_HANDLERS = ["django.core.files.uploadhandler.MemoryFileUploadHandler"]
FILE_UPLOAD_MAX_MEMORY_SIZE = (CV_MAX_UPLOAD_MB + 2) * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024  # non-file form data

# --- Live AI provider (keys absent => the toggle is locked to Mock) ---
# groq (default) | cloudflare | watsonx
AI_PROVIDER = os.environ.get("AI_PROVIDER", "groq").strip().lower()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "").strip()
# Only for reasoning models (e.g. gpt-oss): low | medium | high. Blank = not sent.
GROQ_REASONING_EFFORT = os.environ.get("GROQ_REASONING_EFFORT", "").strip().lower()
if GROQ_REASONING_EFFORT not in {"", "low", "medium", "high"}:
    from config.env import ConfigError

    raise ConfigError(f"GROQ_REASONING_EFFORT must be low, medium, high or blank, got {GROQ_REASONING_EFFORT!r}.")

CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_MODEL = os.environ.get("CLOUDFLARE_MODEL", "").strip()

WATSONX_APIKEY = os.environ.get("WATSONX_APIKEY", "")
WATSONX_URL = os.environ.get("WATSONX_URL", "")
WATSONX_PROJECT_ID = os.environ.get("WATSONX_PROJECT_ID", "")
WATSONX_MODEL_ID = os.environ.get("WATSONX_MODEL_ID", "").strip()

# --- Live AI limits ---
AI_CALL_TIMEOUT_SECONDS = env_float("AI_CALL_TIMEOUT_SECONDS", 45, min_value=5, max_value=300)
AI_AGENT_MAX_MODEL_CALLS = env_int("AI_AGENT_MAX_MODEL_CALLS", 6, min_value=2, max_value=20)  # tool calls + answer + repair
AI_AGENT_RECURSION_LIMIT = env_int("AI_AGENT_RECURSION_LIMIT", 24, min_value=4, max_value=100)  # graph steps
AI_LIVE_CALLS_PER_SESSION = env_int("AI_LIVE_CALLS_PER_SESSION", 25, min_value=0, max_value=10_000)

# --- Privacy: data retention ---
# purge_expired_data deletes profiles (with shortlists and AI assessments), inactive assessments and AI
# cache rows not used for this many days, plus expired sessions. Run it daily.
DATA_RETENTION_DAYS = env_int("DATA_RETENTION_DAYS", 30, min_value=1, max_value=3650)

# --- Matching weights (MATCH_WEIGHT_SKILLS, ..._EXPERIENCE, ..._LANGUAGE, ..._LOCATION, ..._EDUCATION, ..._INTERESTS)
# Parsed here only to fail fast at startup; the engine reads them itself (matching/config.py).
from matching.config import parse_experience_factors, parse_weights  # noqa: E402

MATCH_WEIGHTS = parse_weights(os.environ)
MATCH_EXPERIENCE_FACTORS = parse_experience_factors(os.environ)  # MATCH_EXPERIENCE_UNRELATED / _UNKNOWN
