from pathlib import Path

from django.conf import settings


def static_version(request):
    """Cache-busting tag for our own static files: the newest modification time under static/.
    Browsers re-fetch CSS/JS as soon as any of them changes."""
    newest = 0
    for folder in settings.STATICFILES_DIRS:
        for f in Path(folder).rglob("*"):
            if f.is_file():
                newest = max(newest, int(f.stat().st_mtime))
    return {"static_v": newest}
