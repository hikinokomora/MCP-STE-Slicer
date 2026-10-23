"""Event bus between the agent and the SPA (long polling)."""
import threading
import time


class EventBus:
    def __init__(self, max_events=2000):
        self._events = []
        self._next_id = 1
        self._cond = threading.Condition()
        self._max = max_events

    def emit(self, kind, **data):
        with self._cond:
            event = {"id": self._next_id, "type": kind, "ts": time.time()}
            event.update(data)
            self._next_id += 1
            self._events.append(event)
            if len(self._events) > self._max:
                self._events = self._events[-self._max:]
            self._cond.notify_all()
            return event

    def since(self, after_id, wait=25.0):
        deadline = time.time() + wait
        with self._cond:
            while True:
                items = [e for e in self._events if e["id"] > after_id]
                remaining = deadline - time.time()
                if items or remaining <= 0:
                    return items
                self._cond.wait(remaining)

    def last_id(self):
        with self._cond:
            return self._next_id - 1

    def clear(self):
        with self._cond:
            self._events = []
            self.emit("reset")
