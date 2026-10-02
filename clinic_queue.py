"""The clinic queue itself: patients join at the back, staff call from the front.

The live queue is an in-memory deque, so reading it is instant. Every change is written to SQLite
first, so if the server crashes or restarts, the queue is rebuilt from the database on startup.
"""

import secrets
import sqlite3
import threading
import time
from collections import deque

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    number      INTEGER PRIMARY KEY,
    joined_at   REAL NOT NULL,
    called_at   REAL,   -- when staff called this ticket
    finished_at REAL    -- when staff moved on to the next ticket
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class ClinicQueue:
    def __init__(self, db_path=":memory:", clock=time.time, default_minutes=5.0, sample_size=5):
        self._clock = clock
        self._default_minutes = default_minutes
        self._sample_size = sample_size
        self._changed = threading.Condition()
        self._version = 0
        # One connection shared by all threads; every use happens while holding self._changed.
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._load()

    def _load(self):
        """Rebuild the in-memory queue from the database."""
        db = self._db
        self._waiting = deque(n for (n,) in db.execute(
            "SELECT number FROM tickets WHERE called_at IS NULL ORDER BY number"))
        serving = db.execute(
            "SELECT number, called_at FROM tickets WHERE called_at IS NOT NULL AND finished_at IS NULL").fetchone()
        self._serving, self._serving_since = serving or (None, None)
        recent = db.execute(
            "SELECT finished_at - called_at FROM tickets WHERE finished_at IS NOT NULL "
            "ORDER BY finished_at DESC LIMIT ?", (self._sample_size,)).fetchall()
        # How long the most recent patients took, in seconds, oldest first.
        self._durations = deque((d for (d,) in reversed(recent)), maxlen=self._sample_size)
        self._next_number = db.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM tickets").fetchone()[0]

        row = db.execute("SELECT value FROM settings WHERE key = 'queue_id'").fetchone()
        if row is None:
            self._new_queue_id()
        else:
            self._queue_id = row[0]

    def _new_queue_id(self):
        # Ticket numbers restart at 1 after a reset; this id tells an old "ticket 3" apart from a new one.
        self._queue_id = secrets.token_hex(4)
        with self._db:
            self._db.execute("INSERT OR REPLACE INTO settings VALUES ('queue_id', ?)", (self._queue_id,))

    def _notify(self):
        self._version += 1
        self._changed.notify_all()

    def join(self):
        """Add a patient to the back of the queue and return their ticket number."""
        with self._changed:
            number = self._next_number
            with self._db:
                self._db.execute("INSERT INTO tickets (number, joined_at) VALUES (?, ?)", (number, self._clock()))
            self._next_number += 1
            self._waiting.append(number)
            self._notify()
            return number

    def call_next(self):
        """Finish the current patient and call the next one. Returns the new ticket, or None."""
        with self._changed:
            now = self._clock()
            # Save to disk first; only update memory once the database write has succeeded.
            with self._db:
                if self._serving is not None:
                    self._db.execute("UPDATE tickets SET finished_at = ? WHERE number = ?", (now, self._serving))
                if self._waiting:
                    self._db.execute("UPDATE tickets SET called_at = ? WHERE number = ?", (now, self._waiting[0]))

            if self._serving is not None:
                self._durations.append(max(0.0, now - self._serving_since))
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
            with self._db:
                self._db.execute("DELETE FROM tickets")
            self._new_queue_id()
            self._load()
            self._notify()

    def close(self):
        with self._changed:
            self._db.close()

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
            "queue_id": self._queue_id,
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
