"""
Polling / retry decorator.

Uses raise ... from syntax for exception chaining (no `future` dependency).
"""
import functools
import logging
import time
from collections.abc import Callable
from typing import Any

LOG = logging.getLogger(__name__)


def poller(
    timeout: float = 60,
    wait: float = 0.5,
    retries: int | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator that adds timeout-based or retry-based polling.

    Usage:
        @poller(timeout=30, wait=1)
        def wait_for_condition():
            assert some_api_call() == expected_value

        @poller(retries=5, wait=2)
        def retry_operation():
            assert flaky_call() is True
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if retries is not None:
                return _retry_poller(fn, retries, wait, *args, **kwargs)
            return _timeout_poller(fn, timeout, wait, *args, **kwargs)

        return wrapper

    return decorator


def _timeout_poller(
    fn: Callable[..., Any],
    timeout: float,
    wait: float,
    *args: Any,
    **kwargs: Any,
) -> Any:
    start = time.monotonic()
    attempt = 0
    last_exc: BaseException | None = None

    while (time.monotonic() - start) < timeout:
        remaining = timeout - (time.monotonic() - start)
        LOG.info(
            "%s.%s(): attempt %d, time remaining %.2fs",
            fn.__module__, fn.__name__, attempt + 1, remaining,
        )
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            LOG.info("Exception in %s(): %r — retrying in %.1fs", fn.__name__, exc, wait)
        time.sleep(wait)
        attempt += 1

    if last_exc is not None:
        raise last_exc
    return False


def _retry_poller(
    fn: Callable[..., Any],
    retries: int,
    wait: float,
    *args: Any,
    **kwargs: Any,
) -> Any:
    last_exc: BaseException | None = None

    for attempt in range(retries):
        LOG.info("Attempt %d/%d: %s()", attempt + 1, retries, fn.__name__)
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            LOG.info("Exception in %s(): %r — retrying in %.1fs", fn.__name__, exc, wait)
        time.sleep(wait)

    if last_exc is not None:
        raise last_exc
    return False
