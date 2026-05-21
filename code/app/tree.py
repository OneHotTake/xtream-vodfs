"""Virtual filesystem tree abstraction (Sprint 2 - Xtream VOD tree)"""

from typing import List, Optional, Dict, Set
from datetime import datetime
from pathlib import Path
from logging import getLogger

from app.models import FSNode, NodeType, XtreamCategory, XtreamVodStream
from app.naming import clean_title, extract_year, format_movie_name, handle_duplicate_filename, get_content_type

logger = getLogger(__name__)


class VirtualTree:
    """
    Virtual filesystem tree that builds Xtream VOD nodes from cache.
    Maintains Sprint 1 samples/ structure for config-free testing.
    """

    def __init__(self, cache=None, config=None):
        """
        Initialize virtual tree with cache and config.

        Args:
            cache: Cache instance with VOD categories and streams
            config: Config instance to check if Xtream is configured
        """
        self._cache = cache
        self._config = config
        self._root = self._build_tree()

    def _build_tree(self) -> FSNode:
        """Build the virtual tree combining VOD, series, and samples"""
        children = []

        # Build movies section with Xtream VOD data
        movies = self._build_vod_tree()
        children.append(movies)

        # Build series section (placeholder for Sprint 4)
        series = self._build_series_placeholder()
        children.append(series)

        # Build samples section (Sprint 1 - works without config)
        samples = self._build_samples_tree()
        children.append(samples)

        return FSNode(
            name="",
            type=NodeType.DIRECTORY,
            path="/",
            children=children
        )

    def _build_vod_tree(self) -> FSNode:
        """
        Build /fs/movies/ tree from Xtream VOD cache data.

        Returns:
            FSNode for /movies/ directory with all movies and category subdirectories
        """
        children = []

        # Check if cache is configured and has data
        if self._cache is None or self._cache.is_empty:
            # Add a placeholder message if not configured
            if self._config and hasattr(self._config, 'is_configured') and not self._config.is_configured():
                message = FSNode(
                    name="NOT_CONFIGURED.txt",
                    type=NodeType.FILE,
                    path="/movies/NOT_CONFIGURED.txt",
                    size=0,
                    last_modified=datetime.now()
                )
                children.append(message)
            return FSNode(
                name="movies",
                type=NodeType.DIRECTORY,
                path="/movies",
                children=children
            )

        # Build /fs/movies/All/ with all movies
        all_movies_node = self._build_all_movies_node()
        if all_movies_node:
            children.append(all_movies_node)

        # Build /fs/movies/{Category Name}/ for each category
        categories = self._cache.vod_categories
        for category in categories:
            category_node = self._build_category_node(category)
            if category_node:
                children.append(category_node)

        return FSNode(
            name="movies",
            type=NodeType.DIRECTORY,
            path="/movies",
            children=children
        )

    def _build_all_movies_node(self) -> Optional[FSNode]:
        """
        Build /fs/movies/All/ node with all movies.

        Returns:
            FSNode for /movies/All/ or None if no movies available
        """
        if self._cache is None:
            return None

        streams = self._cache.vod_streams
        if not streams:
            return None

        movie_nodes = []
        used_filenames: Set[str] = set()

        for stream in streams:
            # Build filename using naming utilities
            movie_node = self._build_movie_node(
                stream=stream,
                parent_path="/movies/All",
                used_filenames=used_filenames
            )
            if movie_node:
                movie_nodes.append(movie_node)
                used_filenames.add(movie_node.name)

        if not movie_nodes:
            return None

        return FSNode(
            name="All",
            type=NodeType.DIRECTORY,
            path="/movies/All",
            children=movie_nodes
        )

    def _build_category_node(self, category: XtreamCategory) -> Optional[FSNode]:
        """
        Build /fs/movies/{Category Name}/ node with movies in that category.

        Args:
            category: Xtream category object

        Returns:
            FSNode for category directory or None if no movies in category
        """
        if self._cache is None:
            return None

        streams = self._cache.get_streams_by_category(category.category_id)
        if not streams:
            return None

        movie_nodes = []
        used_filenames: Set[str] = set()

        for stream in streams:
            # Build filename using naming utilities
            movie_node = self._build_movie_node(
                stream=stream,
                parent_path=f"/movies/{clean_title(category.category_name)}",
                used_filenames=used_filenames
            )
            if movie_node:
                movie_nodes.append(movie_node)
                used_filenames.add(movie_node.name)

        if not movie_nodes:
            return None

        category_name = clean_title(category.category_name)
        return FSNode(
            name=category_name,
            type=NodeType.DIRECTORY,
            path=f"/movies/{category_name}",
            children=movie_nodes
        )

    def _build_movie_node(self, stream: XtreamVodStream, parent_path: str, used_filenames: Set[str]) -> Optional[FSNode]:
        """
        Build a single movie node from Xtream stream data.

        Args:
            stream: Xtream VOD stream object
            parent_path: Parent directory path
            used_filenames: Set of already used filenames for duplicate detection

        Returns:
            FSNode for movie or None if invalid data
        """
        if not stream.name or not stream.stream_id:
            return None

        # Get category information
        category = self._cache.get_category(stream.category_id) if self._cache else None
        category_name = category.category_name if category else "Unknown"
        category_id = stream.category_id or ""

        # Format movie name with year
        year = extract_year(stream.name)
        base_name = format_movie_name(stream.name, year)

        # Build filename
        extension = stream.container_extension or "mp4"
        filename = f"{base_name}.{extension}"

        # Handle duplicates
        if filename in used_filenames:
            filename = handle_duplicate_filename(base_name, extension, stream.stream_id)

        # Build upstream URL
        if self._config and self._config.xtream and self._config.xtream.base_url:
            base_url = self._config.xtream.base_url.rstrip('/')
            username = self._config.xtream.username
            password = self._config.xtream.password
            upstream_url = f"{base_url}/movie/{username}/{password}/{stream.stream_id}.{extension}"
        else:
            upstream_url = ""

        # Get content type from extension
        content_type = get_content_type(extension)

        # Determine size (not available from Xtream API, use None)
        size = None

        # Determine last modified (not available from Xtream API, use None or added timestamp)
        last_modified = None
        if stream.added:
            try:
                last_modified = datetime.fromtimestamp(stream.added)
            except (ValueError, TypeError):
                pass

        # Create the FSNode with XTREAM_VOD_FILE type
        node = FSNode(
            name=filename,
            type=NodeType.XTREAM_VOD_FILE,
            path=f"{parent_path}/{filename}",
            size=size,
            last_modified=last_modified or datetime.now(),
            stream_id=stream.stream_id,
            category_id=category_id,
            category_name=category_name,
            container_extension=extension,
            upstream_url=upstream_url,
            content_type=content_type
        )

        return node

    def _build_series_placeholder(self) -> FSNode:
        """
        Build /fs/series/ placeholder for Sprint 4.

        Returns:
            FSNode for /series/ with placeholder message
        """
        message = FSNode(
            name="COMING_SOON.txt",
            type=NodeType.FILE,
            path="/series/COMING_SOON.txt",
            size=0,
            last_modified=datetime.now()
        )

        return FSNode(
            name="series",
            type=NodeType.DIRECTORY,
            path="/series",
            children=[message]
        )

    def _build_samples_tree(self) -> FSNode:
        """
        Build /fs/samples/ tree from Sprint 1 (works without config).

        Returns:
            FSNode for /samples/ with sample files
        """
        hello = FSNode(
            name="hello.txt",
            type=NodeType.FILE,
            path="/samples/hello.txt",
            size=14,
            last_modified=datetime(2024, 1, 1, 0, 0, 0)
        )

        return FSNode(
            name="samples",
            type=NodeType.DIRECTORY,
            path="/samples",
            children=[hello]
        )

    def resolve(self, path: str) -> Optional[FSNode]:
        if not path or path == "/":
            return self._root
        path = path.rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        components = [c for c in path.split("/") if c]
        current = self._root
        for component in components:
            if current.children is None:
                return None
            found = None
            for child in current.children:
                if child.name == component:
                    found = child
                    break
            if found is None:
                return None
            current = found
        return current

    def get_parent(self, path: str) -> Optional[FSNode]:
        if not path or path == "/":
            return None
        path = path.rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        parent_path = "/".join(path.split("/")[:-1]) or "/"
        return self.resolve(parent_path)