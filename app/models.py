"""Data models for xtream-vodfs"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, validator


class XtreamCredentials(BaseModel):
    """Xtream server credentials with multi-provider support"""
    provider_name: str = Field(
        default="",
        min_length=1,
        description="Stable unique identifier for this provider (e.g., 'real-debrid', 'super-iptv'). Used in cache keys and filesystem paths."
    )
    base_url: str = Field(default="", description="Xtream server base URL without trailing slash")
    username: str = Field(default="", description="Xtream username")
    password: str = Field(default="", description="Xtream password")
    enabled: bool = Field(default=True, description="Whether this provider is active")

    @validator('provider_name')
    def sanitize_provider_name(cls, v):
        v = v.strip().lower()
        v = re.sub(r'[^a-z0-9_-]', '-', v)
        v = re.sub(r'-+', '-', v)
        v = v.strip('-')
        if not v:
            raise ValueError("provider_name cannot be empty")
        return v

    @validator('base_url')
    def normalize_base_url(cls, v):
        if v:
            return v.rstrip('/')
        return v


class NodeType(str, Enum):
    """Type of node in the virtual filesystem"""
    DIRECTORY = "directory"
    FILE = "file"
    XTREAM_VOD_FILE = "xtream_vod_file"


@dataclass
class FSNode:
    """A node in the virtual filesystem"""
    name: str
    type: NodeType
    path: str
    size: Optional[int] = None
    last_modified: Optional[datetime] = None
    children: Optional[List['FSNode']] = None

    # For xtream_vod_file type
    stream_id: Optional[str] = None
    category_id: Optional[str] = None
    category_name: Optional[str] = None
    container_extension: Optional[str] = None
    upstream_url: Optional[str] = None
    content_type: Optional[str] = None
    provider_name: Optional[str] = None

    def is_directory(self) -> bool:
        return self.type == NodeType.DIRECTORY

    def is_file(self) -> bool:
        return self.type in (NodeType.FILE, NodeType.XTREAM_VOD_FILE)


# ===== Xtream API Models (Sprint 2) =====


class XtreamUserInfo(BaseModel):
    """User info from player_api.php authentication"""
    status: Optional[str] = None
    active_cons: Optional[int] = None
    max_connections: Optional[int] = None
    exp_date: Optional[int] = None
    is_trial: Optional[str] = None
    active: Optional[str] = None
    created_at: Optional[str] = None
    max_connections: Optional[int] = None
    allowed_output_formats: Optional[list[str]] = None

    class Config:
        extra = 'ignore'  # Allow provider variance


class XtreamCategory(BaseModel):
    """VOD or Series category from Xtream API"""
    category_id: str = Field(default="", description="Category ID (may be string or int)")
    category_name: str = Field(default="", description="Category name")
    parent_id: Optional[int] = Field(None, description="Parent category ID if nested")

    @validator('category_id')
    def normalize_category_id(cls, v):
        # Ensure category_id is always a string for consistency
        if v is None:
            return ""
        return str(v)

    class Config:
        extra = 'ignore'


class XtreamVodStream(BaseModel):
    """VOD stream from Xtream API"""
    stream_id: str = Field(default="", description="Stream ID")
    name: str = Field(default="", description="Stream name")
    category_id: str = Field(default="", description="Category ID")
    container_extension: str = Field(default="mp4", description="File extension")
    stream_icon: Optional[str] = Field(None, description="Stream icon URL")
    rating: Optional[float] = Field(None, description="Rating value")
    rating_5based: Optional[float] = Field(None, description="5-based rating")
    added: Optional[int] = Field(None, description="Unix timestamp when added")

    @validator('rating', pre=True)
    def normalize_rating(cls, v):
        # Handle string ratings like "6.0/10"
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            # Handle format like "6.0/10"
            if '/' in v:
                try:
                    return float(v.split('/')[0].strip())
                except (ValueError, IndexError):
                    return None
            try:
                return float(v)
            except ValueError:
                return None
        return None

    @validator('rating_5based', pre=True)
    def normalize_rating_5based(cls, v):
        # Handle string ratings like "6.0/10"
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            # Handle format like "6.0/10"
            if '/' in v:
                try:
                    return float(v.split('/')[0].strip())
                except (ValueError, IndexError):
                    return None
            try:
                return float(v)
            except ValueError:
                return None
        return None
    custom_sid: Optional[str] = Field(None, description="Custom service ID")
    direct_source: Optional[str] = Field(None, description="Direct source URL")
    num: Optional[int] = Field(None, description="Stream number")

    @validator('stream_id', pre=True)
    def normalize_stream_id(cls, v):
        if v is None:
            return ""
        return str(v)

    @validator('category_id', pre=True)
    def normalize_category_id(cls, v):
        if v is None:
            return ""
        return str(v)

    @validator('added', pre=True)
    def normalize_added(cls, v):
        # Handle both string and int timestamps
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return None
        return None

    @validator('container_extension', pre=True)
    def default_extension(cls, v):
        # Default to mp4 if extension is missing or invalid
        if not v or v.strip() == "":
            return "mp4"
        # Remove leading dot if present
        if isinstance(v, str) and v.startswith('.'):
            return v[1:]
        return v

    class Config:
        extra = 'ignore'


class FileMetadata(BaseModel):
    """Cached metadata for a stream file"""
    size: Optional[int] = Field(None, description="File size in bytes")
    content_type: Optional[str] = Field(None, description="MIME content type")
    last_modified: Optional[datetime] = Field(None, description="Last modified timestamp")

    class Config:
        extra = 'ignore'


class XtreamValidationResponse(BaseModel):
    """Response from player_api.php authentication"""
    user_info: Optional[XtreamUserInfo] = Field(None, description="User information if authenticated")
    server_info: Optional[Dict[str, Any]] = Field(None, description="Server information")

    class Config:
        extra = 'ignore'


class VodStreamMetadata(BaseModel):
    """Enriched metadata from get_vod_info API. All fields optional due to provider variance."""
    name: Optional[str] = None
    plot: Optional[str] = None
    cast: Optional[str] = None
    director: Optional[str] = None
    genre: Optional[str] = None
    duration: Optional[str] = None
    duration_secs: Optional[int] = None
    bitrate: Optional[int] = None
    rating: Optional[float] = None
    tmdb_id: Optional[int] = None
    releasedate: Optional[str] = None
    movie_image: Optional[str] = None
    backdrop_path: Optional[list] = None
    youtube_trailer: Optional[str] = None
    video: Optional[dict] = None  # opaque — provider varies
    audio: Optional[dict] = None  # opaque — provider varies
    fetched_at: Optional[datetime] = None

    class Config:
        extra = 'ignore'
