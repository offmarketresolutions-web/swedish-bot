"""The cache has to be shared between gunicorn workers.

Django's default is LocMemCache — per-process — and the project ran on it. Two things
quietly depended on a cache that was actually three separate caches:

  * chat/views.py rate-limits with it, so RATE_LIMIT_SESSION=20 per IP was really up to
    60 across three workers, and reset to zero on every deploy.
  * kb/semantic.py caches embedding vectors, so every worker re-paid the warm-up — 3.1s
    of four embedding round trips on a cold specialist turn.

conftest swaps in a local cache for the test run, so this file reads the real settings
module directly. Otherwise the swap would hide exactly the regression it must catch.
"""
import importlib

import pytest

# Per-process backends. Any of these in production puts the rate limiter back to
# counting once per worker.
_PER_PROCESS = ("locmem", "dummy", "filebased")


@pytest.fixture
def production_caches():
    settings_mod = importlib.import_module("config.settings")
    return getattr(settings_mod, "CACHES", None)


def test_production_configures_a_cache_at_all(production_caches):
    assert production_caches, (
        "No CACHES setting means Django falls back to per-process LocMemCache.")


def test_production_cache_is_shared_between_workers(production_caches):
    backend = production_caches["default"]["BACKEND"].lower()
    assert not any(marker in backend for marker in _PER_PROCESS), (
        f"{backend} is per-process: three gunicorn workers would keep three separate "
        "rate-limit counters, so RATE_LIMIT_SESSION would not mean what it says.")


def test_rate_limit_counter_survives_a_restart(production_caches):
    """A limiter that forgets on deploy is not a limiter. The DB cache outlives the
    process; LocMem and the dummy backend do not."""
    backend = production_caches["default"]["BACKEND"].lower()
    assert "db" in backend or "memcached" in backend or "redis" in backend, backend


def test_the_rate_limiter_really_uses_the_django_cache():
    """If the limiter stops reading the cache, the tests above stop meaning anything."""
    import inspect

    from chat import views
    src = inspect.getsource(views._rate_limited if hasattr(views, "_rate_limited")
                            else views)
    assert "cache.get" in src and "cache.set" in src, (
        "chat.views no longer rate-limits through the Django cache — this file's "
        "guarantees are about the wrong thing now.")
