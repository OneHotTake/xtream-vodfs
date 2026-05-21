"""Tests for Xtream API client (Sprint 2)"""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from httpx import HTTPStatusError, RequestError, TimeoutException

from app.xtream import (
    XtreamClient,
    XtreamClientError,
    XtreamAuthError,
    XtreamApiError,
    validate_credentials,
)
from app.config import XtreamCredentials
from app.models import XtreamUserInfo, XtreamCategory, XtreamVodStream, XtreamValidationResponse


@pytest.fixture
def credentials():
    """Fixture for test credentials"""
    return XtreamCredentials(
        base_url="http://example.com:8080",
        username="testuser",
        password="testpass"
    )


@pytest.fixture
def mock_response():
    """Fixture for mock httpx response"""
    response = Mock()
    response.status_code = 200
    response.headers = {"Content-Type": "application/json"}
    response.json = Mock()
    response.raise_for_status = Mock()
    return response


class TestXtreamClient:
    """Test XtreamClient initialization and URL building"""

    def test_init(self, credentials):
        """Test client initialization"""
        client = XtreamClient(credentials, timeout=30.0)
        assert client.credentials == credentials
        assert client.timeout == 30.0
        assert client._client is None

    def test_base_url_normalization(self):
        """Test that base_url trailing slash is stripped"""
        creds1 = XtreamCredentials(base_url="http://example.com:8080/", username="u", password="p")
        creds2 = XtreamCredentials(base_url="http://example.com:8080", username="u", password="p")

        client1 = XtreamClient(creds1)
        client2 = XtreamClient(creds2)

        url1 = client1._build_url()
        url2 = client2._build_url()

        # Both should produce the same URL (no trailing slash)
        assert url1 == url2
        assert "example.com:8080" in url1

    def test_build_url_basic(self, credentials):
        """Test basic URL building"""
        client = XtreamClient(credentials)
        url = client._build_url()

        assert "example.com:8080" in url
        assert "username=testuser" in url
        assert "password=testpass" in url
        assert "player_api.php" in url

    def test_build_url_with_action(self, credentials):
        """Test URL building with action parameter"""
        client = XtreamClient(credentials)
        url = client._build_url(action="get_vod_categories")

        assert "action=get_vod_categories" in url
        assert "username=testuser" in url

    def test_build_url_with_params(self, credentials):
        """Test URL building with additional parameters"""
        client = XtreamClient(credentials)
        url = client._build_url(action="get_vod_streams", params={"category_id": "123"})

        assert "action=get_vod_streams" in url
        assert "category_id=123" in url

    def test_build_vod_stream_url(self, credentials):
        """Test VOD stream URL building"""
        client = XtreamClient(credentials)
        stream = XtreamVodStream(
            stream_id="12345",
            name="Test Movie",
            category_id="1",
            container_extension="mp4",
            stream_icon=None,
            rating=None,
            rating_5based=None,
            added=None,
            custom_sid=None,
            direct_source=None,
            num=None
        )

        url = client.build_vod_stream_url(stream)

        assert "example.com:8080" in url
        assert "/movie/" in url
        assert "testuser" in url
        assert "testpass" in url
        assert "12345.mp4" in url

    def test_build_vod_stream_url_default_extension(self, credentials):
        """Test VOD stream URL with default extension"""
        client = XtreamClient(credentials)
        stream = XtreamVodStream(
            stream_id="12345",
            name="Test Movie",
            category_id="1",
            container_extension="",
            stream_icon=None,
            rating=None,
            rating_5based=None,
            added=None,
            custom_sid=None,
            direct_source=None,
            num=None
        )

        url = client.build_vod_stream_url(stream)

        assert "12345.mp4" in url


class TestValidateAccount:
    """Test account validation"""

    @pytest.mark.asyncio
    async def test_validate_account_success(self, credentials, mock_response):
        """Test successful account validation"""
        mock_response.json.return_value = {
            "user_info": {
                "status": "Active",
                "active_cons": 1,
                "max_connections": 1
            }
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)

            client = XtreamClient(credentials)
            response = await client.validate_account()

            assert response.user_info is not None
            assert response.user_info.status == "Active"

    @pytest.mark.asyncio
    async def test_validate_account_auth_failure_401(self, credentials):
        """Test authentication failure with 401"""
        mock_response = Mock()
        mock_response.status_code = 401
        error = HTTPStatusError("Unauthorized", request=Mock(), response=mock_response)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=error)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock()

            client = XtreamClient(credentials)
            with pytest.raises(XtreamAuthError):
                await client.validate_account()

    @pytest.mark.asyncio
    async def test_validate_account_connection_error(self, credentials):
        """Test connection error"""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RequestError("Connection failed"))

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock()

            client = XtreamClient(credentials)
            with pytest.raises(XtreamApiError):
                await client.validate_account()

    @pytest.mark.asyncio
    async def test_validate_account_invalid_json(self, credentials, mock_response):
        """Test invalid JSON response"""
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock()

            client = XtreamClient(credentials)
            with pytest.raises(XtreamApiError):
                await client.validate_account()


