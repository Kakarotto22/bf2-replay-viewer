"""WSGI entry for a server: ``gunicorn --workers 1 --threads 8 bf2demo.web.wsgi:app`` (see ``deploy/README.md``).

Everything comes from environment variables so the same code runs on a laptop and behind Caddy / nginx:

``BF2VIEW_DEMOS``      folders with the recordings to publish, separated by ``os.pathsep`` (``:`` on Linux)
``BF2VIEW_CACHE``      parse cache, the viewer's game asset store and the high resolution maps (default ``~/.bf2demo-viewer-cache``)
``BF2VIEW_MAPS``       extra folders with ``<level>.jpg`` maps
``BF2VIEW_UPLOAD``     ``1`` to accept uploads (default ``0``: a public server only shows what is in the folders)
``BF2VIEW_MAX_PARSE``  recordings parsed at once (default 2)
``BF2VIEW_MAX_UPLOAD_MB``  largest accepted upload (default 400)
``BF2VIEW_DONATE_TELEGRAM``  Telegram username (``@name``) shown in the support section; empty = no section
``BF2VIEW_DONATE_FILE``  JSON file with the payment methods (wallets, links), see ``deploy/donate.example.json``

Use ONE worker process (threads are fine): the parse jobs and their status live in the process.
"""

from __future__ import annotations

import os

from .app import create_app


def _folders(name: str) -> list:
    return [p for p in os.environ.get(name, "").split(os.pathsep) if p]


app = create_app(
    _folders("BF2VIEW_DEMOS"), os.environ.get("BF2VIEW_CACHE") or None, _folders("BF2VIEW_MAPS"),
    allow_upload=os.environ.get("BF2VIEW_UPLOAD", "0") == "1",
    max_parse=int(os.environ.get("BF2VIEW_MAX_PARSE", "2")),
    max_upload=int(os.environ.get("BF2VIEW_MAX_UPLOAD_MB", "400")) * 1024 * 1024,
    donate_telegram=os.environ.get("BF2VIEW_DONATE_TELEGRAM"),
    donate_file=os.environ.get("BF2VIEW_DONATE_FILE") or None,
)
