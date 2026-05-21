"""Background metadata warmer for xtream-vodfs.

Fetches VOD metadata in parallel with bounded concurrency.
Coordinates with lazy fetching to avoid duplicate requests.
"""

import asyncio
import logging
import time
from typing import Optional, Dict, Set
from datetime import datetime

from app.models import XtreamCredentials, XtreamVodStream
from app.config import MetadataWarmerSettings
from app.metadata_cache import MetadataCache, make_cache_key
from app.xtream import XtreamClient


logger = logging.getLogger(__name__)


class MetadataWarmer:
    """
    Background task that warms metadata cache for VOD streams.

    Uses bounded concurrency to avoid overwhelming providers.
    Coordinates with lazy fetching via shared _pending set.
    """

    def __init__(
        self,
        metadata_cache: MetadataCache,
        providers: list[tuple[str, XtreamCredentials, list[XtreamVodStream]]],
        settings: MetadataWarmerSettings
    ):
        """
        Initialize metadata warmer.

        Args:
            metadata_cache: Metadata cache to populate
            providers: List of (provider_name, credentials, streams) tuples
            settings: Warmer configuration
        """
        self._cache = metadata_cache
        self._providers = providers
        self._settings = settings

        # Bounded concurrency
        self._semaphore = asyncio.Semaphore(settings.concurrency)

        # State tracking
        self._pending: Set[str] = set()  # Keys currently being fetched
        self._failed: Set[str] = set()   # Keys that failed this run
        self._fetched_count = 0
        self._failed_count = 0
        self._total_count = sum(len(streams) for _, _, streams in providers)

        # Timing
        self._start_time: Optional[float] = None
        self._end_time: Optional[float] = None

    async def start(self) -> None:
        """Start background warming task."""
        if not self._settings.enabled:
            logger.info("Metadata warming is disabled")
            return

        if self._total_count == 0:
            logger.info("No streams to warm metadata for")
            return

        self._start_time = time.time()
        logger.info(
            f"Starting metadata warming: {self._total_count} streams, "
            f"concurrency={self._settings.concurrency}"
        )

        # Schedule all streams
        for provider_name, credentials, streams in self._providers:
            for stream in streams:
                await self._schedule(provider_name, credentials, stream)

        # Wait for all pending tasks to complete
        while self._pending:
            await asyncio.sleep(0.5)

        self._end_time = time.time()
        elapsed = self._end_time - self._start_time

        logger.info(
            f"Metadata warming complete: {self._fetched_count} fetched, "
            f"{self._failed_count} failed in {elapsed:.1f}s"
        )

    async def _schedule(
        self,
        provider_name: str,
        credentials: XtreamCredentials,
        stream: XtreamVodStream
    ) -> None:
        """
        Schedule a stream for metadata fetching.

        Respects concurrency limits and avoids duplicates.
        """
        key = make_cache_key(provider_name, stream.stream_id)

        # Skip if already cached, pending, or failed
        if self._cache.has(provider_name, stream.stream_id):
            return
        if key in self._pending:
            return
        if key in self._failed:
            return

        # Respect queue depth limit (concurrency * 2)
        max_pending = self._settings.concurrency * 2
        while len(self._pending) >= max_pending:
            await asyncio.sleep(0.1)

        self._pending.add(key)
        asyncio.create_task(self._fetch_one(provider_name, credentials, stream))

        # Add delay between batches
        if self._settings.delay_seconds > 0:
            await asyncio.sleep(self._settings.delay_seconds)

    async def _fetch_one(
        self,
        provider_name: str,
        credentials: XtreamCredentials,
        stream: XtreamVodStream
    ) -> None:
        """
        Fetch metadata for a single stream.

        Implements retry with exponential backoff.
        """
        key = make_cache_key(provider_name, stream.stream_id)

        try:
            async with self._semaphore:
                last_exception: Optional[Exception] = None

                for attempt in range(self._settings.retry_attempts + 1):
                    try:
                        async with XtreamClient(credentials, timeout=30.0) as client:
                            metadata = await client.get_vod_info(stream.stream_id)

                            if metadata:
                                self._cache.set(provider_name, stream.stream_id, metadata)
                                self._fetched_count += 1
                                logger.debug(
                                    f"Fetched metadata for {provider_name}:{stream.stream_id} "
                                    f"({self._fetched_count}/{self._total_count})"
                                )
                                # Entries saved immediately in set()
                            else:
                                # Metadata not found is OK, just skip
                                pass

                            # Success - exit retry loop
                            return

                    except Exception as e:
                        last_exception = e
                        logger.debug(
                            f"Failed to fetch metadata for {key} "
                            f"(attempt {attempt + 1}/{self._settings.retry_attempts + 1}): {e}"
                        )

                        # Wait before retry (exponential backoff)
                        if attempt < self._settings.retry_attempts:
                            wait = min(
                                self._settings.retry_backoff_seconds * (2 ** attempt),
                                10.0  # Cap at 10 seconds
                            )
                            await asyncio.sleep(wait)

                # All retries failed
                self._failed.add(key)
                self._failed_count += 1
                logger.warning(
                    f"Failed to fetch metadata for {key} after "
                    f"{self._settings.retry_attempts + 1} attempts"
                )
        finally:
            self._pending.discard(key)

    async def request_single(self, provider_name: str, stream_id: str) -> None:
        """
        Request lazy fetch of a single stream.

        Fire-and-forget - does not block. Coordinates with warmer
        via shared _pending set to avoid duplicates.

        Args:
            provider_name: Provider name
            stream_id: Stream ID to fetch
        """
        # Find the provider credentials
        credentials = None
        for pname, creds, _ in self._providers:
            if pname == provider_name:
                credentials = creds
                break

        if not credentials:
            logger.warning(f"Cannot lazy fetch: provider {provider_name} not found")
            return

        key = make_cache_key(provider_name, stream_id)

        # Already cached, pending, or failed?
        if self._cache.has(provider_name, stream_id):
            return
        if key in self._pending:
            return
        if key in self._failed:
            return

        # Schedule fetch (fire-and-forget)
        self._pending.add(key)

        # Create a mock stream object
        from app.models import XtreamVodStream
        stream = XtreamVodStream(stream_id=stream_id)

        asyncio.create_task(self._fetch_one(provider_name, credentials, stream))

    def warming_progress(self) -> dict:
        """
        Get current warming progress.

        Returns:
            Dict with progress statistics
        """
        elapsed = 0.0
        if self._start_time:
            end = self._end_time or time.time()
            elapsed = end - self._start_time

        return {
            "total": self._total_count,
            "fetched": self._fetched_count,
            "failed": self._failed_count,
            "pending": len(self._pending),
            "elapsed_seconds": elapsed,
            "percent_complete": (
                (self._fetched_count / self._total_count * 100)
                if self._total_count > 0 else 0.0
            ),
            "is_warming": len(self._pending) > 0 or (
                self._start_time is not None and self._end_time is None
            ),
        }
