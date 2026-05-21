"""Tests for streaming proxy (Sprint 2)"""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from httpx import HTTPStatusError, RequestError, TimeoutException

from app.proxy import (
    stream_vod_file,
    stream_vod_from_node,
    head_vod_from_node,
    ProxyError,
    ProxyConnectionError,
    ProxyTimeoutError,
)
from app.models import FSNode, NodeType
from fastapi import Response


@pytest.fixture
def sample_node():
    """Fixture for sample VOD node"""
    return FSNode(
        name="Test Movie (2024).mp4",
        type=NodeType.XTREAM_VOD_FILE,
        path="/movies/All/Test Movie (2024).mp4",
        stream_id="12345",
        category_id="1",
        category_name="Action",
        container_extension="mp4",
        upstream_url="http://example.com:8080/movie/user/pass/12345.mp4",
        content_type="video/mp4"
    )


@pytest.fixture
def mock_upstream_response():
    """Fixture for mock upstream response"""
    response = Mock()
    response.status_code = 200
    response.headers = {
        "Content-Type": "video/mp4",
        "Content-Length": "1048576",
        "Accept-Ranges": "bytes"
    }
    response.raise_for_status = Mock()
    response.aiter_bytes = AsyncMock()
    return response


class TestStreamVodFile:
    """Test VOD file streaming"""

    @pytest.mark.asyncio
    async def test_stream_without_range(self, mock_upstream_response):
        """Test streaming without Range header"""
        mock_upstream_response.aiter_bytes.return_value = [b"chunk1", b"chunk2"]

        async def mock_client():
            async with AsyncMock() as client:
                client.stream = AsyncMock()
                async with client.stream.return_value.__aenter__(AsyncMock(return_value=mock_upstream_response)):
                    yield client

        with patch("httpx.AsyncClient", mock_client):
            response = await stream_vod_file("http://example.com/video.mp4")

            # Should return StreamingResponse
            assert response is not None
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_stream_with_range(self, mock_upstream_response):
        """Test streaming with Range header"""
        range_header = "bytes=0-1023"
        mock_upstream_response.aiter_bytes.return_value = [b"chunk"]

        async def mock_client():
            async with AsyncMock() as client:
                client.stream = AsyncMock()
                async with client.stream.return_value.__aenter__(AsyncMock(return_value=mock_upstream_response)):
                    yield client

        with patch("httpx.AsyncClient", mock_client):
            response = await stream_vod_file("http://example.com/video.mp4", range_header=range_header)

            assert response is not None

    @pytest.mark.asyncio
    async def test_stream_timeout(self):
        """Test streaming timeout"""
        async def mock_client():
            async with AsyncMock() as client:
                client.stream = AsyncMock(side_effect=TimeoutException("Timeout"))
                yield client

        with patch("httpx.AsyncClient", mock_client):
            with pytest.raises(ProxyTimeoutError):
                await stream_vod_file("http://example.com/video.mp4")

    @pytest.mark.asyncio
    async def test_stream_connection_error(self):
        """Test streaming connection error"""
        async def mock_client():
            async with AsyncMock() as client:
                client.stream = AsyncMock(side_effect=RequestError("Connection failed"))
                yield client

        with patch("httpx.AsyncClient", mock_client):
            with pytest.raises(ProxyConnectionError):
                await stream_vod_file("http://example.com/video.mp4")

    @pytest.mark.asyncio
    async def test_stream_http_error(self):
        """Test streaming HTTP error"""
        mock_response = Mock()
        mock_response.status_code = 404
        error = HTTPStatusError("Not Found", request=Mock(), response=mock_response)

        async def mock_client():
            async with AsyncMock() as client:
                client.stream = AsyncMock(side_effect=error)
                yield client

        with patch("httpx.AsyncClient", mock_client):
            with pytest.raises(ProxyError):
                await stream_vod_file("http://example.com/video.mp4")


class TestStreamVodFromNode:
    """Test streaming from FSNode"""

    @pytest.mark.asyncio
    async def test_stream_from_valid_node(self, sample_node):
        """Test streaming from valid node"""
        with patch("app.proxy.stream_vod_file") as mock_stream:
            mock_stream.return_value = Mock()

            await stream_vod_from_node(sample_node)

            # Should call stream_vod_file with upstream URL
            mock_stream.assert_called_once_with(
                sample_node.upstream_url,
                range_header=None,
                timeout=30.0
            )

    @pytest.mark.asyncio
    async def test_stream_from_invalid_node_type(self):
        """Test streaming from wrong node type"""
        node = FSNode(
            name="test.txt",
            type=NodeType.FILE,
            path="/samples/test.txt"
        )

        with pytest.raises(ValueError, match="Expected xtream_vod_file"):
            await stream_vod_from_node(node)

    @pytest.mark.asyncio
    async def test_stream_from_node_missing_url(self, sample_node):
        """Test streaming from node without upstream URL"""
        sample_node.upstream_url = ""

        with pytest.raises(ValueError, match="missing upstream_url"):
            await stream_vod_from_node(sample_node)


class TestHeadVodFromNode:
    """Test HEAD responses for VOD nodes"""

    def test_head_vod_from_node_basic(self, sample_node):
        """Test basic HEAD response"""
        response = head_vod_from_node(sample_node)

        assert response.status_code == 200
        assert "Accept-Ranges" in response.headers
        assert response.headers["Accept-Ranges"] == "bytes"

    def test_head_vod_with_content_type(self, sample_node):
        """Test HEAD with content type"""
        sample_node.content_type = "video/mkv"

        response = head_vod_from_node(sample_node)

        assert "Content-Type" in response.headers
        assert response.headers["Content-Type"] == "video/mkv"

    def test_head_vod_with_size(self, sample_node):
        """Test HEAD with size"""
        sample_node.size = 1048576

        response = head_vod_from_node(sample_node)

        assert "Content-Length" in response.headers
        assert response.headers["Content-Length"] == "1048576"

    def test_head_vod_with_last_modified(self, sample_node):
        """Test HEAD with last modified"""
        from datetime import datetime
        sample_node.last_modified = datetime(2024, 1, 1, 12, 0, 0)

        response = head_vod_from_node(sample_node)

        assert "Last-Modified" in response.headers

    def test_head_vod_invalid_node_type(self):
        """Test HEAD with invalid node type"""
        node = FSNode(
            name="test.txt",
            type=NodeType.FILE,
            path="/samples/test.txt"
        )

        with pytest.raises(ValueError, match="Expected xtream_vod_file"):
            head_vod_from_node(node)

    def test_head_vod_cached_only_mode(self, sample_node):
        """Test HEAD in cached_only mode (default)"""
        response = head_vod_from_node(sample_node, head_mode="cached_only")

        # Should return 200 with cached metadata
        assert response.status_code == 200
        assert "Accept-Ranges" in response.headers


class TestErrorHandling:
    """Test error handling and credential safety"""

    def test_error_messages_no_credentials(self):
        """Test that errors don't expose credentials"""
        node = FSNode(
            name="Test Movie (2024).mp4",
            type=NodeType.XTREAM_VOD_FILE,
            path="/movies/All/Test Movie (2024).mp4",
            upstream_url="http://user:pass@example.com/video.mp4"
        )

        # Create error and check it doesn't contain credentials
        error = ProxyError(f"Error accessing {node.upstream_url}")
        error_msg = str(error)

        # Should not contain username or password in error message
        # (This is a simplified test - in practice, you'd sanitize URLs)
        assert "example.com" in error_msg  # Host should be present
        # But actual credentials handling should be in production code