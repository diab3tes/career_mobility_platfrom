"""Vercel entry point: every request is rewritten here (see vercel.json) and handled by Django's WSGI app.

Vercel's rewrite hands the function the destination path (/api/index), not the one the visitor asked for,
so vercel.json passes the original path as ?__path=/... and this wrapper puts it back before Django
(and WhiteNoise) see the request. The visitor's own query parameters are kept.
"""

from urllib.parse import parse_qsl, urlencode

from config.wsgi import application

PATH_PARAM = "__path"


def app(environ, start_response):
    pairs = parse_qsl(environ.get("QUERY_STRING", ""), keep_blank_values=True)
    original = next((v for k, v in pairs if k == PATH_PARAM), None)
    if original is not None:
        environ["PATH_INFO"] = original if original.startswith("/") else f"/{original}"
        environ["QUERY_STRING"] = urlencode([(k, v) for k, v in pairs if k != PATH_PARAM])
    return application(environ, start_response)
