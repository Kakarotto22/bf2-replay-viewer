"""Protection of the expensive endpoints of a public server: a per-address rate limit and a cap on how many run at the same time.

Cutting a clip loads a whole recording and uploading writes to the disk, so one visitor in a loop could keep the server busy for everybody. The
limits are kept in the process (the viewer runs as ONE worker process, see ``wsgi.py``), which is enough for a demo site; a proxy-level limit
is still better against a flood of plain requests.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict


class RateLimit:
    """At most ``count`` events per ``seconds`` for each key (an address); ``hit`` returns the seconds to wait, or 0 when the event is allowed."""

    def __init__(self, count: int, seconds: float):
        self.count, self.seconds = count, seconds
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        with self._lock:
            events = self._events[key]
            while events and now - events[0] >= self.seconds:
                events.popleft()
            if len(events) >= self.count:
                return int(self.seconds - (now - events[0])) + 1
            events.append(now)
            if len(self._events) > 4096:                      # forget idle addresses so the table cannot grow without limit
                for stale in [k for k, e in self._events.items() if not e or now - e[-1] >= self.seconds]:
                    del self._events[stale]
            return 0
