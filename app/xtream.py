"""Xtream Codes API client for xtream-vodfs Sprint 2

Handles authentication and fetching VOD content from Xtream-compatible servers.
"""

import logging
from typing import List, Optional
from datetime import datetime

import httpx

from app.models import (
    XtreamUserInfo,
    XtreamCategory,
    XtreamVodStream,
    XtreamValidationResponse,
    VodStreamMetadata,
)
from app.config import XtreamCredentials


logger = logging.getLogger(__name__)


class XtreamClientError(Exception):
    """Base exception for Xtream client errors"""
    pass


class XtreamAuthError(XtreamClientError):
    """Authentication error"""
    pass


class XtreamApiError(XtreamClientError):
    """API request error"""
    pass


class XtreamClient:
    """
    Async client for Xtream Codes API.

    Methods:
        validate_account(): Test credentials and get user info
        get_vod_categories(): Fetch VOD categories
        get_vod_streams(): Fetch VOD streams (optionally filtered by category)
        build_vod_stream_url(): Build direct streaming URL for a VOD stream
    """

    def __init__(self, credentials: XtreamCredentials, timeout: float = 30.0):
        """
        Initialize Xtream client.

        Args:
            credentials: Xtream server credentials
            timeout: Request timeout in seconds
        """
        self.credentials = credentials
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._client_kwargs = {
            'timeout': httpx.Timeout(timeout),
            'headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'application/json',
            }
        }

    async def __aenter__(self):
        """Async context manager entry"""
        await self._get_or_create_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    async def _get_or_create_client(self) -> httpx.AsyncClient:
        """Get or create httpx client"""
        if self._client is None:
            self._client = httpx.AsyncClient(**self._client_kwargs)
        return self._client

    async def close(self):
        """Close httpx client"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _build_url(self, action: Optional[str] = None, params: Optional[dict] = None) -> str:
        """
        Build API URL with parameters.

        Args:
            action: Optional API action (e.g., "get_vod_categories")
            params: Optional additional parameters

        Returns:
            Full URL with query parameters
        """
        base_url = self.credentials.base_url.rstrip('/')
        query_params = {
            'username': self.credentials.username,
            'password': self.credentials.password,
        }

        if action:
            query_params['action'] = action

        if params:
            query_params.update(params)

        # Build query string
        from urllib.parse import urlencode
        query_string = urlencode(query_params)

        return f"{base_url}/player_api.php?{query_string}"

    async def validate_account(self) -> XtreamValidationResponse:
        """
        Validate Xtream credentials and get user info.

        Returns:
            XtreamValidationResponse with user_info if successful

        Raises:
            XtreamAuthError: If authentication fails
            XtreamApiError: If API request fails
        """
        client = await self._get_or_create_client()
        url = self._build_url()

        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                logger.warning(f"Xtream auth failed: {e.response.status_code}")
                raise XtreamAuthError("Invalid Xtream credentials") from e
            logger.error(f"Xtream API error during auth: {e}")
            raise XtreamApiError(f"HTTP error: {e.response.status_code}") from e
        except httpx.RequestError as e:
            logger.error(f"Xtream connection error: {e}")
            raise XtreamApiError(f"Connection error: {str(e)}") from e

        try:
            data = response.json()
        except ValueError as e:
            logger.error(f"Xtream returned invalid JSON: {e}")
            raise XtreamApiError("Invalid response from server") from e

        # Check if response contains user_info (successful auth)
        if 'user_info' not in data:
            logger.warning("Xtream auth response missing user_info")
            raise XtreamAuthError("Invalid Xtream credentials")

        # Parse response safely
        try:
            validation_response = XtreamValidationResponse(**data)
            logger.info(f"Xtream auth successful for user {self.credentials.username}")
            return validation_response
        except Exception as e:
            logger.error(f"Failed to parse Xtream auth response: {e}")
            raise XtreamApiError("Invalid response format from server") from e

    async def get_vod_categories(self) -> List[XtreamCategory]:
        """
        Fetch VOD categories from Xtream server.

        Returns:
            List of XtreamCategory objects

        Raises:
            XtreamApiError: If API request fails
        """
        client = await self._get_or_create_client()
        url = self._build_url(action='get_vod_categories')

        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.RequestError as e:
            logger.error(f"Xtream connection error fetching categories: {e}")
            raise XtreamApiError(f"Connection error: {str(e)}") from e

        try:
            data = response.json()
        except ValueError as e:
            logger.error(f"Xtream returned invalid JSON for categories: {e}")
            raise XtreamApiError("Invalid response from server") from e

        # Parse categories safely
        categories = []
        if isinstance(data, list):
            for item in data:
                try:
                    category = XtreamCategory(**item)
                    categories.append(category)
                except Exception as e:
                    logger.warning(f"Failed to parse category: {item}, error: {e}")
        else:
            logger.warning(f"Xtream categories response is not a list: {type(data)}")

        logger.info(f"Fetched {len(categories)} VOD categories from Xtream")
        return categories

    async def get_vod_streams(self, category_id: Optional[str] = None) -> List[XtreamVodStream]:
        """
        Fetch VOD streams from Xtream server.

        Args:
            category_id: Optional category ID to filter streams

        Returns:
            List of XtreamVodStream objects

        Raises:
            XtreamApiError: If API request fails
        """
        client = await self._get_or_create_client()
        params = {}
        if category_id:
            params['category_id'] = category_id

        url = self._build_url(action='get_vod_streams', params=params)

        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.RequestError as e:
            logger.error(f"Xtream connection error fetching streams: {e}")
            raise XtreamApiError(f"Connection error: {str(e)}") from e

        try:
            data = response.json()
        except ValueError as e:
            logger.error(f"Xtream returned invalid JSON for streams: {e}")
            raise XtreamApiError("Invalid response from server") from e

        # Parse streams safely
        streams = []
        if isinstance(data, list):
            for item in data:
                try:
                    stream = XtreamVodStream(**item)
                    streams.append(stream)
                except Exception as e:
                    logger.warning(f"Failed to parse stream: {item}, error: {e}")
        else:
            logger.warning(f"Xtream streams response is not a list: {type(data)}")

        logger.info(f"Fetched {len(streams)} VOD streams from Xtream (category: {category_id or 'all'})")
        return streams

    async def get_vod_info(self, vod_id: str) -> Optional[VodStreamMetadata]:
        """
        Fetch enriched metadata for a VOD stream.

        Args:
            vod_id: VOD/stream ID to fetch metadata for

        Returns:
            VodStreamMetadata or None if not found or fetch fails

        Raises:
            XtreamApiError: If API request fails
        """
        client = await self._get_or_create_client()

        # Try both parameter names (provider variance)
        for param_name in ['vod_id', 'stream_id']:
            url = self._build_url(action='get_vod_info', params={param_name: vod_id})

            try:
                response = await client.get(url)

                # If 404 with wrong parameter name, try the next one
                if response.status_code == 404:
                    continue

                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    continue
                logger.error(f"Xtream API error fetching vod_info: {e}")
                raise XtreamApiError(f"HTTP error: {e.response.status_code}") from e
            except httpx.RequestError as e:
                logger.error(f"Xtream connection error fetching vod_info: {e}")
                raise XtreamApiError(f"Connection error: {str(e)}") from e

            try:
                data = response.json()
            except ValueError as e:
                logger.error(f"Xtream returned invalid JSON for vod_info: {e}")
                raise XtreamApiError("Invalid response from server") from e

            # Parse response safely
            try:
                # Response structure: {"info": {...}, "movie_data": {...}}
                info = data.get('info', {})
                movie_data = data.get('movie_data', {})

                # Build VodStreamMetadata from info + movie_data
                metadata_dict = {}

                # Fields from info
                if 'name' in info:
                    metadata_dict['name'] = info['name']
                if 'plot' in info:
                    metadata_dict['plot'] = info['plot']
                if 'cast' in info:
                    metadata_dict['cast'] = info['cast']
                if 'director' in info:
                    metadata_dict['director'] = info['director']
                if 'genre' in info:
                    metadata_dict['genre'] = info['genre']
                if 'duration' in info:
                    metadata_dict['duration'] = info['duration']
                if 'duration_secs' in info:
                    metadata_dict['duration_secs'] = info['duration_secs']
                if 'bitrate' in info:
                    metadata_dict['bitrate'] = info['bitrate']
                if 'rating' in info:
                    metadata_dict['rating'] = info['rating']
                if 'tmdb_id' in info:
                    metadata_dict['tmdb_id'] = info['tmdb_id']
                if 'releasedate' in info:
                    metadata_dict['releasedate'] = info['releasedate']
                if 'movie_image' in info:
                    metadata_dict['movie_image'] = info['movie_image']
                if 'backdrop_path' in info:
                    metadata_dict['backdrop_path'] = info['backdrop_path']
                if 'youtube_trailer' in info:
                    metadata_dict['youtube_trailer'] = info['youtube_trailer']
                if 'video' in info:
                    metadata_dict['video'] = info['video']
                if 'audio' in info:
                    metadata_dict['audio'] = info['audio']

                # Add timestamp
                metadata_dict['fetched_at'] = datetime.now()

                metadata = VodStreamMetadata(**metadata_dict)
                logger.info(f"Fetched vod_info for {vod_id} from {self.credentials.provider_name}")
                return metadata

            except Exception as e:
                logger.warning(f"Failed to parse vod_info response for {vod_id}: {e}")
                # Return None instead of raising - missing metadata is not fatal
                return None

        # Neither parameter name worked
        logger.warning(f"No vod_info found for ID {vod_id}")
        return None

    def build_vod_stream_url(self, stream: XtreamVodStream) -> str:
        """
        Build direct streaming URL for a VOD stream.

        Args:
            stream: XtreamVodStream object

        Returns:
            Full streaming URL

        Example:
            >>> client.build_vod_stream_url(stream)
            "http://example.com:8080/movie/username/password/12345.mp4"

        Note on CDN URLs:
            The Xtream Codes API does NOT expose actual CDN URLs in its response data.
            The stream URL is constructed from the base server URL + credentials + stream_id.
            The `direct_source` field on XtreamVodStream is rarely populated and unreliable.
            Therefore, the "CDN URL" for a stream IS the constructed streaming URL itself.
            When `enable_cdn_direct` is enabled, this same URL is exposed via:
              - X-Cdn-Url header on proxied responses
              - 302 redirect on /cdn/ endpoints (bypassing the local proxy)
            Local proxying remains the default for credential privacy and Range-request handling.
        """
        base_url = self.credentials.base_url.rstrip('/')
        username = self.credentials.username
        password = self.credentials.password
        stream_id = stream.stream_id
        extension = stream.container_extension or 'mp4'

        return f"{base_url}/movie/{username}/{password}/{stream_id}.{extension}"


async def validate_credentials(base_url: str, username: str, password: str, timeout: float = 30.0) -> tuple[bool, str]:
    """
    Validate Xtream credentials with a simple test.

    Args:
        base_url: Xtream server base URL
        username: Xtream username
        password: Xtream password
        timeout: Request timeout in seconds

    Returns:
        Tuple of (success: bool, message: str)

    Examples:
        >>> success, message = await validate_credentials("http://example.com:8080", "user", "pass")
        >>> if success:
        ...     print(f"Connected: {message}")
    """
    credentials = XtreamCredentials(base_url=base_url, username=username, password=password)

    async with XtreamClient(credentials, timeout=timeout) as client:
        try:
            response = await client.validate_account()
            user_info = response.user_info

            if user_info:
                msg = f"Connected as {username}"
                if user_info.status:
                    msg += f" — status: {user_info.status}"
                if user_info.active_cons is not None:
                    active = user_info.active_cons
                    max_conn = user_info.max_connections
                    if max_conn is not None:
                        msg += f", {active}/{max_conn} active streams"
                    else:
                        msg += f", {active} active streams"
                return True, msg
            else:
                return True, "Connection successful"
        except XtreamAuthError as e:
            return False, str(e)
        except XtreamApiError as e:
            return False, str(e)
        except Exception as e:
            logger.exception(f"Unexpected error validating credentials: {e}")
            return False, f"Unexpected error: {str(e)}"