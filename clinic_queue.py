"""The clinic queue itself: patients join at the back, staff call from the front."""

import threading
import time
from collections import deque


class ClinicQueue:
    def __init__(self, clock=time.monotonic, default_minutes=5.0, sample_size=5):
        self._clock = clock
        self._default_minutes = default_minutes
        self._sample_size = sample_size
        self._changed = threading.Condition()
        self._reset_state()

    def _reset_state(self):
        self._waiting = deque()          # ticket numbers, front = next to be called
        self._next_number = 1
        self._serving = None             # ticket currently with staff
        self._serving_since = None
        # How long the most recent patients took, in seconds.
        self._durations = deque(maxlen=self._sample_size)
        self._version = getattr(self, "_version", 0) + 1

    def _notify(self):
        self._version += 1
        self._changed.notify_all()

    def join(self):
        """Add a patient to the back of the queue and return their ticket number."""
        with self._changed:
            number = self._next_number
            self._next_number += 1
            self._waiting.append(number)
            self._notify()
            return number

    def call_next(self):
        """Finish the current patient and call the next one. Returns the new ticket, or None."""
        with self._changed:
            now = self._clock()
            if self._serving is not None:
                self._durations.append(now - self._serving_since)
            if self._waiting:
                self._serving = self._waiting.popleft()
                self._serving_since = now
            else:
                self._serving = None
                self._serving_since = None
            self._notify()
            return self._serving

    def reset(self):
        with self._changed:
            self._reset_state()
            self._notify()

    def minutes_per_patient(self):
        """Average time recent patients took, or the default before anyone has been seen."""
        if not self._durations:
            return self._default_minutes
        return sum(self._durations) / len(self._durations) / 60

    def snapshot(self):
        with self._changed:
            return self._snapshot()

    def _snapshot(self):
        return {
            "serving": self._serving,
            "waiting": list(self._waiting),
            "last_issued": self._next_number - 1,
            "minutes_per_patient": round(self.minutes_per_patient(), 2),
            "estimate_is_default": not self._durations,
        }

    def wait_for_change(self, since_version, timeout):
        """Block until the queue changes after `since_version`.

        Returns (snapshot, version), or (None, since_version) if nothing changed before the timeout.
        """
        with self._changed:
            self._changed.wait_for(lambda: self._version != since_version, timeout)
            if self._version == since_version:
                return None, since_version
            return self._snapshot(), self._version
