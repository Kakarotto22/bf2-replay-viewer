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
import subprocess
import sys
import threading
import time
import traceback
from typing import Dict, List, Optional

from ..reader import load_demo
from ..replay import build_replay
from .viewer_format import FORMAT, build_viewer_document


#: what a visitor is told when a recording cannot be shown: plain words, nothing about the server (paths, exception names, limits in use)
PARSE_ERRORS = {
    "unreadable": "This file could not be read as a BF2 recording.",
    "too_large": "This recording is too large for this server to process.",
    "timeout": "This recording took too long to process on this server.",
    "server_error": "The server could not process this recording right now. Please try again later.",
}
#: the file's own verdicts: remembered, a new try would end the same way. A ``server_error`` (the child could not start, crashed) is not.
_FINAL = ("unreadable", "too_large", "timeout")
_EXIT_CODES = {0: "ok", 3: "too_large", 4: "unreadable"}
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse_to_cache(path: str, target: str) -> str:
    """Parse ``path`` and write its viewer document (+ summary) next to ``target``; returns an outcome key of ``PARSE_ERRORS`` or ``"ok"``."""
    try:
        doc = build_viewer_document(build_replay(load_demo(path)))
    except MemoryError:
        return "too_large"
    except ValueError as exc:
        return "too_large" if "larger than" in str(exc) else "unreadable"          # the decompression cap of the reader
    tmp = target + ".tmp"
    try:
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as fh:
            json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"))
        with open(target + ".summary", "w", encoding="utf-8") as fh:
            json.dump(summarise(doc), fh)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return "ok"


def child_main(argv: List[str]) -> int:
    """Entry of the parse child process: ``<path> <target> <memory_mb>``. The exit code tells the parent what happened (``_EXIT_CODES``)."""
    path, target, memory_mb = argv[0], argv[1], int(argv[2])
    if memory_mb > 0:
        try:
            import resource                                       # Linux / macOS: address space cap, a parse that needs more gets MemoryError
            limit = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        except (ImportError, ValueError, OSError):
            pass
    try:
        outcome = _parse_to_cache(path, target)
    except MemoryError:
        outcome = "too_large"
    except Exception:  # noqa: BLE001 - the details stay in the server log
        traceback.print_exc()
        outcome = "unreadable"
    return {v: k for k, v in _EXIT_CODES.items()}[outcome]


def _run_isolated(path: str, target: str, timeout: float, memory_mb: int) -> str:
    """Run :func:`child_main` in a fresh interpreter (``-I``: no environment variables or current folder on the import path), wait up to
    ``timeout`` seconds, kill it after that. A child killed by the kernel (out of memory) counts as too large."""
    code = f"import sys; sys.path.insert(0, {_PACKAGE_ROOT!r}); from bf2demo.web.store import child_main; sys.exit(child_main(sys.argv[1:]))"
    proc = subprocess.Popen([sys.executable, "-I", "-c", code, path, target, str(int(memory_mb))], stdin=subprocess.DEVNULL)
    try:
        exit_code = proc.wait(timeout=timeout if timeout > 0 else None)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return "timeout"
    if exit_code < 0:                                            # SIGKILL from the OOM killer, ...
        return "too_large"
    return _EXIT_CODES.get(exit_code, "server_error")            # 1 = the child itself failed (import, start-up): not the file's fault


def demo_id(path: str) -> str:
    return hashlib.sha1(os.path.abspath(path).lower().encode()).hexdigest()[:16]


def summarise(doc: dict) -> dict:
    demo = doc["demo"]
    humans = [p for p in doc["players"] if not p["is_ai"]]
    # a player who joins and leaves on the same tick never gets a score (None = unknown): such a row must not break the summary
    top = max((r for r in doc["scoreboard"] if r["score"] is not None), key=lambda r: r["score"], default=None)
    return {"map": demo["map"], "mode": demo["mode"], "server": demo["server"], "recorded_at": demo["recorded_at"],
            "duration_s": round((demo["last_tick"] - demo["first_tick"]) / 30), "players": len(doc["players"]),
            "humans": len(humans), "kills": sum(1 for f in doc["feed"] if f["kind"] == "kill"),
            "top_player": top and {"name": top["name"], "score": top["score"]}}


