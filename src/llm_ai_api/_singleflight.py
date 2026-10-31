"""Coordinate cache misses across threads and asyncio event loops."""

import asyncio
import threading
from contextlib import asynccontextmanager, contextmanager

from .cache import cache_key

_lock = threading.Lock()
_flights = {}


def _key(client, body):
    if client.cache is None:
        return None
    try:
        return cache_key(client.provider, body, client._cache_context(), client._api_key)
    except Exception:
        return None


def _enter(key):
    with _lock:
        flight = _flights.get(key)
        if flight is None:
            flight = (threading.Event(), [], threading.get_ident(), None)
            _flights[key] = flight
            return flight, True
        return flight, False


def _leave(key, flight):
    with _lock:
        del _flights[key]
        flight[0].set()
        waiters = flight[1][:]
    for loop, future in waiters:
        try:
            loop.call_soon_threadsafe(_wake, future)
        except RuntimeError:
            pass


def _wake(future):
    if not future.done():
        future.set_result(None)


@contextmanager
def singleflight(client, body):
    key = _key(client, body)
    if key is None:
        yield
        return
    while True:
        flight, owner = _enter(key)
        if owner:
            break
        if flight[2] == threading.get_ident():
            yield
            return
        flight[0].wait()
    try:
        yield
    finally:
        if flight is not None:
            _leave(key, flight)


@asynccontextmanager
async def async_singleflight(client, body):
    key = _key(client, body)
    if key is None:
        yield
        return
    loop = asyncio.get_running_loop()
    while True:
        with _lock:
            flight = _flights.get(key)
            if flight is None:
                flight = (threading.Event(), [], threading.get_ident(), asyncio.current_task())
                _flights[key] = flight
                break
            if flight[3] is asyncio.current_task():
                flight = None
                break
            future = loop.create_future()
            waiter = (loop, future)
            flight[1].append(waiter)
        try:
            await future
        finally:
            with _lock:
                if waiter in flight[1]:
                    flight[1].remove(waiter)
    try:
        yield
    finally:
        if flight is not None:
            _leave(key, flight)
