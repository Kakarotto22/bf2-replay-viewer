"""Flask application: JSON API + static single-page viewer."""

from __future__ import annotations

import json
import os
import re
import threading
from typing import List, Optional

from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory

from . import donate as donations, maps
from .limits import RateLimit
from .assets import GameAssets
from .store import Store, demo_id

STATIC = os.path.join(os.path.dirname(__file__), "static")
MAX_UPLOAD = 400 * 1024 * 1024


def create_app(folders: List[str], cache_dir: Optional[str] = None, map_folders: Optional[List[str]] = None, allow_upload: bool = True,
               max_parse: int = 2, max_upload: int = MAX_UPLOAD, donate_telegram: Optional[str] = None,
               donate_file: Optional[object] = None, behind_proxy: bool = False, clips_per_minute: int = 6, uploads_per_hour: int = 6) -> Flask:
    """``allow_upload=False`` is the public setting: the library is whatever is in ``folders``. ``max_parse`` limits the recordings parsed at once.
    The support section shows ``donate_telegram`` and the payment methods of ``donate_file`` (:mod:`bf2demo.web.donate`); it is hidden while both are empty."""
    cache_dir = cache_dir or os.path.join(os.path.expanduser("~"), ".bf2demo-viewer-cache")
    # no option needed: a donate.json in the project folder or in the cache folder is picked up by itself
    project = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    donate = donations.build(donate_telegram, donations.default_file(project, os.path.join(project, "local"), cache_dir) if donate_file is None else donate_file or None)    # False = never look
    app = Flask(__name__, static_folder=None)
    if behind_proxy:                                    # Caddy / nginx in front: the visitor's address is in X-Forwarded-For (one proxy)
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    clip_limit, upload_limit = RateLimit(clips_per_minute, 60), RateLimit(uploads_per_hour, 3600)
    clip_slot = threading.BoundedSemaphore(1)           # one clip is built at a time: it loads the whole recording

    def too_many(limit):
        wait = limit.hit(request.remote_addr or "?")
        if wait:
            response = jsonify({"error": f"too many requests, try again in {wait} s"})
            response.status_code = 429
            response.headers["Retry-After"] = str(wait)
            abort(response)
    app.config["MAX_CONTENT_LENGTH"] = max_upload
    store = Store(folders, cache_dir, max_parse=max_parse)
    # high resolution maps made by the user (BF2 Editor mega map renders, downloaded packs): <level>.jpg / .png, they win over everything
    map_folders = [os.path.abspath(f) for f in (map_folders or [])] + [os.path.join(os.path.abspath(cache_dir), "hd_maps")]
    app.config["STORE"] = store
    backdrops = {}
    root = maps.game_root()
    game_store = os.path.join(os.path.abspath(cache_dir), "game")          # the viewer's own source: only what the page draws, built from the install
    assets = GameAssets(root, game_store)
    level_dir = os.path.join(game_store, "levels")

    @app.after_request
    def headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/static/<path:name>")
    def static_file(name):
        return send_from_directory(STATIC, name)

    @app.get("/api/demos")
    def demos():
        return jsonify(store.listing())

    @app.post("/api/demos/<did>/parse")
    def parse(did):
        result = store.request(did)
        if result["status"] == "missing":
            abort(404)
        return jsonify(result)

    @app.get("/api/demos/<did>")
    def document(did):
        path = store.cached_file(did)
        if path is None:
            result = store.request(did)
            if result["status"] == "missing":
                abort(404)
            return jsonify(result), 202
        # the cache file name already hashes the format version: an ETag + revalidation lets a browser reuse a document only while it is
        # still the current format (a fixed max-age kept serving a stale document with old headings after the format changed)
        response = send_file(path, mimetype="application/json", etag=True, conditional=True, max_age=0)
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/api/demos/<did>/clip")
    def clip(did):
        """A cut of the recording as a download: ``?start=<tick>&end=<tick>&lead=<seconds>`` (ticks are absolute demo ticks)."""
        from ..clip import make_clip
        from ..reader import load_demo
        too_many(clip_limit)
        path = store.resolve(did)
        if path is None:
            abort(404)
        if not clip_slot.acquire(blocking=False):
            response = jsonify({"error": "another clip is being built, try again in a moment"})
            response.status_code = 503
            response.headers["Retry-After"] = "5"
            abort(response)
        try:
            return _clip_response(path, make_clip, load_demo)
        finally:
            clip_slot.release()

    def _clip_response(path, make_clip, load_demo):
        demo = load_demo(path)
        ticks = [p.tick for p in demo.packets if p.tick >= 0]
        if not ticks:
            abort(400, "empty recording")
        lo, hi = min(ticks), max(ticks)
        try:
            start = request.args.get("start", type=int)
            end = request.args.get("end", type=int)
            lead = min(max(request.args.get("lead", 8.0, type=float), 0.0), 120.0)
        except ValueError:
            abort(400)
        start = None if start is None else min(max(start, lo), hi)
        end = None if end is None else min(max(end, lo), hi)
        if start is not None and end is not None and end <= start:
            abort(400, "end must be after start")
        data = make_clip(demo, start, end, lead, request.args.get("signature", "1") != "0")
        label = lambda t: "full" if t is None else f"{(t - lo) // 30 // 60:02d}-{(t - lo) // 30 % 60:02d}"
        stem = "".join(ch for ch in os.path.splitext(os.path.basename(path))[0] if ch.isalnum() or ch in "_-")[:60] or "demo"
        name = f"{stem}_clip_{label(start)}_{label(end)}.bf2demo"
        return Response(data, mimetype="application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/api/upload")
    def upload():
        if not allow_upload:
            abort(403, "uploads are disabled on this server")
        too_many(upload_limit)
        file = request.files.get("file")
        if file is None or not file.filename.lower().endswith(".bf2demo"):
            abort(400, "expected a .bf2demo file")
        name = os.path.basename(file.filename).replace("\\", "_").replace("/", "_")
        path = os.path.join(store.upload_dir, name)
        file.save(path)
        store.scan(max_age=0)
        return jsonify({"id": demo_id(path)})

    @app.get("/api/game")
    def game():
        return jsonify({"installed": assets.tables() is not None, "upload": allow_upload, "donate": donate})

    @app.get("/api/hud/<path:icon>.png")
    def hud_icon(icon):
        data = assets.icon_png(icon)      # only names present in the archive index (or already in the store) resolve
        if data is None:
            abort(404)
        return Response(data, mimetype="image/png", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/api/assets/tables")
    def tables():
        """Vehicle / kit icons and names and the few strings the page shows, in one document."""
        doc = assets.tables()
        if doc is None:
            abort(404)
        return jsonify(doc)

    @app.get("/api/fonts/<name>.png")
    def font_png(name):
        font = assets.font(name)
        if font is None:
            abort(404)
        return Response(font[0], mimetype="image/png", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/api/fonts/<name>.json")
    def font_json(name):
        font = assets.font(name)
        if font is None:
            abort(404)
        return jsonify(font[1])

    @app.get("/api/maps/<level>")
    def backdrop_info(level):
        item = _backdrop(level)
        clean = "".join(ch for ch in level if ch.isalnum() or ch in "_-")
        return jsonify({"available": item is not None, "world_size": item and item["world_size"], "uncapturable": item["uncapturable"] if item else [],
                        "rules": item["rules"] if item else None})

    @app.get("/api/maps/<level>.png")
    def backdrop_png(level):
        item = _backdrop(level)
        if item is None:
            abort(404)
        return Response(item["png"], mimetype="image/png", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/api/maps/<level>/hd.jpg")
    def backdrop_hd(level):
        """The stitched high resolution terrain (built once from the game's colour tiles, then served from the cache folder)."""
        level = "".join(ch for ch in level if ch.isalnum() or ch in "_-").lower()
        for folder in map_folders:
            for ext, mime in ((".jpg", "image/jpeg"), (".jpeg", "image/jpeg"), (".png", "image/png")):
                custom = os.path.join(folder, level + ext)
                if os.path.isfile(custom):
                    return send_file(custom, mimetype=mime, etag=True, conditional=True, max_age=0)
        folder = os.path.join(store.cache_dir, "maps")
        path = os.path.join(folder, f"{level}.hd4.jpg")
        if not os.path.isfile(path):
            data = maps.hd_map(level)
            if data is None:
                abort(404)
            os.makedirs(folder, exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
        return send_file(path, mimetype="image/jpeg", etag=True, conditional=True, max_age=0)

    def _backdrop(level):
        """The level's minimap and facts, built from the game once and kept in the store (``levels/<level>.png|json``)."""
        level = "".join(ch for ch in level if ch.isalnum() or ch in "_-").lower()
        if level not in backdrops:
            png_path, json_path = os.path.join(level_dir, level + ".png"), os.path.join(level_dir, level + ".json")
            item = None
            if os.path.isfile(png_path) and os.path.isfile(json_path):
                with open(png_path, "rb") as fh, open(json_path, encoding="utf-8") as jh:
                    meta = json.load(jh)
                    item = {"png": fh.read(), "world_size": meta["world_size"], "uncapturable": meta.get("uncapturable", []), "rules": meta.get("rules")}
                if item["rules"] is None and maps.game_root():                 # a store written before the ticket rules existed
                    item["rules"] = maps.ticket_rules(level)
                    _save_level(level, item)
            else:
                item = maps.load_backdrop(level)
                if item is not None:
                    item["uncapturable"] = maps.uncapturable_points(level)
                    item["rules"] = maps.ticket_rules(level)
                    os.makedirs(level_dir, exist_ok=True)
                    with open(png_path, "wb") as fh:
                        fh.write(item["png"])
                    _save_level(level, item)
            backdrops[level] = item
        return backdrops[level]

    def _save_level(level, item):
        with open(os.path.join(level_dir, level + ".json"), "w", encoding="utf-8") as jh:
            json.dump({"world_size": item["world_size"], "uncapturable": item["uncapturable"], "rules": item["rules"]}, jh)

    return app
