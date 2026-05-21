"""Configuration management for xtream-vodfs Sprint 2

Handles loading/saving config from JSON file with credential safety.
"""

import json
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict, field
from datetime import datetime

import pydantic
from pydantic import BaseModel, Field, validator


class XtreamCredentials(BaseModel):
    """Xtream server credentials"""
    base_url: str = Field(default="", description="Xtream server base URL without trailing slash")
    username: str = Field(default="", description="Xtream username")
    password: str = Field(default="", description="Xtream password")

    @validator('base_url')
    def normalize_base_url(cls, v):
        if v:
            return v.rstrip('/')
        return v


class LibrarySettings(BaseModel):
    """Library content settings"""
    enable_vod: bool = Field(default=True, description="Enable VOD movies")
    enable_series: bool = Field(default=False, description="Enable series (Sprint 4)")
    include_categories: list[str] = Field(default_factory=list, description="Specific categories to include")
    exclude_categories: list[str] = Field(default_factory=list, description="Categories to exclude")
    movies_include_all: bool = Field(default=True, description="Include all movies in /All/")
    movies_include_categories: bool = Field(default=True, description="Include category folders")


class HttpfsSettings(BaseModel):
    """HTTP filesystem settings"""
    enable_cdn_direct: bool = Field(default=False, description="When enabled, expose direct Xtream CDN URLs via X-Cdn-Url header and /cdn/ redirect endpoint (opt-in, default disabled)")
    enable_scanner_detection: bool = Field(default=True, description="When enabled, detect Plex/Emby/Jellyfin scanners and add small delays to avoid aggressive scanning")
    cache_content_type: bool = Field(default=True, description="Cache Content-Type lookups to avoid redundant upstream queries")
    dir_listing_cache_ttl: int = Field(default=60, description="Directory listing cache TTL in seconds (0 = no caching)")


class Config(BaseModel):
    """Main application configuration"""
    xtream: XtreamCredentials = Field(default_factory=XtreamCredentials)
    library: LibrarySettings = Field(default_factory=LibrarySettings)
    httpfs: HttpfsSettings = Field(default_factory=HttpfsSettings)

    class Config:
        # Extra fields allowed for future compatibility
        extra = 'ignore'


class ConfigManager:
    """Manages config file persistence with credential safety"""

    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize config manager.

        Args:
            config_dir: Override config directory. If None, uses XTREAM_VODFS_CONFIG_DIR env var
                        or defaults to ./config relative to code/
        """
        if config_dir:
            self.config_dir = Path(config_dir)
        elif 'XTREAM_VODFS_CONFIG_DIR' in os.environ:
            self.config_dir = Path(os.environ['XTREAM_VODFS_CONFIG_DIR'])
        else:
            # Default to ./config relative to this file's parent directory
            self.config_dir = Path(__file__).parent.parent / 'config'

        self.config_file = self.config_dir / 'config.json'
        self._config: Optional[Config] = None

    def _ensure_config_dir(self):
        """Ensure config directory exists"""
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> Config:
        """Load config from file or return defaults"""
        if self._config is not None:
            return self._config

        if not self.config_file.exists():
            self._ensure_config_dir()
            self._config = Config()
            return self._config

        try:
            with open(self.config_file, 'r') as f:
                data = json.load(f)
            self._config = Config(**data)
        except (json.JSONDecodeError, pydantic.ValidationError) as e:
            # If config is corrupt, use defaults
            import logging
            logging.warning(f"Failed to load config file {self.config_file}: {e}. Using defaults.")
            self._config = Config()

        return self._config

    def save(self, config: Config) -> None:
        """
        Save config to file with restricted permissions.

        Args:
            config: Config object to save
        """
        self._ensure_config_dir()

        # Convert to dict for JSON serialization
        data = config.dict()

        # Write to temp file first (atomic write)
        temp_file = self.config_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(data, f, indent=2, default=str)

        # Set restrictive permissions on temp file
        try:
            os.chmod(temp_file, 0o600)
        except OSError:
            # chmod may fail on some systems (e.g., Windows)
            pass

        # Atomic rename
        temp_file.replace(self.config_file)

        # Update cached config
        self._config = config

    def is_configured(self) -> bool:
        """Check if Xtream credentials are configured"""
        config = self.load()
        return bool(config.xtream.base_url and config.xtream.username and config.xtream.password)

    def get_config_dir(self) -> Path:
        """Get the config directory path"""
        self._ensure_config_dir()
        return self.config_dir


# Global config manager instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """Get or create global config manager instance"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def load_config() -> Config:
    """Load config from global config manager"""
    return get_config_manager().load()


def save_config(config: Config) -> None:
    """Save config via global config manager"""
    get_config_manager().save(config)