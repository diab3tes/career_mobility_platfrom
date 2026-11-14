import os
from functools import lru_cache
from pathlib import Path

from django.conf import settings


@lru_cache(maxsize=1)
def _newest_static_mtime() -> int:
    newest = 0
    for folder in settings.STATICFILES_DIRS:
        for f in Path(folder).rglob("*"):
            if f.is_file():
                newest = max(newest, int(f.stat().st_mtime))
    return newest


def static_version(request):
    """Cache-busting tag for our own static files. On Vercel: the deployed commit. Locally: the newest
    modification time under static/ (re-scanned on every request in DEBUG, so edits show at once)."""
    sha = os.environ.get("VERCEL_GIT_COMMIT_SHA", "")
    if sha:
        return {"static_v": sha[:12]}
    if settings.DEBUG:
        _newest_static_mtime.cache_clear()
    return {"static_v": _newest_static_mtime()}
