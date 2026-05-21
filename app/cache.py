"""Cache management for xtream-vodfs Sprint 2

In-memory + JSON persistence for VOD categories and streams.
"""

import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from app.models import XtreamCategory, XtreamVodStream, FileMetadata
from app.config import get_config_manager


logger = logging.getLogger(__name__)


class Cache:
    """
    Cache for VOD data with in-memory storage and JSON persistence.

    Attributes:
        vod_categories: List of VOD categories
        vod_streams: List of VOD streams
        last_refresh: Timestamp of last refresh
    """

    def __init__(self):
        """Initialize cache"""
        self._vod_categories: Optional[List[XtreamCategory]] = None
        self._vod_streams: Optional[List[XtreamVodStream]] = None
        self._last_refresh: Optional[datetime] = None
        self._categories_by_id: Dict[str, XtreamCategory] = {}
        self._streams_by_category: Dict[str, List[XtreamVodStream]] = {}
        self._file_metadata: Dict[str, FileMetadata] = {}

    @property
    def vod_categories(self) -> List[XtreamCategory]:
        """Get VOD categories (empty list if not loaded)"""
        return self._vod_categories or []

    @property
    def vod_streams(self) -> List[XtreamVodStream]:
        """Get VOD streams (empty list if not loaded)"""
        return self._vod_streams or []

    @property
    def last_refresh(self) -> Optional[datetime]:
        """Get last refresh timestamp"""
        return self._last_refresh

    @property
    def is_empty(self) -> bool:
        """Check if cache is empty"""
        return self._vod_categories is None or self._vod_streams is None

    def set_vod_categories(self, categories: List[XtreamCategory]) -> None:
        """
        Set VOD categories and rebuild index.

        Args:
            categories: List of VOD categories
        """
        self._vod_categories = categories
        self._categories_by_id = {cat.category_id: cat for cat in categories}
        logger.info(f"Set {len(categories)} VOD categories in cache")

    def set_vod_streams(self, streams: List[XtreamVodStream]) -> None:
        """
        Set VOD streams and rebuild index.

        Args:
            streams: List of VOD streams
        """
        self._vod_streams = streams
        self._rebuild_stream_index()
        logger.info(f"Set {len(streams)} VOD streams in cache")

    def _rebuild_stream_index(self) -> None:
        """Rebuild stream index by category ID"""
        self._streams_by_category = {}
        for stream in self._vod_streams or []:
            cat_id = stream.category_id
            if cat_id not in self._streams_by_category:
                self._streams_by_category[cat_id] = []
            self._streams_by_category[cat_id].append(stream)

    def get_streams_by_category(self, category_id: str) -> List[XtreamVodStream]:
        """
        Get streams for a specific category.

        Args:
            category_id: Category ID

        Returns:
            List of streams in the category (empty if not found)
        """
        return self._streams_by_category.get(category_id, [])

    def get_category(self, category_id: str) -> Optional[XtreamCategory]:
        """
        Get category by ID.

        Args:
            category_id: Category ID

        Returns:
            Category object or None if not found
        """
        return self._categories_by_id.get(category_id)

    def get_file_metadata(self, stream_id: str) -> Optional[FileMetadata]:
        """
        Get cached metadata for a stream file.

        Args:
            stream_id: Stream ID

        Returns:
            FileMetadata or None if not cached
        """
        return self._file_metadata.get(stream_id)

    def set_file_metadata(self, stream_id: str, metadata: FileMetadata) -> None:
        """
        Set cached metadata for a stream file.

        Args:
            stream_id: Stream ID
            metadata: File metadata to cache
        """
        self._file_metadata[stream_id] = metadata

    def refresh(self, categories: List[XtreamCategory], streams: List[XtreamVodStream]) -> None:
        """
        Refresh cache with new data.

        Args:
            categories: New VOD categories
            streams: New VOD streams
        """
        self.set_vod_categories(categories)
        self.set_vod_streams(streams)
        self._last_refresh = datetime.now()
        logger.info(f"Cache refreshed at {self._last_refresh}")

    def set_provider_data(self, provider_name: str, categories: List[XtreamCategory], streams: List[XtreamVodStream]) -> None:
        """
        Set VOD categories and streams for a specific provider.

        Stores data with provider-prefixed IDs to avoid collisions
        when multiple providers are configured.

        Args:
            provider_name: Provider identifier
            categories: List of VOD categories
            streams: List of VOD streams
        """
        # Store with provider prefix to avoid collisions
        prefixed_categories = []
        prefixed_streams = []

        for cat in categories:
            # Create a copy with provider-scoped ID
            cat_dict = cat.dict()
            cat_dict['category_id'] = f"{provider_name}:{cat.category_id}"
            prefixed_categories.append(XtreamCategory(**cat_dict))

        for stream in streams:
            # Create a copy with provider prefix
            stream_dict = stream.dict()
            stream_dict['stream_id'] = f"{provider_name}:{stream.stream_id}"
            stream_dict['category_id'] = f"{provider_name}:{stream.category_id}"
            prefixed_streams.append(XtreamVodStream(**stream_dict))

        self.set_vod_categories(prefixed_categories)
        self.set_vod_streams(prefixed_streams)

    def clear(self) -> None:
        """Clear all cached data"""
        self._vod_categories = None
        self._vod_streams = None
        self._last_refresh = None
        self._categories_by_id = {}
        self._streams_by_category = {}
        self._file_metadata = {}
        logger.info("Cache cleared")

    def save_to_disk(self) -> None:
        """Save cache to JSON file"""
        config_manager = get_config_manager()
        cache_file = config_manager.get_config_dir() / 'cache.json'

        try:
            data = {
                'vod_categories': [cat.dict() for cat in self.vod_categories],
                'vod_streams': [stream.dict() for stream in self.vod_streams],
                'last_refresh': self._last_refresh.isoformat() if self._last_refresh else None,
                'file_metadata': {
                    sid: meta.dict() for sid, meta in self._file_metadata.items()
                },
            }

            # Write to temp file first (atomic write)
            temp_file = cache_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)

            # Atomic rename
            temp_file.replace(cache_file)

            logger.info(f"Cache saved to {cache_file}")
        except Exception as e:
            logger.error(f"Failed to save cache to disk: {e}")

    def load_from_disk(self) -> bool:
        """
        Load cache from JSON file.

        Returns:
            True if cache was loaded successfully, False otherwise
        """
        config_manager = get_config_manager()
        cache_file = config_manager.get_config_dir() / 'cache.json'

        if not cache_file.exists():
            logger.info(f"Cache file not found: {cache_file}")
            return False

        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)

            # Parse categories
            categories = []
            for item in data.get('vod_categories', []):
                try:
                    categories.append(XtreamCategory(**item))
                except Exception as e:
                    logger.warning(f"Failed to parse cached category: {e}")

            # Parse streams
            streams = []
            for item in data.get('vod_streams', []):
                try:
                    streams.append(XtreamVodStream(**item))
                except Exception as e:
                    logger.warning(f"Failed to parse cached stream: {e}")

            # Set last refresh
            last_refresh_str = data.get('last_refresh')
            if last_refresh_str:
                try:
                    self._last_refresh = datetime.fromisoformat(last_refresh_str)
                except Exception as e:
                    logger.warning(f"Failed to parse last_refresh timestamp: {e}")

            # Load file metadata
            file_meta = data.get('file_metadata', {})
            for sid, meta_data in file_meta.items():
                try:
                    self._file_metadata[sid] = FileMetadata(**meta_data)
                except Exception as e:
                    logger.warning(f"Failed to parse cached file metadata for stream {sid}: {e}")

            self.set_vod_categories(categories)
            self.set_vod_streams(streams)

            logger.info(f"Cache loaded from {cache_file} ({len(categories)} categories, {len(streams)} streams, {len(self._file_metadata)} file metadata)")
            return True
        except Exception as e:
            logger.error(f"Failed to load cache from disk: {e}")
            return False


# Global cache instance
_cache: Optional[Cache] = None


def get_cache() -> Cache:
    """Get or create global cache instance"""
    global _cache
    if _cache is None:
        _cache = Cache()
    return _cache