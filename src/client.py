"""
HTTP client for the API automation framework.

Session wrapper with response-time enforcement and
structured error reporting.
"""
import logging
import time
from typing import Any

import requests
from requests import Response

from utils.poller import poller

LOG = logging.getLogger(__name__)

CONNECT_TIMEOUT_S = 12.0
READ_TIMEOUT_S = 30.0
REQUEST_TIMEOUT: tuple[float, float] = (CONNECT_TIMEOUT_S, READ_TIMEOUT_S)
REQUEST_RETRIES = 2
RETRY_BACKOFF_S = 1.0


class ApiError(Exception):
    """Raised when an API call returns a non-2xx status."""

    def __init__(self, method: str, url: str, status_code: int, body: str) -> None:
        self.method = method
        self.url = url
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code} {method} {url} — {body[:300]}")


class ApiClient:
    """
    Environment-aware HTTP client.

    Constructed from an environment config dict (base_url, max_response_time).
    Every request is timed; if elapsed > max_response_time the call fails with
    an AssertionError so the threshold never needs to appear in test code.
    """

    def __init__(self, base_url: str, max_response_time: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_response_time = max_response_time
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get(self, path: str, **kwargs: Any) -> Any:
        """GET request — returns parsed JSON body."""
        return self._request("GET", path, **kwargs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        request_kwargs: dict[str, Any] = dict(kwargs)
        request_kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        LOG.info(
            "%s %s (timeout=%s, retries=%d, backoff=%.1fs)",
            method,
            url,
            request_kwargs["timeout"],
            REQUEST_RETRIES,
            RETRY_BACKOFF_S,
        )

        @poller(retries=REQUEST_RETRIES, wait=RETRY_BACKOFF_S)
        def _request_with_retry() -> tuple[Response, float]:
            start = time.monotonic()
            response = self._session.request(method, url, **request_kwargs)
            elapsed = time.monotonic() - start
            return response, elapsed

        response, elapsed = _request_with_retry()

        LOG.info(
            "%s %s → %d (%.3fs)", method, url, response.status_code, elapsed
        )

        self._assert_response_time(elapsed, method, url)
        self._assert_ok(response, method, url)

        return response.json()

    def _assert_response_time(self, elapsed: float, method: str, url: str) -> None:
        assert elapsed <= self.max_response_time, (
            f"Response time {elapsed:.3f}s exceeded threshold "
            f"{self.max_response_time}s for {method} {url}"
        )

    @staticmethod
    def _assert_ok(response: Response, method: str, url: str) -> None:
        if not response.ok:
            raise ApiError(method, url, response.status_code, response.text)
