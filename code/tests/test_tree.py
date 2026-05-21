"""Tests for virtual tree (Sprint 1)"""

import pytest
from app.tree import VirtualTree
from app.models import NodeType


def test_root_resolves():
    tree = VirtualTree()
    root = tree.resolve("/")
    assert root is not None
    assert root.is_directory()
    assert root.name == ""
    assert root.path == "/"


def test_movies_resolves():
    tree = VirtualTree()
    node = tree.resolve("/movies")
    assert node is not None
    assert node.is_directory()
    assert node.name == "movies"
    assert node.path == "/movies"


def test_movies_all_resolves():
    tree = VirtualTree()
    node = tree.resolve("/movies/All")
    assert node is not None
    assert node.is_directory()
    assert node.name == "All"
    assert node.path == "/movies/All"


def test_movies_all_file_resolves():
    tree = VirtualTree()
    node = tree.resolve("/movies/All/Big Buck Bunny (2008).mp4")
    assert node is not None
    assert node.is_file()
    assert node.name == "Big Buck Bunny (2008).mp4"
    assert node.path == "/movies/All/Big Buck Bunny (2008).mp4"
    assert node.size is not None


def test_series_resolves():
    tree = VirtualTree()
    node = tree.resolve("/series")
    assert node is not None
    assert node.is_directory()
    assert node.name == "series"


def test_series_show_resolves():
    tree = VirtualTree()
    node = tree.resolve("/series/Example Show (2024)")
    assert node is not None
    assert node.is_directory()
    assert node.name == "Example Show (2024)"


def test_series_season_resolves():
    tree = VirtualTree()
    node = tree.resolve("/series/Example Show (2024)/Season 01")
    assert node is not None
    assert node.is_directory()
    assert node.name == "Season 01"


def test_series_episode_resolves():
    tree = VirtualTree()
    node = tree.resolve("/series/Example Show (2024)/Season 01/Example Show - S01E01 - Pilot.mp4")
    assert node is not None
    assert node.is_file()
    assert node.name == "Example Show - S01E01 - Pilot.mp4"


def test_samples_resolves():
    tree = VirtualTree()
    node = tree.resolve("/samples")
    assert node is not None
    assert node.is_directory()
    assert node.name == "samples"


def test_hello_txt_resolves():
    tree = VirtualTree()
    node = tree.resolve("/samples/hello.txt")
    assert node is not None
    assert node.is_file()
    assert node.name == "hello.txt"
    assert node.size == 14


def test_missing_path_returns_none():
    tree = VirtualTree()
    assert tree.resolve("/nonexistent") is None
    assert tree.resolve("/movies/Nonexistent") is None
    assert tree.resolve("/series/Example Show (2024)/Season 02") is None


def test_parent_directory():
    tree = VirtualTree()
    parent = tree.get_parent("/movies/All/Big Buck Bunny (2008).mp4")
    assert parent is not None
    assert parent.is_directory()
    assert parent.name == "All"


def test_root_parent_is_none():
    tree = VirtualTree()
    parent = tree.get_parent("/")
    assert parent is None


def test_movies_children_count():
    tree = VirtualTree()
    node = tree.resolve("/movies")
    assert node is not None
    assert node.children is not None
    assert len(node.children) == 2


def test_movies_all_children_count():
    tree = VirtualTree()
    node = tree.resolve("/movies/All")
    assert node is not None
    assert node.children is not None
    assert len(node.children) == 2


def test_path_without_leading_slash():
    tree = VirtualTree()
    node = tree.resolve("movies/All")
    assert node is not None
    assert node.is_directory()
    assert node.name == "All"
