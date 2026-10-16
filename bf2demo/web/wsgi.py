"""WSGI entry for a server: ``gunicorn --workers 1 --threads 8 bf2demo.web.wsgi:app`` (see ``deploy/README.md``).

Everything comes from environment variables so the same code runs on a laptop and behind Caddy / nginx:

``BF2VIEW_DEMOS``      folders with the recordings to publish, separated by ``os.pathsep`` (``:`` on Linux)
``BF2VIEW_CACHE``      parse cache, the viewer's game asset store and the high resolution maps (default ``~/.bf2demo-viewer-cache``)
``BF2VIEW_MAPS``       extra folders with ``<level>.jpg`` maps
``BF2VIEW_UPLOAD``     ``1`` to accept uploads (default ``0``: a public server only shows what is in the folders)
``BF2VIEW_MAX_PARSE``  recordings parsed at once (default 2)
``BF2VIEW_MAX_UPLOAD_MB``  largest accepted upload (default 400)
``BF2VIEW_DONATE_TELEGRAM``  Telegram username (``@name``) shown in the support section; empty = no section
``BF2VIEW_BEHIND_PROXY``  ``1`` behind Caddy / nginx: the visitor's address (rate limits) comes from X-Forwarded-For
``BF2VIEW_BEHIND_CLOUDFLARE``  ``1`` when Cloudflare is in front: the limits count ``CF-Connecting-IP`` (otherwise every visitor looks like a Cloudflare address)
``BF2VIEW_CLIPS_PER_MIN`` / ``BF2VIEW_UPLOADS_PER_HOUR``  per address limits of the expensive endpoints (default 6 and 6)
``BF2VIEW_DONATE_FILE``  JSON file with the payment methods (wallets, links), see ``deploy/donate.example.json``

A ``bf2view.env`` file in the project folder overrides all of these (see ``_load_env_file``).

Use ONE worker process (threads are fine): the parse jobs and their status live in the process.
"""

from __future__ import annotations

import os

from .app import create_app


def _load_env_file() -> None:
    """``bf2view.env`` in the project folder (or ``BF2VIEW_ENV_FILE``): ``KEY=value`` lines that OVERRIDE the process environment.

    Lets the owner change the settings of a running service without root (edit the file, then ``kill -HUP`` the gunicorn master).
    """
    path = os.environ.get("BF2VIEW_ENV_FILE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "bf2view.env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if key.strip().startswith("BF2VIEW_"):
                    os.environ[key.strip()] = value.strip()


_load_env_file()


def _folders(name: str) -> list:
    return [p for p in os.environ.get(name, "").split(os.pathsep) if p]


app = create_app(
    _folders("BF2VIEW_DEMOS"), os.environ.get("BF2VIEW_CACHE") or None, _folders("BF2VIEW_MAPS"),
    allow_upload=os.environ.get("BF2VIEW_UPLOAD", "0") == "1",
    max_parse=int(os.environ.get("BF2VIEW_MAX_PARSE", "2")),
    max_upload=int(os.environ.get("BF2VIEW_MAX_UPLOAD_MB", "400")) * 1024 * 1024,
    donate_telegram=os.environ.get("BF2VIEW_DONATE_TELEGRAM"),
    donate_file=os.environ.get("BF2VIEW_DONATE_FILE") or None,
    behind_proxy=os.environ.get("BF2VIEW_BEHIND_PROXY", "0") == "1",
    behind_cloudflare=os.environ.get("BF2VIEW_BEHIND_CLOUDFLARE", "0") == "1",
    clips_per_minute=int(os.environ.get("BF2VIEW_CLIPS_PER_MIN", "6")),
    uploads_per_hour=int(os.environ.get("BF2VIEW_UPLOADS_PER_HOUR", "6")),
)
