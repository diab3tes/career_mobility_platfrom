"""Vercel entry point: every request is rewritten here (see vercel.json) and handled by Django's WSGI app."""

from config.wsgi import application

app = application