class TestGetVodCategories:
    """Test VOD categories fetching"""

    @pytest.mark.asyncio
    async def test_get_vod_categories_success(self, credentials, mock_response):
        """Test successful categories fetch"""
        mock_response.json.return_value = [
            {"category_id": "1", "category_name": "Action"},
            {"category_id": "2", "category_name": "Comedy"}
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock()

            client = XtreamClient(credentials)
            categories = await client.get_vod_categories()

            assert len(categories) == 2
            assert categories[0].category_name == "Action"
            assert categories[1].category_name == "Comedy"

    @pytest.mark.asyncio
    async def test_get_vod_categories_string_ids(self, credentials, mock_response):
        """Test categories with string IDs"""
        mock_response.json.return_value = [
            {"category_id": "abc123", "category_name": "Drama"},
            {"category_id": "xyz789", "category_name": "Horror"}
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock()

            client = XtreamClient(credentials)
            categories = await client.get_vod_categories()

            assert len(categories) == 2
            assert categories[0].category_id == "abc123"

    @pytest.mark.asyncio
    async def test_get_vod_categories_malformed_item(self, credentials, mock_response):
        """Test handling of malformed category items"""
        mock_response.json.return_value = [
            {"category_id": "1", "category_name": "Action"},
            {"invalid": "data"},  # This should be skipped
            {"category_id": "2", "category_name": "Comedy"}
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock()

            client = XtreamClient(credentials)
            categories = await client.get_vod_categories()

            # Should only return valid categories
            assert len(categories) == 2

    @pytest.mark.asyncio
    async def test_get_vod_categories_not_list(self, credentials, mock_response):
        """Test non-list response"""
        mock_response.json.return_value = {"error": "Invalid response"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock()

            client = XtreamClient(credentials)
            categories = await client.get_vod_categories()

            # Should return empty list instead of crashing
            assert categories == []


class TestGetVodStreams:
    """Test VOD streams fetching"""

    @pytest.mark.asyncio
    async def test_get_vod_streams_all(self, credentials, mock_response):
        """Test fetching all streams"""
        mock_response.json.return_value = [
            {
                "stream_id": "1",
                "name": "Movie 1",
                "category_id": "1",
                "container_extension": "mp4"
            },
            {
                "stream_id": "2",
                "name": "Movie 2",
                "category_id": "2",
                "container_extension": "mkv"
            }
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock()

            client = XtreamClient(credentials)
            streams = await client.get_vod_streams()

            assert len(streams) == 2
            assert streams[0].name == "Movie 1"
            assert streams[1].container_extension == "mkv"

    @pytest.mark.asyncio
    async def test_get_vod_streams_by_category(self, credentials, mock_response):
        """Test fetching streams by category"""
        mock_response.json.return_value = [
            {
                "stream_id": "1",
                "name": "Action Movie",
                "category_id": "1",
                "container_extension": "mp4"
            }
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock()

            client = XtreamClient(credentials)
            streams = await client.get_vod_streams(category_id="1")

            assert len(streams) == 1
            assert streams[0].category_id == "1"

    @pytest.mark.asyncio
    async def test_get_vod_streams_missing_optional_fields(self, credentials, mock_response):
        """Test streams with missing optional fields"""
        mock_response.json.return_value = [
            {
                "stream_id": "1",
                "name": "Minimal Movie",
                "category_id": "1"
                # Missing container_extension, should default to mp4
            }
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock()

            client = XtreamClient(credentials)
            streams = await client.get_vod_streams()

            assert len(streams) == 1
            assert streams[0].container_extension == "mp4"  # Default

    @pytest.mark.asyncio
    async def test_get_vod_streams_malformed_item(self, credentials, mock_response):
        """Test handling of malformed stream items"""
        mock_response.json.return_value = [
            {
                "stream_id": "1",
                "name": "Valid Movie",
                "category_id": "1",
                "container_extension": "mp4"
            },
            {"invalid": "data"},  # Should be skipped
            {
                "stream_id": "2",
                "name": "Another Valid",
                "category_id": "2",
                "container_extension": "mkv"
            }
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock()

            client = XtreamClient(credentials)
            streams = await client.get_vod_streams()

            assert len(streams) == 2


class TestValidateCredentials:
    """Test standalone credentials validation function"""

    @pytest.mark.asyncio
    async def test_validate_credentials_success(self, mock_response):
        """Test successful credential validation"""
        mock_response.json.return_value = {
            "user_info": {
                "status": "Active",
                "active_cons": 0,
                "max_connections": 1
            }
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock()

            success, message = await validate_credentials(
                "http://example.com:8080",
                "testuser",
                "testpass"
            )

            assert success is True
            assert "Connected as testuser" in message

    @pytest.mark.asyncio
    async def test_validate_credentials_failure(self):
        """Test failed credential validation"""
        mock_response = Mock()
        mock_response.status_code = 401
        error = HTTPStatusError("Unauthorized", request=Mock(), response=mock_response)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=error)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock()

            success, message = await validate_credentials(
                "http://example.com:8080",
                "baduser",
                "badpass"
            )

            assert success is False
            assert "Invalid" in message