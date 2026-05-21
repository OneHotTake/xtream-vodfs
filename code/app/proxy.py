"""Streaming proxy for xtream-vodfs Sprint 3

Handles streaming VOD content from Xtream servers with Range header support,
rate limiting, retry logic, and configurable timeouts.
"""

import asyncio
import logging
import os
import re
import time
from collections import defaultdict
from typing import AsyncGenerator, Dict, List, Optional

import httpx
from fastapi import Response
from fastapi.responses import StreamingResponse, RedirectResponse

from app.models import FSNode, NodeType


logger = logging.getLogger(__name__)


# Headers to preserve from upstream response (non-hop-by-hop)
PRESERVE_HEADERS = {
    'Content-Type',
    'Content-Length',
    'Content-Range',
    'Accept-Ranges',
    'ETag',
    'Last-Modified',
    'Cache-Control',
    'Content-Disposition',
}

# Hop-by-hop headers to strip (not forwarded)
HOP_BY_HOP_HEADERS = {
    'Connection',
    'Keep-Alive',
    'Proxy-Authenticate',
    'Proxy-Authorization',
    'Te',
    'Trailers',
    'Transfer-Encoding',
    'Upgrade',
}


class ProxyError(Exception):
    """Proxy error"""
    pass


class ProxyConnectionError(ProxyError):
    """Connection error"""
    pass


class ProxyTimeoutError(ProxyError):
    """Timeout error"""
    pass


# ---- Credential sanitization ----

# Regex to match URL credentials: scheme://user:pass@host
_CREDENTIAL_RE = re.compile(r'://([^:]+):([^@]+)@')


def sanitize_url(url: str) -> str:
    """Remove credentials from URL for safe logging."""
    return _CREDENTIAL_RE.sub(r'://***:***@', url)


def sanitize_error_message(msg: str) -> str:
    """Remove potential credential patterns from error messages."""
    # Remove anything that looks like a URL with credentials
    msg = _CREDENTIAL_RE.sub(r'://***:***@', msg)
    # Also remove standalone password-like patterns if they appear
    return msg


# ---- Rate Limiter ----

