"""Demo library + parse cache.

Demos live in the configured folders (``--demos``) or in the upload folder. A client only ever names a demo by an opaque
id (hash of the file path), never by a path. Parsing is slow (seconds to minutes), so the compact document is parsed in a
background thread and cached on disk as gzip JSON keyed by path, size and mtime.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import threading
import time
import traceback
from typing import Dict, List, Optional

from ..reader import load_demo
from ..replay import build_replay
from .viewer_format import FORMAT, build_viewer_document


def demo_id(path: str) -> str:
    return hashlib.sha1(os.path.abspath(path).lower().encode()).hexdigest()[:16]


def summarise(doc: dict) -> dict:
    demo = doc["demo"]
    humans = [p for p in doc["players"] if not p["is_ai"]]
    top = max(doc["scoreboard"], key=lambda r: r["score"], default=None)
    return {"map": demo["map"], "mode": demo["mode"], "server": demo["server"], "recorded_at": demo["recorded_at"],
            "duration_s": round((demo["last_tick"] - demo["first_tick"]) / 30), "players": len(doc["players"]),
            "humans": len(humans), "kills": sum(1 for f in doc["feed"] if f["kind"] == "kill"),
            "top_player": top and {"name": top["name"], "score": top["score"]}}


class Store:
    def __init__(self, folders: List[str], cache_dir: str, upload_dir: Optional[str] = None, max_parse: int = 2):
        self.folders = [os.path.abspath(f) for f in folders]
        self.cache_dir = os.path.abspath(cache_dir)
        self.upload_dir = os.path.abspath(upload_dir or os.path.join(cache_dir, "uploads"))
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.upload_dir, exist_ok=True)
        self._jobs: Dict[str, dict] = {}
        self._slots = threading.BoundedSemaphore(max(1, max_parse))      # recordings parsed at the same time (a big one takes minutes of CPU)
        self._lock = threading.Lock()
        self._scan: Optional[Dict[str, str]] = None
        self._scan_time = 0.0

    # --- library -----------------------------------------------------------------------------------------------------
    def scan(self, max_age: float = 5.0) -> Dict[str, str]:
        """Demo id -> path of every .bf2demo in the folders; the walk is cached for a few seconds (the page polls while parsing)."""
        if self._scan is not None and time.monotonic() - self._scan_time < max_age:
            return self._scan
        found: Dict[str, str] = {}
        for folder in self.folders + [self.upload_dir]:
            for root, _, files in os.walk(folder):
                for name in files:
                    if name.lower().endswith(".bf2demo"):
                        path = os.path.join(root, name)
                        found[demo_id(path)] = path
        self._scan, self._scan_time = found, time.monotonic()
        return found

    def _cache_path(self, path: str) -> str:
        st = os.stat(path)
        key = hashlib.sha1(f"{FORMAT}|{os.path.abspath(path).lower()}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:20]
        return os.path.join(self.cache_dir, key + ".json.gz")

    def listing(self) -> List[dict]:
        items = []
        for did, path in self.scan().items():
            st = os.stat(path)
            item = {"id": did, "name": os.path.basename(path), "size": st.st_size, "mtime": int(st.st_mtime),
                    "status": self.status(did, path)}
            summary = self._read_summary(path)
            if summary:
                item["summary"] = summary
            items.append(item)
        items.sort(key=lambda i: -i["mtime"])
        return items

    def _read_summary(self, path: str) -> Optional[dict]:
        try:
            with open(self._cache_path(path) + ".summary", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    # --- parsing -----------------------------------------------------------------------------------------------------
    def status(self, did: str, path: str) -> str:
        job = self._jobs.get(did)
        if job and job["state"] == "running":
            return "parsing"
        if os.path.isfile(self._cache_path(path)):
            return "ready"
        if job and job["state"] == "error":
            return "error"
        return "new"

    def resolve(self, did: str) -> Optional[str]:
        return self.scan().get(did)

    def request(self, did: str) -> dict:
        """Start parsing when needed; returns ``{"status": ..., "error": ...}``."""
        path = self.resolve(did)
        if path is None:
            return {"status": "missing"}
        with self._lock:
            status = self.status(did, path)
            if status in ("new", "error"):
                self._jobs[did] = {"state": "running", "error": None}
                threading.Thread(target=self._parse, args=(did, path), daemon=True).start()
                return {"status": "parsing"}
        job = self._jobs.get(did) or {}
        return {"status": status, "error": job.get("error")}

    def _parse(self, did: str, path: str) -> None:
        with self._slots:
            self._parse_now(did, path)

    def _parse_now(self, did: str, path: str) -> None:
        try:
            doc = build_viewer_document(build_replay(load_demo(path)))
            target = self._cache_path(path)
            tmp = target + ".tmp"
            with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as fh:
                json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"))
            with open(target + ".summary", "w", encoding="utf-8") as fh:
                json.dump(summarise(doc), fh)
            os.replace(tmp, target)
            self._jobs[did] = {"state": "done", "error": None}
        except Exception as exc:  # noqa: BLE001 - reported to the client
            traceback.print_exc()
            self._jobs[did] = {"state": "error", "error": f"could not read this recording ({type(exc).__name__}); details are in the server log"}   # no paths or internals to visitors

    def warm(self, say=print) -> int:
        """Parse every recording that is not cached yet, one after the other (``bf2view --warm``: run it when publishing, so visitors never wait)."""
        todo = [(did, path) for did, path in self.scan(max_age=0).items() if self.status(did, path) in ("new", "error")]
        for number, (did, path) in enumerate(todo, 1):
            say(f"[{number}/{len(todo)}] {os.path.basename(path)} ...")
            started = time.monotonic()
            self._parse_now(did, path)
            job = self._jobs.get(did) or {}
            say(f"    {job.get('error') or 'ok'} ({time.monotonic() - started:.0f} s)")
        return len(todo)

    def cached_file(self, did: str) -> Optional[str]:
        path = self.resolve(did)
        if path and os.path.isfile(self._cache_path(path)):
            return self._cache_path(path)
        return None
