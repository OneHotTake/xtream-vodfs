"""Metadata cache for xtream-vodfs VOD enrichment data.

Stores enriched metadata from get_vod_info API calls in a directory structure.
Structure: config/metadata_cache/{provider_name}/{stream_id}.json
"""

import json
import logging
import asyncio
from pathlib import Path
from typing import Optional, Dict, Set
from datetime import datetime

from app.models import VodStreamMetadata
from app.config import get_config_manager


logger = logging.getLogger(__name__)


def make_cache_key(provider_name: str, stream_id: str) -> str:
    """Create a cache key from provider_name and stream_id."""
    return f"{provider_name}:{stream_id}"


def parse_cache_key(key: str) -> tuple[str, str]:
    """Parse a cache key into (provider_name, stream_id).

    Raises ValueError on malformed key.
    """
    parts = key.split(':', 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid cache key: {key}")
    return parts[0], parts[1]


def get_metadata_cache_file(config_manager, provider_name: str, stream_id: str) -> Path:
    """Get the file path for a specific metadata entry."""
    cache_dir = config_manager.get_config_dir() / 'metadata_cache' / provider_name
    return cache_dir / f"{stream_id}.json"


class MetadataCache:
    """
    Cache for VOD metadata with directory-based persistence.

    Stores entries as individual JSON files:
    config/metadata_cache/{provider_name}/{stream_id}.json
    """

    CACHE_VERSION = 1
    VERSION_FILE = "cache_version.txt"

    def __init__(self):
        """Initialize metadata cache."""
        self._cache_dir: Optional[Path] = None
        self._dirty: bool = False
        self._save_lock = asyncio.Lock()
        self._loaded_providers: Set[str] = set()

    def _ensure_cache_dir(self) -> Path:
        """Ensure cache directory exists and return it."""
        if self._cache_dir is None:
            config_manager = get_config_manager()
            self._cache_dir = config_manager.get_config_dir() / 'metadata_cache'
            self._cache_dir.mkdir(parents=True, exist_ok=True)

            # Write version file
            version_file = self._cache_dir / self.VERSION_FILE
            if not version_file.exists():
                version_file.write_text(str(self.CACHE_VERSION))

        return self._cache_dir

    def get(self, provider_name: str, stream_id: str) -> Optional[VodStreamMetadata]:
        """Get cached metadata for a stream."""
        config_manager = get_config_manager()
        cache_file = get_metadata_cache_file(config_manager, provider_name, stream_id)

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
            return VodStreamMetadata(**data)
        except Exception as e:
            logger.warning(f"Failed to load metadata for {provider_name}:{stream_id}: {e}")
            return None

    def set(self, provider_name: str, stream_id: str, metadata: VodStreamMetadata) -> None:
        """Set cached metadata for a stream."""
        config_manager = get_config_manager()
        cache_dir = self._ensure_cache_dir()

        # Create provider directory if needed
        provider_dir = cache_dir / provider_name
        provider_dir.mkdir(exist_ok=True)

        # Write metadata file
        cache_file = provider_dir / f"{stream_id}.json"

        try:
            with open(cache_file, 'w') as f:
                json.dump(metadata.dict(), f, indent=2, default=str)
            logger.debug(f"Saved metadata for {provider_name}:{stream_id}")
        except Exception as e:
            logger.error(f"Failed to save metadata for {provider_name}:{stream_id}: {e}")

    def has(self, provider_name: str, stream_id: str) -> bool:
        """Check if metadata is cached for a stream."""
        config_manager = get_config_manager()
        cache_file = get_metadata_cache_file(config_manager, provider_name, stream_id)
        return cache_file.exists()

    def missing_keys(self, provider_name: str, stream_ids: list[str]) -> list[str]:
        """Return list of stream_ids that are not cached."""
        config_manager = get_config_manager()
        cache_dir = config_manager.get_config_dir() / 'metadata_cache' / provider_name

        if not cache_dir.exists():
            return stream_ids

        missing = []
        for stream_id in stream_ids:
            cache_file = cache_dir / f"{stream_id}.json"
            if not cache_file.exists():
                missing.append(stream_id)

        return missing

    def count(self) -> int:
        """Return number of cached entries."""
        cache_dir = self._ensure_cache_dir()
        count = 0
        for provider_dir in cache_dir.iterdir():
            if provider_dir.is_dir():
                count += len(list(provider_dir.glob("*.json")))
        return count

    def count_by_provider(self, provider_name: str) -> int:
        """Return number of cached entries for a specific provider."""
        config_manager = get_config_manager()
        provider_dir = config_manager.get_config_dir() / 'metadata_cache' / provider_name

        if not provider_dir.exists():
            return 0

        return len(list(provider_dir.glob("*.json")))

    def clear(self) -> None:
        """Clear all cached entries."""
        cache_dir = self._ensure_cache_dir()
        for provider_dir in cache_dir.iterdir():
            if provider_dir.is_dir():
                for cache_file in provider_dir.glob("*.json"):
                    cache_file.unlink()
                provider_dir.rmdir()

    def clear_provider(self, provider_name: str) -> None:
        """Clear all cached entries for a specific provider."""
        config_manager = get_config_manager()
        provider_dir = config_manager.get_config_dir() / 'metadata_cache' / provider_name

        if provider_dir.exists():
            for cache_file in provider_dir.glob("*.json"):
                cache_file.unlink()
            provider_dir.rmdir()

    async def save_to_disk(self) -> None:
        """No-op for directory-based cache - entries are saved immediately."""
        pass

    def _migrate_from_old_cache(self) -> int:
        """Migrate from old monolithic cache to new directory structure.

        Returns:
            Number of entries migrated
        """
        config_manager = get_config_manager()
        old_cache_file = config_manager.get_config_dir() / 'metadata_cache.json'

        if not old_cache_file.exists():
            return 0

        try:
            with open(old_cache_file, 'r') as f:
                data = json.load(f)

            version = data.get('version', 0)
            if version != self.CACHE_VERSION:
                logger.warning("Old cache version mismatch, skipping migration")
                return 0

            entries = data.get('entries', {})
            migrated = 0

            for key, metadata_data in entries.items():
                try:
                    provider_name, stream_id = parse_cache_key(key)
                    metadata = VodStreamMetadata(**metadata_data)
                    self.set(provider_name, stream_id, metadata)
                    migrated += 1
                except Exception as e:
                    logger.warning(f"Failed to migrate entry {key}: {e}")

            # Backup and remove old cache
            backup_file = old_cache_file.with_suffix('.json.backup')
            old_cache_file.rename(backup_file)
            logger.info(f"Migrated {migrated} entries from old cache. Old cache backed up to {backup_file}")

            return migrated
        except Exception as e:
            logger.error(f"Failed to migrate old cache: {e}")
            return 0

    def load_from_disk(self) -> bool:
        """
        Directory-based cache doesn't need bulk loading.

        Entries are loaded on-demand via get().
        This method just verifies the cache directory structure
        and attempts migration from the old monolithic cache.

        Returns:
            True if cache directory exists and is valid
        """
        try:
            cache_dir = self._ensure_cache_dir()

            # Try migration from old cache
            migrated = self._migrate_from_old_cache()
            if migrated > 0:
                logger.info(f"Migrated {migrated} entries from old monolithic cache")

            # Check version
            version_file = cache_dir / self.VERSION_FILE
            if version_file.exists():
                version = int(version_file.read_text().strip())
                if version != self.CACHE_VERSION:
                    logger.warning(
                        f"Metadata cache version mismatch: expected {self.CACHE_VERSION}, "
                        f"got {version}. Will recreate cache."
                    )
                    return False

            count = self.count()
            logger.info(f"Metadata cache directory ready: {count} entries")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize metadata cache: {e}")
            return False

    def get_cached_providers(self) -> list[str]:
        """Return list of providers with cached entries."""
        cache_dir = self._ensure_cache_dir()
        providers = []
        for provider_dir in cache_dir.iterdir():
            if provider_dir.is_dir() and any(provider_dir.glob("*.json")):
                providers.append(provider_dir.name)
        return providers

    def get_cached_stream_ids(self, provider_name: str) -> list[str]:
        """Return list of stream_ids cached for a specific provider."""
        config_manager = get_config_manager()
        provider_dir = config_manager.get_config_dir() / 'metadata_cache' / provider_name

        if not provider_dir.exists():
            return []

        return [f.stem for f in provider_dir.glob("*.json")]


# Global cache instance
_metadata_cache: Optional[MetadataCache] = None


def get_metadata_cache() -> MetadataCache:
    """Get or create global metadata cache instance."""
    global _metadata_cache
    if _metadata_cache is None:
        _metadata_cache = MetadataCache()
    return _metadata_cache