class Store:
    def __init__(self, folders: List[str], cache_dir: str, upload_dir: Optional[str] = None, max_parse: int = 2, quota_mb: int = 0,
                 list_uploads: bool = False, isolate: bool = True, parse_timeout: float = 600, parse_memory_mb: int = 3072):
        self.isolate = isolate                                   # parse in a child process (False: in this process, for debugging)
        self.parse_timeout = parse_timeout                       # seconds before a parse is killed (0 = never)
        self.parse_memory_mb = parse_memory_mb                   # address space of the parse child on Linux (0 = no cap)
        self.retry_after = 60.0                                  # seconds before a server_error may be tried again (the page polls every 1.5 s)
        self.folders = [os.path.abspath(f) for f in folders]
        self.cache_dir = os.path.abspath(cache_dir)
        self.upload_dir = os.path.abspath(upload_dir or os.path.join(cache_dir, "uploads"))
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.upload_dir, exist_ok=True)
        self._jobs: Dict[str, dict] = {}
        self._slots = threading.BoundedSemaphore(max(1, max_parse))      # recordings parsed at the same time (a big one takes minutes of CPU)
        self._lock = threading.Lock()
        self.quota = max(0, int(quota_mb)) * 1024 * 1024        # 0 = no limit; see enforce_quota
        self.list_uploads = list_uploads                         # False: an uploaded recording is reachable by its link only, not shown to everybody
        self._quota_lock = threading.Lock()
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

    def _is_upload(self, path: str) -> bool:
        return os.path.abspath(path).startswith(self.upload_dir + os.sep)

    def _cache_path(self, path: str) -> str:
        st = os.stat(path)
        key = hashlib.sha1(f"{FORMAT}|{os.path.abspath(path).lower()}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:20]
        return os.path.join(self.cache_dir, key + ".json.gz")

    def listing(self) -> List[dict]:
        items = []
        for did, path in self.scan().items():
            if not self.list_uploads and self._is_upload(path):
                continue
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
            job = self._jobs.get(did) or {}
            # a failure is final for this process: the page polls every 1.5 s, and starting the parse again on each poll answered "parsing"
            # forever (the visitor never saw the error) while the server parsed the same file over and over
            if status == "error" and (job.get("final") or time.monotonic() - job.get("at", 0) < self.retry_after):
                return {"status": "error", "error": job.get("error"), "reason": job.get("reason")}
            if status in ("new", "error"):                       # error here = a server_error at least retry_after s old: try again
                self._jobs[did] = {"state": "running", "error": None}
                threading.Thread(target=self._parse, args=(did, path), daemon=True).start()
                return {"status": "parsing"}
        job = self._jobs.get(did) or {}
        return {"status": status, "error": job.get("error"), "reason": job.get("reason")}

    def _parse(self, did: str, path: str) -> None:
        with self._slots:
            self._parse_now(did, path)

    def _parse_now(self, did: str, path: str) -> None:
        """Parse in a CHILD process (see ``isolate``): a huge or hostile recording can use up its own memory / time limit and die, never the
        web worker (an in-process parse held the GIL for minutes, pushed the worker into swap and kept its peak memory after it finished)."""
        target = self._cache_path(path)
        try:
            if self.isolate:
                outcome = _run_isolated(path, target, self.parse_timeout, self.parse_memory_mb)
            else:
                outcome = _parse_to_cache(path, target)
        except Exception:  # noqa: BLE001 - logged, a generic message goes to the client
            traceback.print_exc()
            outcome = "server_error" if self.isolate else "unreadable"
        if outcome == "ok":
            self._jobs[did] = {"state": "done", "error": None}
        else:
            print(f"bf2view: parse of {did} failed: {outcome}", file=sys.stderr, flush=True)       # the server log only: never the path or the error text
            self._jobs[did] = {"state": "error", "error": PARSE_ERRORS.get(outcome, PARSE_ERRORS["server_error"]), "reason": outcome,
                               "final": outcome in _FINAL, "at": time.monotonic()}

    def enforce_quota(self) -> int:
        """Keep the uploads and their parse results under ``quota``: delete the OLDEST uploaded recording (with its parsed document) until they fit.

        Only the upload folder is ever cleaned. The recordings published in ``--demos`` folders, their parsed documents and the viewer's asset
        store are never touched. Parse results that belong to no recording any more (an old format, a deleted upload) are removed first.
        Returns the number of files deleted.
        """
        if not self.quota:
            return 0
        removed = 0
        with self._quota_lock:
            current = self.scan(max_age=0)
            known = set()
            for path in current.values():
                try:
                    base = self._cache_path(path)
                except OSError:
                    continue
                known.update((base, base + ".summary"))
            cutoff = time.time() - 3600                          # a document being written right now has a fresh .tmp: leave anything younger than an hour
            for name in os.listdir(self.cache_dir):
                full = os.path.join(self.cache_dir, name)
                if name.endswith((".json.gz", ".json.gz.summary")) and full not in known and os.path.isfile(full) and os.path.getmtime(full) < cutoff:
                    os.remove(full)
                    removed += 1
            uploads = []
            for name in os.listdir(self.upload_dir):
                path = os.path.join(self.upload_dir, name)
                if not (name.lower().endswith(".bf2demo") and os.path.isfile(path)):
                    continue
                files = [path] + [f for f in (self._cache_path(path), self._cache_path(path) + ".summary") if os.path.isfile(f)]
                uploads.append((os.path.getmtime(path), demo_id(path), files, sum(os.path.getsize(f) for f in files)))
            total = sum(item[3] for item in uploads)
            for mtime, did, files, size in sorted(uploads):
                if total <= self.quota:
                    break
                if (self._jobs.get(did) or {}).get("state") == "running":
                    continue                                       # never delete what is being parsed
                for f in files:
                    os.remove(f)
                    removed += 1
                total -= size
            if removed:
                self._scan = None
        return removed

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
