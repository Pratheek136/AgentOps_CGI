"""In-process event bus that fans out to SSE subscribers. Thread-safe publish."""
from __future__ import annotations

import asyncio
import itertools
import json
import threading
import time
from collections import deque
from typing import Any

_seq = itertools.count(1)


class EventBus:
    def __init__(self, history: int = 500) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subs: set[asyncio.Queue] = set()
        self._recent: deque[dict] = deque(maxlen=history)
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, type_: str, data: Any = None) -> dict:
        evt = {"id": next(_seq), "type": type_, "ts": time.time(), "data": data}
        with self._lock:
            self._recent.append(evt)
            subs = list(self._subs)
        if self._loop is not None:
            for q in subs:
                self._loop.call_soon_threadsafe(_put, q, evt)
        return evt

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs.discard(q)

    def recent(self, n: int = 100) -> list[dict]:
        with self._lock:
            return list(self._recent)[-n:]


def _put(q: asyncio.Queue, evt: dict) -> None:
    try:
        q.put_nowait(evt)
    except asyncio.QueueFull:
        pass


def sse_format(evt: dict) -> str:
    return f"id: {evt['id']}\nevent: {evt['type']}\ndata: {json.dumps(evt, default=str)}\n\n"


bus = EventBus()
