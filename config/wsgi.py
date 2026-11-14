"""WSGI entry point (local servers, Vercel).

On Vercel every request is rewritten to the one Python function (see vercel.json), and the function is
handed the destination path, not the one the visitor asked for. vercel.json therefore passes the original
path as ?__path=/...; restore_path puts it back before Django (and WhiteNoise) see the request and keeps
the visitor's own query parameters. Requests without the parameter (local runs) are untouched.
"""

import os
from urllib.parse import parse_qsl, urlencode

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

PATH_PARAM = "__path"


def restore_path(wsgi_app):
    def wrapped(environ, start_response):
        query = environ.get("QUERY_STRING", "")
        if PATH_PARAM in query:
            pairs = parse_qsl(query, keep_blank_values=True)
            original = next((v for k, v in pairs if k == PATH_PARAM), None)
            if original is not None:
                environ["PATH_INFO"] = original if original.startswith("/") else f"/{original}"
                environ["QUERY_STRING"] = urlencode([(k, v) for k, v in pairs if k != PATH_PARAM])
        return wsgi_app(environ, start_response)

    return wrapped


django_application = get_wsgi_application()
application = restore_path(django_application)
app = application  # the name Vercel's Python runtime looks for
