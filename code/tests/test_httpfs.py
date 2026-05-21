"""Tests for HTTP filesystem (Sprint 1)"""

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from pathlib import Path
import tempfile

from app.main import app
from app.tree import VirtualTree
from app.httpfs import HTTPFilesystem


client = TestClient(app)


def test_healthz_returns_ok():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "sprint": 1}


def test_root_returns_status_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "xtream-vodfs Sprint 1" in response.text
    assert "Running" in response.text


def test_fs_root_returns_html():
    response = client.get("/fs/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Index of /fs/" in response.text


def test_fs_directory_listing_has_escaped_hrefs():
    response = client.get("/fs/movies/All/")
    assert response.status_code == 200
    assert "Big%20Buck%20Bunny%20%282008%29.mp4" in response.text
    assert "Sintel%20%282010%29.mp4" in response.text


def test_fs_directory_listing_has_parent_link():
    response = client.get("/fs/movies/All/")
    assert response.status_code == 200
    assert "../" in response.text


def test_fs_root_no_parent_link():
    response = client.get("/fs/")
    assert response.status_code == 200
    assert "../" not in response.text


def test_fs_directory_ends_with_slash():
    response = client.get("/fs/")
    assert response.status_code == 200
    assert "movies/" in response.text
    assert "series/" in response.text
    assert "samples/" in response.text


def test_fs_without_trailing_slash_redirects():
    response = client.get("/fs/movies", follow_redirects=False)
    assert response.status_code == 301
    assert "location" in response.headers
    assert response.headers["location"] == "/fs/movies/"


def test_fs_file_serves_content():
    response = client.get("/fs/samples/hello.txt")
    assert response.status_code == 200
    assert response.content == b"Hello, World!\n"
    assert "text/plain" in response.headers["content-type"]


def test_fs_file_not_found():
    response = client.get("/fs/samples/nonexistent.txt")
    assert response.status_code == 404


def test_fs_directory_not_found():
    response = client.get("/fs/nonexistent/")
    assert response.status_code == 404


def test_head_file_returns_headers():
    response = client.head("/fs/samples/hello.txt")
    assert response.status_code == 200
    assert "accept-ranges" in response.headers
    assert response.headers["accept-ranges"] == "bytes"
    assert "content-length" in response.headers
    assert "content-type" in response.headers


def test_head_directory_returns_200():
    response = client.head("/fs/movies/All/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_head_directory_without_slash_redirects():
    response = client.head("/fs/movies", follow_redirects=False)
    assert response.status_code == 301
    assert "location" in response.headers


def test_head_file_not_found():
    response = client.head("/fs/samples/nonexistent.txt")
    assert response.status_code == 404


def test_get_file_with_range():
    response = client.get("/fs/samples/hello.txt", headers={"Range": "bytes=0-4"})
    assert response.status_code == 206
    assert "accept-ranges" in response.headers
    assert "content-range" in response.headers
    assert response.content == b"Hello"


def test_get_file_with_range_full():
    response = client.get("/fs/samples/hello.txt", headers={"Range": "bytes=0-13"})
    assert response.status_code == 206
    assert response.content == b"Hello, World!\n"


def test_get_file_with_invalid_range():
    response = client.get("/fs/samples/hello.txt", headers={"Range": "bytes=100-200"})
    assert response.status_code == 416


def test_get_file_with_start_only():
    response = client.get("/fs/samples/hello.txt", headers={"Range": "bytes=7-"})
    assert response.status_code == 206
    assert response.content == b"World!\n"


def test_get_file_with_suffix_range():
    response = client.get("/fs/samples/hello.txt", headers={"Range": "bytes=-6"})
    assert response.status_code == 206
    assert response.content == b"orld!\n"


def test_directory_listing_structure():
    response = client.get("/fs/movies/All/")
    assert response.status_code == 200
    assert "<!doctype html>" in response.text.lower()
    assert "<html>" in response.text
    assert "<head>" in response.text
    assert "<body>" in response.text
    assert "<h1>" in response.text
    assert "<pre>" in response.text
    assert "<a href=" in response.text


def test_multiple_levels_deep():
    response = client.get("/fs/series/Example Show (2024)/Season 01/")
    assert response.status_code == 200
    assert "Index of /fs/series/Example Show (2024)/Season 01/" in response.text


def test_movie_file_in_multiple_categories():
    response = client.get("/fs/movies/All/")
    assert response.status_code == 200
    assert "Big Buck Bunny (2008).mp4" in response.text
    response = client.get("/fs/movies/Action/")
    assert response.status_code == 200
    assert "Big Buck Bunny (2008).mp4" in response.text


def test_parse_range_header_valid():
    tree = VirtualTree()
    httpfs = HTTPFilesystem(tree, "")
    start, end = httpfs._parse_range_header("bytes=0-99", 1000)
    assert start == 0
    assert end == 99
    start, end = httpfs._parse_range_header("bytes=500-", 1000)
    assert start == 500
    assert end == 999
    start, end = httpfs._parse_range_header("bytes=-100", 1000)
    assert start == 900
    assert end == 999


def test_parse_range_header_invalid():
    tree = VirtualTree()
    httpfs = HTTPFilesystem(tree, "")
    with pytest.raises(ValueError):
        httpfs._parse_range_header("bits=0-99", 1000)
    with pytest.raises(ValueError):
        httpfs._parse_range_header("bytes=900-1000", 1000)
    with pytest.raises(ValueError):
        httpfs._parse_range_header("bytes=0-99-199", 1000)
    with pytest.raises(ValueError):
        httpfs._parse_range_header("bytes=200-100", 1000)


def test_media_type_detection():
    tree = VirtualTree()
    httpfs = HTTPFilesystem(tree, "")
    assert httpfs._get_media_type_by_name("file.txt") == "text/plain"
    assert httpfs._get_media_type_by_name("file.mp4") == "video/mp4"
    assert httpfs._get_media_type_by_name("file.mkv") == "video/x-matroska"
    assert httpfs._get_media_type_by_name("file.avi") == "video/x-msvideo"
    assert httpfs._get_media_type_by_name("file.webm") == "video/webm"
    assert httpfs._get_media_type_by_name("file.unknown") == "application/octet-stream"
