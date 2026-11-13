"""Holding a lease on a claim or a run for as long as the work goes on."""

import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import httpx

from agent import client

RENEW_SECONDS = 5.0


def keep_renewing(path: str, worker: str, stop: threading.Event) -> None:
    """Renew the lease until told to stop; a missed renewal is tried again next time."""
    with client.backend() as backend:
        while not stop.wait(RENEW_SECONDS):
            try:
                backend.post(path, json={"worker": worker})
            except httpx.HTTPError:
                continue


@contextmanager
def holding(path: str, worker: str | None = None) -> Iterator[bool]:
    """Take the lease at this path and say whether we got it; give it up at the end.

    A worker that already holds the lease, such as one that took a sent-back claim,
    keeps it.
    """
    worker = worker or uuid.uuid4().hex
    with client.backend() as backend:
        if not backend.post(path, json={"worker": worker}).is_success:
            yield False
            return
        stop = threading.Event()
        renewing = threading.Thread(
            target=keep_renewing, args=(path, worker, stop), daemon=True
        )
        renewing.start()
        try:
            yield True
        finally:
            stop.set()
            renewing.join()
            backend.post(f"{path}/release", json={"worker": worker})
