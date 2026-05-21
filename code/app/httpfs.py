"""HTTP filesystem handlers for serving virtual files and directories"""

import time
import urllib.parse
from datetime import datetime
from typing import Dict, Optional, Tuple
from pathlib import Path

from fastapi import Request, Response, HTTPException
from fastapi.responses import FileResponse

from app.models import FSNode, NodeType
from app.tree import VirtualTree
from app.cache import Cache


# Known media scanner user-agent fragments
SCANNER_AGENTS = [
    "plex",
    "emby",
    "jellyfin",
    "kodi",
    "infuse",
    "vlc",
    "subsonic",
    "navidrome",
    "androidmedia",
    "applecoremedia",
]


class HTTPFilesystem:
    def __init__(self, tree: VirtualTree, media_dir: str,
                 cache: Optional[Cache] = None):
        self.tree = tree
        self.media_dir = Path(media_dir)
        # Scanner detection state: {client_ip: {"last_access": float, "count": int}}
        self._scan_tracker: Dict[str, Dict] = {}
        # Content-Type cache: {extension: content_type}
        self._content_type_cache: Dict[str, str] = {}
        # Directory listing cache: {path: (html, timestamp)}
        self._dir_listing_cache: Dict[str, Tuple[str, float]] = {}
        # Scanner detection enabled flag (set from config)
        self.enable_scanner_detection: bool = True
        # Content-Type cache enabled flag
        self.cache_content_type: bool = True
        # Directory listing cache TTL in seconds
        self.dir_listing_cache_ttl: int = 60

    def is_scanner(self, request: Request) -> bool:
        """Detect if request is from a media scanner (Plex, Emby, Jellyfin, etc.)

        Returns True if the User-Agent suggests a scanner client.
        """
        if not self.enable_scanner_detection:
            return False
        user_agent = request.headers.get("user-agent", "")
        ua_lower = user_agent.lower()
        for agent in SCANNER_AGENTS:
            if agent in ua_lower:
                return True
        return False

    def _track_scanner_access(self, request: Request) -> bool:
        """Track rapid directory listing accesses from the same client.

        Returns True if the client is detected as a scanner (rapid pattern).
        Adds a small sleep for detected scanners to reduce load.
        """
        if not self.enable_scanner_detection:
            return False
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        state = self._scan_tracker.get(client_ip, {"last_access": 0.0, "count": 0})

        # Reset counter if more than 2 seconds have passed
        if now - state["last_access"] > 2.0:
            state["count"] = 0

        state["last_access"] = now
        state["count"] += 1
        self._scan_tracker[client_ip] = state

        # If more than 5 accesses in under 2 seconds, slow down
        if state["count"] > 5:
            time.sleep(0.1)  # 100ms delay for scanner
            return True
        return False

    def get_directory_listing(self, path: str, request: Optional[Request] = None) -> str:
        # Check cache first (if enabled)
        if self.dir_listing_cache_ttl > 0:
            cached = self._dir_listing_cache.get(path)
            if cached:
                html, timestamp = cached
                if time.time() - timestamp < self.dir_listing_cache_ttl:
                    return html

        node = self.tree.resolve(path)
        if node is None:
            raise HTTPException(status_code=404, detail="Not found")
        if not node.is_directory():
            raise HTTPException(status_code=404, detail="Not a directory")

        # Track scanner access if we have request context
        if request is not None:
            is_scanner = self.is_scanner(request)
            if is_scanner:
                self._track_scanner_access(request)
            else:
                # Still track for rapid-access detection
                self._track_scanner_access(request)

        entries = []
        if path != "/" and path != "":
            entries.append({"name": "../", "href": "../"})

        if node.children:
            sorted_children = sorted(node.children, key=lambda n: (not n.is_directory(), n.name.lower()))
            for child in sorted_children:
                if child.is_directory():
                    entries.append({"name": child.name + "/", "href": urllib.parse.quote(child.name + "/")})
                else:
                    entries.append({"name": child.name, "href": urllib.parse.quote(child.name)})

        from jinja2 import Environment, FileSystemLoader, select_autoescape
        env = Environment(loader=FileSystemLoader(str(Path(__file__).parent / "templates")), autoescape=select_autoescape(['html', 'xml']))
        template = env.get_template("listing.html")
        html = template.render(title=f"Index of /fs{path}", path=f"/fs{path}", entries=entries)

        # Cache the result
        if self.dir_listing_cache_ttl > 0:
            self._dir_listing_cache[path] = (html, time.time())

        return html

    def serve_file(self, path: str, range_header: Optional[str] = None) -> Response:
        node = self.tree.resolve(path)
        if node is None:
            raise HTTPException(status_code=404, detail="Not found")
        if not node.is_file():
            raise HTTPException(status_code=404, detail="Not a file")

        local_path = self._get_local_file_path(node.name)
        if not local_path or not local_path.exists():
            return self._serve_generated_content(node, range_header)
        return self._serve_local_file(local_path, range_header)

    def _get_local_file_path(self, filename: str) -> Optional[Path]:
        if filename == "hello.txt":
            return self.media_dir / "hello.txt"
        if filename.endswith(".mp4"):
            sample_mp4 = self.media_dir / "sample.mp4"
            if sample_mp4.exists():
                return sample_mp4
        return None

    def _serve_local_file(self, local_path: Path, range_header: Optional[str] = None) -> Response:
        file_size = local_path.stat().st_size
        if range_header is None:
            return FileResponse(local_path, media_type=self._get_media_type(local_path),
                headers={"Accept-Ranges": "bytes", "Content-Length": str(file_size),
                    "Last-Modified": datetime.fromtimestamp(local_path.stat().st_mtime).strftime("%a, %d %b %Y %H:%M:%S GMT")})
        try:
            start, end = self._parse_range_header(range_header, file_size)
        except ValueError:
            raise HTTPException(status_code=416, detail="Range Not Satisfiable")

        with open(local_path, "rb") as f:
            f.seek(start)
            content = f.read(end - start + 1)
        return Response(content=content, status_code=206, media_type=self._get_media_type(local_path),
            headers={"Accept-Ranges": "bytes", "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(len(content)),
                "Last-Modified": datetime.fromtimestamp(local_path.stat().st_mtime).strftime("%a, %d %b %Y %H:%M:%S GMT")})

    def _serve_generated_content(self, node: FSNode, range_header: Optional[str] = None) -> Response:
        if node.name == "hello.txt":
            content = b"Hello, World!\n"
        else:
            content = b"Placeholder video content"
        content_size = len(content)
        if range_header is None:
            return Response(content=content, media_type=self._get_media_type_by_name(node.name),
                headers={"Accept-Ranges": "bytes", "Content-Length": str(content_size),
                    "Last-Modified": node.last_modified.strftime("%a, %d %b %Y %H:%M:%S GMT") if node.last_modified else ""})
        try:
            start, end = self._parse_range_header(range_header, content_size)
        except ValueError:
            raise HTTPException(status_code=416, detail="Range Not Satisfiable")
        partial = content[start:end + 1]
        return Response(content=partial, status_code=206, media_type=self._get_media_type_by_name(node.name),
            headers={"Accept-Ranges": "bytes", "Content-Range": f"bytes {start}-{end}/{content_size}",
                "Content-Length": str(len(partial)),
                "Last-Modified": node.last_modified.strftime("%a, %d %b %Y %H:%M:%S GMT") if node.last_modified else ""})

    def _parse_range_header(self, range_header: str, file_size: int) -> tuple[int, int]:
        if not range_header.startswith("bytes="):
            raise ValueError("Invalid range unit")
        range_spec = range_header[6:]
        if "-" not in range_spec:
            raise ValueError("Invalid range format")
        parts = range_spec.split("-")
        if len(parts) != 2:
            raise ValueError("Invalid range format")
        start_str, end_str = parts
        if start_str == "":
            start = max(0, file_size - int(end_str))
            end = file_size - 1
        else:
            start = int(start_str)
            if end_str == "":
                end = file_size - 1
            else:
                end = int(end_str)
        if start < 0 or end >= file_size or start > end:
            raise ValueError("Range out of bounds")
        return start, end

    def _get_media_type(self, path: Path) -> str:
        return self._get_media_type_by_name(path.name)

    def _get_media_type_by_name(self, filename: str) -> str:
        # Extract extension and check cache
        ext = Path(filename).suffix.lower()

        if self.cache_content_type and ext in self._content_type_cache:
            return self._content_type_cache[ext]

        if ext == ".txt":
            ct = "text/plain"
        elif ext == ".mp4":
            ct = "video/mp4"
        elif ext == ".mkv":
            ct = "video/x-matroska"
        elif ext == ".avi":
            ct = "video/x-msvideo"
        elif ext == ".webm":
            ct = "video/webm"
        else:
            ct = "application/octet-stream"

        # Cache the result for future lookups
        if self.cache_content_type:
            self._content_type_cache[ext] = ct

        return ct

    def head_file(self, path: str) -> Response:
        """Handle HEAD for files - always synthetic, no upstream calls."""
        node = self.tree.resolve(path)
        if node is None:
            raise HTTPException(status_code=404, detail="Not found")
        if not node.is_file():
            raise HTTPException(status_code=404, detail="Not a file")

        # Local files
        local_path = self._get_local_file_path(node.name)
        if local_path and local_path.exists():
            file_size = local_path.stat().st_size
            last_modified = datetime.fromtimestamp(local_path.stat().st_mtime).strftime("%a, %d %b %Y %H:%M:%S GMT")
            content_type = self._get_media_type_by_name(node.name)
            return Response(status_code=200, media_type=content_type,
                headers={"Accept-Ranges": "bytes",
                    "Content-Length": str(file_size), "Last-Modified": last_modified})

        # Xtream VOD file - synthetic, no upstream call
        if node.type == NodeType.XTREAM_VOD_FILE:
            return Response(status_code=200,
                media_type=node.content_type or self._get_media_type_by_name(node.name),
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(1024 * 1024),  # 1MB synthetic
                    "Last-Modified": node.last_modified.strftime("%a, %d %b %Y %H:%M:%S GMT") if node.last_modified else "Wed, 01 Jan 2020 00:00:00 GMT"
                })

        # Regular virtual file
        content_type = self._get_media_type_by_name(node.name)
        return Response(status_code=200, media_type=content_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(node.size) if node.size else "",
                "Last-Modified": node.last_modified.strftime("%a, %d %b %Y %H:%M:%S GMT") if node.last_modified else "",
            })

    def head_directory(self, path: str, has_trailing_slash: bool) -> Response:
        node = self.tree.resolve(path)
        if node is None:
            raise HTTPException(status_code=404, detail="Not found")
        if not node.is_directory():
            raise HTTPException(status_code=404, detail="Not a directory")
        if not has_trailing_slash:
            return Response(status_code=301, headers={"Location": f"/fs{path.rstrip('/')}/"})
        return Response(status_code=200, media_type="text/html", headers={"Content-Type": "text/html"})
