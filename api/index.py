"""Vercel entry point: every request is rewritten here (see vercel.json). The original path is restored
in config/wsgi.py, so it works whichever of the two files Vercel starts from."""

from config.wsgi import app, application  # noqa: F401
