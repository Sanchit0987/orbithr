"""Vercel entrypoint: adapts the OrbitHR stdlib Handler to Vercel's Python
runtime (which natively runs BaseHTTPRequestHandler subclasses named `handler`).

Deployment note: Vercel's function filesystem is read-only except /tmp, so the
SQLite DB lives at /tmp/hrms.db. That storage is EPHEMERAL — demo data re-seeds
on every cold start. For durable storage run the app on a persistent host
(python3 app.py) or port the data layer to a hosted Postgres.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("ORBITHR_DB", "/tmp/hrms.db")

import db as D  # noqa: E402

D.init()  # seed demo data on cold start

from app import Handler  # noqa: E402


class handler(Handler):  # Vercel requires this exact lowercase name
    pass