class RateLimiter:
    """
    Simple in-memory rate limiter tracking requests per IP.

    Uses a sliding window of timestamps per client IP.
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, List[float]] = defaultdict(list)

    def check(self, client_ip: str) -> bool:
        """
        Check if request is allowed for this IP.

        Returns True if allowed, False if rate limited.
        """
        now = time.time()
        cutoff = now - self.window_seconds

        # Prune old entries
        self._requests[client_ip] = [
            t for t in self._requests[client_ip] if t > cutoff
        ]

        if len(self._requests[client_ip]) >= self.max_requests:
            logger.warning(f"Rate limit exceeded for {client_ip}")
            return False

        self._requests[client_ip].append(now)
        return True


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        max_requests = int(os.environ.get('RATE_LIMIT_PER_MINUTE', '60'))
        _rate_limiter = RateLimiter(max_requests=max_requests)
    return _rate_limiter


# ---- Retry settings ----

def _get_upstream_timeout() -> float:
    """Get upstream timeout from environment or default."""
    return float(os.environ.get('UPSTREAM_TIMEOUT', '30'))


async def stream_vod_file(
    upstream_url: str,
    range_header: Optional[str] = None,
    timeout: Optional[float] = None,
    add_cdn_header: bool = False,
    cdn_url: Optional[str] = None,
) -> StreamingResponse:
    """
    Stream VOD file from upstream with Range header support, retry, and backoff.

    Args:
        upstream_url: Upstream streaming URL
        range_header: Optional Range header value
        timeout: Request timeout in seconds (defaults to UPSTREAM_TIMEOUT env var)
        add_cdn_header: When True, adds X-Cdn-Url header to response
        cdn_url: CDN URL to include in X-Cdn-Url header (defaults to upstream_url if not set)

    Returns:
        StreamingResponse with appropriate headers

    Raises:
        ProxyConnectionError: If connection fails
        ProxyTimeoutError: If request times out
        ProxyError: If other error occurs
    """
    if timeout is None:
        timeout = _get_upstream_timeout()

    headers = {}
    if range_header:
        headers['Range'] = range_header

    safe_url = sanitize_url(upstream_url)
    cdn_header_url = cdn_url or upstream_url

    async def generate() -> AsyncGenerator[bytes, None]:
        """Async generator for streaming response with retry logic"""
        last_exception: Optional[Exception] = None
        max_retries = 3

        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
                    async with client.stream('GET', upstream_url, headers=headers) as response:
                        response.raise_for_status()

                        async for chunk in response.aiter_bytes():
                            yield chunk
                        # Success — exit generator
                        return

            except httpx.TimeoutException as e:
                logger.warning(
                    f"Timeout streaming from {safe_url} (attempt {attempt + 1}/{max_retries + 1})"
                )
                last_exception = ProxyTimeoutError("Streaming timeout from upstream")
            except httpx.HTTPStatusError as e:
                # Do NOT retry client errors (4xx)
                if 400 <= e.response.status_code < 500:
                    raise ProxyError(f"Upstream error: {e.response.status_code}") from e
                # Retry server errors (5xx)
                logger.warning(
                    f"Upstream server error {e.response.status_code} from {safe_url} "
                    f"(attempt {attempt + 1}/{max_retries + 1})"
                )
                last_exception = ProxyError(f"Upstream error: {e.response.status_code}")
            except httpx.RequestError as e:
                logger.warning(
                    f"Connection error streaming from {safe_url} "
                    f"(attempt {attempt + 1}/{max_retries + 1})"
                )
                last_exception = ProxyConnectionError("Connection error to upstream")
            except Exception as e:
                logger.exception(f"Unexpected error streaming from {safe_url}")
                last_exception = ProxyError("Streaming error")

            if attempt < max_retries:
                # Exponential backoff: 1s, 2s, 4s (capped at 10s)
                wait = min(1 * (2 ** attempt), 10)
                logger.info(f"Retrying in {wait}s (attempt {attempt + 2}/{max_retries + 1})")
                await asyncio.sleep(wait)

        # All retries exhausted
        raise last_exception  # type: ignore

    # Build response headers from upstream
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            head_response = await client.head(upstream_url, headers=headers)

            response_headers = {}
            for name, value in head_response.headers.items():
                # Only preserve specific headers
                if name in PRESERVE_HEADERS:
                    response_headers[name] = value

            # Ensure Range support is indicated
            response_headers['Accept-Ranges'] = 'bytes'

            # Add CDN URL header if enabled
            if add_cdn_header:
                response_headers['X-Cdn-Url'] = cdn_header_url
                logger.debug(f"Added X-Cdn-Url header: {sanitize_url(cdn_header_url)}")

            # Determine status code
            status_code = head_response.status_code

            return StreamingResponse(
                generate(),
                status_code=status_code,
                headers=response_headers,
                media_type=response_headers.get('Content-Type', 'video/mp4')
            )

    except Exception as e:
        # If HEAD fails, return streaming response anyway
        response_headers = {'Accept-Ranges': 'bytes'}
        if add_cdn_header:
            response_headers['X-Cdn-Url'] = cdn_header_url
        logger.warning(
            f"HEAD request failed for {safe_url}, streaming without headers: {sanitize_error_message(str(e))}"
        )
        return StreamingResponse(
            generate(),
            status_code=200,
            headers=response_headers,
            media_type='video/mp4'
        )


async def stream_vod_from_node(
    node: FSNode,
    range_header: Optional[str] = None,
    timeout: Optional[float] = None,
    enable_cdn_direct: bool = False,
) -> Response:
    """
    Stream VOD file from FSNode with Range header support.

    When enable_cdn_direct is True and no Range header is present, returns a 302 redirect
    to the direct upstream/CDN URL (bypassing the local proxy). HEAD requests always remain local.

    Args:
        node: FSNode with xtream_vod_file type
        range_header: Optional Range header value
        timeout: Request timeout in seconds (defaults to UPSTREAM_TIMEOUT env var)
        enable_cdn_direct: When True, expose CDN URL via X-Cdn-Url header (and 302 redirect for GET)

    Returns:
        Response with appropriate headers (StreamingResponse or RedirectResponse)

    Raises:
        ValueError: If node is not xtream_vod_file type
        ProxyError: If streaming fails
    """
    if node.type != NodeType.XTREAM_VOD_FILE:
        raise ValueError(f"Expected xtream_vod_file node, got {node.type}")

    if not node.upstream_url:
        raise ValueError("Node missing upstream_url")

    safe_url = sanitize_url(node.upstream_url)
    logger.info(f"Streaming VOD file: {node.name} from {safe_url}")

    # When CDN direct is enabled and no Range header, redirect directly to upstream
    # This bypasses the local proxy, trading credential privacy for direct streaming.
    # HEAD requests stay local (handled by head_vod_from_node in main.py).
    if enable_cdn_direct and not range_header:
        logger.info(f"CDN direct enabled: redirecting to {safe_url}")
        return RedirectResponse(
            url=node.upstream_url,
            status_code=302,
            headers={"X-Cdn-Url": node.upstream_url}
        )

    # Normal proxied streaming with optional X-Cdn-Url header
    return await stream_vod_file(
        node.upstream_url,
        range_header,
        timeout,
        add_cdn_header=enable_cdn_direct,
        cdn_url=node.upstream_url,
    )


def head_vod_from_node(
    node: FSNode,
    head_mode: str = 'cached_only'
) -> Response:
    """
    Generate HEAD response for VOD node.

    Args:
        node: FSNode with xtream_vod_file type
        head_mode: HEAD mode ('cached_only', 'upstream_probe', 'synthetic_size')

    Returns:
        FastAPI Response with appropriate headers
    """
    if node.type != NodeType.XTREAM_VOD_FILE:
        raise ValueError(f"Expected xtream_vod_file node, got {node.type}")

    # Build headers
    headers = {
        'Accept-Ranges': 'bytes',
    }

    if node.content_type:
        headers['Content-Type'] = node.content_type

    if node.size:
        headers['Content-Length'] = str(node.size)

    if node.last_modified:
        # Format as HTTP date
        headers['Last-Modified'] = node.last_modified.strftime('%a, %d %b %Y %H:%M:%S GMT')

    # For Sprint 2, we always return 200 with cached metadata
    # Future sprints may add upstream_probe mode
    return Response(status_code=200, headers=headers)