"""HTML fetching for AccuWeather, with a browser TLS fingerprint.

AccuWeather sits behind Akamai Bot Manager, which judges a client by its TLS and
HTTP/2 fingerprint as much as by its headers. aiohttp's fingerprint does not look
like a browser, so on many networks every request comes back 403 no matter which
User-Agent is sent — that is the "AccuWeather từ chối yêu cầu (HTTP 403)" case.

curl_cffi speaks through curl-impersonate, which reproduces Chrome's TLS
handshake, so the same requests succeed. It is a binary wheel, so it may be
missing on an unusual platform; in that case this falls back to aiohttp, which
still works on networks that are not being blocked.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

try:
    from curl_cffi.requests import AsyncSession as _ImpersonateSession

    IMPERSONATE_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on the wheel being installed
    _ImpersonateSession = None
    IMPERSONATE_AVAILABLE = False

# Which browser curl-impersonate should imitate. Chrome is the safest default:
# it is the most common client AccuWeather sees.
IMPERSONATE_TARGET = "chrome"

REQUEST_TIMEOUT = 40


class HtmlFetcher:
    """Fetches pages, preferring a browser-like TLS fingerprint."""

    def __init__(self, aiohttp_session: aiohttp.ClientSession) -> None:
        """Keep the Home Assistant session as the fallback transport."""
        self._aiohttp = aiohttp_session
        self._impersonated: Any | None = None
        self.using_impersonation = IMPERSONATE_AVAILABLE

    def _session(self) -> Any | None:
        """Create the curl_cffi session on first use, inside the event loop."""
        if not IMPERSONATE_AVAILABLE:
            return None
        if self._impersonated is None:
            self._impersonated = _ImpersonateSession(
                impersonate=IMPERSONATE_TARGET,
                timeout=REQUEST_TIMEOUT,
            )
        return self._impersonated

    async def get_text(
        self, url: str, headers: dict[str, str]
    ) -> tuple[int, str | None]:
        """GET a URL, returning (status, body). Body is None on a non-200."""
        session = self._session()
        if session is not None:
            response = await session.get(url, headers=headers)
            if response.status_code != 200:
                return response.status_code, None
            return 200, response.text

        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        async with self._aiohttp.get(
            url, headers=headers, timeout=timeout
        ) as response:
            if response.status != 200:
                return response.status, None
            return 200, await response.text()

    async def get_json(
        self, url: str, headers: dict[str, str], params: dict[str, str] | None = None
    ) -> Any | None:
        """GET a JSON endpoint, or None if it did not answer with 200."""
        session = self._session()
        if session is not None:
            response = await session.get(url, headers=headers, params=params)
            if response.status_code != 200:
                return None
            return response.json()

        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        async with self._aiohttp.get(
            url, headers=headers, params=params, timeout=timeout
        ) as response:
            if response.status != 200:
                return None
            return await response.json(content_type=None)

    def clear_cookies(self) -> None:
        """Drop cookies so the next request starts a fresh handshake.

        A stale Akamai clearance cookie is one way a working setup starts
        answering 403 out of nowhere.
        """
        session = self._session()
        if session is not None:
            session.cookies.clear()
            return
        self._aiohttp.cookie_jar.clear()

    async def close(self) -> None:
        """Release the impersonated session, if one was created."""
        if self._impersonated is not None:
            await self._impersonated.close()
            self._impersonated = None
