"""FastAPI app for xtream-vodfs Sprint 3

CDN direct URL exposure, scanner detection, content-type normalization, performance improvements,
streaming reliability, rate limiting, and head_mode caching.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request, Response, HTTPException, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from app.tree import VirtualTree
from app.httpfs import HTTPFilesystem
from app.config import Config, ConfigManager, get_config_manager, get_active_providers, load_config, save_config
from app.cache import Cache, get_cache
from app.metadata_cache import MetadataCache, get_metadata_cache
from app.xtream import XtreamClient, validate_credentials
from app.proxy import stream_vod_from_node, get_rate_limiter
from app.warmer import MetadataWarmer
from app.models import NodeType


app = FastAPI(title="xtream-vodfs", description="Local HTTP virtual filesystem for Xtream Codes VOD and Series", version="0.3.0 (Sprint 3)")

BASE_DIR = Path(__file__).parent.parent
MEDIA_DIR = BASE_DIR / "sample_media"

# Global instances
config_manager: Optional[ConfigManager] = None
config: Optional[Config] = None
cache: Optional[Cache] = None
tree: Optional[VirtualTree] = None
httpfs: Optional[HTTPFilesystem] = None
metadata_cache: Optional[MetadataCache] = None
warmer: Optional[MetadataWarmer] = None


class ConfigForm(BaseModel):
    """Form data for config submission"""
    base_url: str
    username: str
    password: str
    enable_vod: bool = True
    movies_include_all: bool = True
    movies_include_categories: bool = True


@app.on_event("startup")
async def startup_event():
    """Initialize app components on startup"""
    global config_manager, config, cache, tree, httpfs, metadata_cache, warmer

    config_manager = get_config_manager()
    config = config_manager.load()

    cache = get_cache()

    # Try to load cache from disk
    cache_loaded = cache.load_from_disk()
    if cache_loaded:
        print(f"Loaded cache from disk: {len(cache.vod_categories)} categories, {len(cache.vod_streams)} streams")

    # Load metadata cache
    metadata_cache = get_metadata_cache()
    metadata_cache_loaded = metadata_cache.load_from_disk()
    if metadata_cache_loaded:
        print(f"Loaded metadata cache from disk: {metadata_cache.count()} entries")

    # Build tree
    active_providers = get_active_providers(config)
    if active_providers:
        # Multi-provider mode: try to refresh to get full data
        if cache_loaded:
            try:
                await refresh_vod_cache()
            except Exception as e:
                logger.warning(f"Failed to refresh cache on startup: {e}")
                # Fall back to single-provider mode with existing cache
                tree = VirtualTree(cache=cache if not cache.is_empty else None, config=config)
        else:
            tree = VirtualTree(cache=None, config=config)
    else:
        # Single-provider mode or not configured
        tree = VirtualTree(cache=cache if not cache.is_empty else None, config=config)

    httpfs = HTTPFilesystem(tree, str(MEDIA_DIR), metadata_cache=metadata_cache)
    _apply_httpfs_config()


def _apply_httpfs_config():
    """Apply HTTP filesystem settings from current config"""
    global httpfs, config
    if httpfs and config:
        httpfs.enable_scanner_detection = config.httpfs.enable_scanner_detection
        httpfs.cache_content_type = config.httpfs.cache_content_type
        httpfs.dir_listing_cache_ttl = config.httpfs.dir_listing_cache_ttl


async def refresh_vod_cache():
    """Refresh VOD cache for all configured providers."""
    global config, cache, tree, httpfs, metadata_cache, warmer

    if not config or not config_manager:
        raise HTTPException(status_code=400, detail="Config not loaded")

    active_providers = get_active_providers(config)
    if not active_providers:
        raise HTTPException(status_code=400, detail="No Xtream providers configured")

    try:
        all_categories = []
        all_streams = []
        providers_data = []          # For warmer: (name, creds, streams)
        providers_tree_data = []     # For tree: (name, categories, streams)

        # Fetch data from each provider
        for creds in active_providers:
            async with XtreamClient(creds, timeout=30.0) as client:
                # Validate credentials
                await client.validate_account()

                # Fetch categories and streams
                categories = await client.get_vod_categories()
                streams = await client.get_vod_streams()

                all_categories.extend(categories)
                all_streams.extend(streams)

                # Store for tree building (needs categories + streams)
                providers_tree_data.append((creds.provider_name, categories, streams))
                # Store for warming (needs credentials)
                providers_data.append((creds.provider_name, creds, streams))

                logger.info(
                    f"Fetched {len(categories)} categories and {len(streams)} streams "
                    f"from provider {creds.provider_name}"
                )

        # Update cache with all data
        if cache:
            cache.refresh(all_categories, all_streams)
            cache.save_to_disk()

        # Build tree with multi-provider data
        tree = VirtualTree(
            cache=cache if cache and not cache.is_empty else None,
            config=config,
            providers=providers_tree_data
        )
        httpfs = HTTPFilesystem(tree, str(MEDIA_DIR), metadata_cache=metadata_cache)
        _apply_httpfs_config()

        # Start warmer in background
        if config.metadata_warmer.enabled and metadata_cache:
            global warmer
            warmer = MetadataWarmer(metadata_cache, providers_data, config.metadata_warmer)
            asyncio.create_task(warmer.start())

        return sum(len(cats) for _, cats, _ in providers_tree_data), sum(len(streams) for _, _, streams in providers_tree_data)

    except Exception as e:
        # Sanitize error message
        error_msg = str(e)
        if config:
            for creds in get_active_providers(config):
                error_msg = error_msg.replace(creds.username, "USERNAME")
                error_msg = error_msg.replace(creds.password, "PASSWORD")
        raise HTTPException(status_code=500, detail=f"Failed to refresh VOD cache: {error_msg}")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Main status and configuration page"""
    is_configured = config_manager.is_configured() if config_manager else False
    vod_categories = len(cache.vod_categories) if cache else 0
    vod_streams = len(cache.vod_streams) if cache else 0
    last_refresh = cache.last_refresh.isoformat() if cache and cache.last_refresh else "Never"

    html = f"""<!doctype html>
<html>
<head>
    <title>xtream-vodfs - Sprint 2</title>
    <meta charset="utf-8">
    <style>
        body {{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,Ubuntu,sans-serif;max-width:900px;margin:40px auto;padding:20px;line-height:1.6}}
        h1 {{color:#333;border-bottom:2px solid #007bff;padding-bottom:10px}}
        .status {{background:#d4edda;color:#155724;padding:15px;border-radius:5px;margin:20px 0}}
        .status.not-configured {{background:#fff3cd;color:#856404}}
        .info {{background:#f8f9fa;padding:15px;border-radius:5px;margin:20px 0;border:1px solid #dee2e6}}
        .form-group {{margin-bottom:15px}}
        label {{display:block;margin-bottom:5px;font-weight:600}}
        input[type="text"], input[type="password"] {{width:100%;padding:8px;border:1px solid #ddd;border-radius:4px;box-sizing:border-box}}
        button {{background:#007bff;color:#fff;padding:10px 20px;border:none;border-radius:4px;cursor:pointer;font-size:16px}}
        button:hover {{background:#0056b3}}
        button:disabled {{background:#6c757d;cursor:not-allowed}}
        .links {{margin:20px 0}}
        .links a {{display:block;margin:8px 0;color:#0066cc;text-decoration:none}}
        .links a:hover {{text-decoration:underline}}
        .stats {{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:15px;margin:20px 0}}
        .stat {{background:#e9ecef;padding:15px;border-radius:5px;text-align:center}}
        .stat-value {{font-size:2em;font-weight:bold;color:#007bff}}
        .stat-label {{color:#666;font-size:0.9em}}
    </style>
</head>
<body>
<h1>xtream-vodfs - Sprint 2</h1>
<div class="status {'not-configured' if not is_configured else ''}">
    <strong>Status:</strong> {'' if is_configured else 'Not '}Configured
</div>
<div class="stats">
    <div class="stat">
        <div class="stat-value">{vod_categories}</div>
        <div class="stat-label">VOD Categories</div>
    </div>
    <div class="stat">
        <div class="stat-value">{vod_streams}</div>
        <div class="stat-label">VOD Streams</div>
    </div>
</div>
<div class="info">
    <h3>Configuration</h3>
    <form method="post" action="/config">
        <div class="form-group">
            <label for="base_url">Xtream Base URL:</label>
            <input type="text" id="base_url" name="base_url" placeholder="http://example.com:8080" value="{config.xtream.base_url if config and config.xtream.base_url else ''}" required>
        </div>
        <div class="form-group">
            <label for="username">Username:</label>
            <input type="text" id="username" name="username" placeholder="your_username" value="{config.xtream.username if config and config.xtream.username else ''}" required>
        </div>
        <div class="form-group">
            <label for="password">Password:</label>
            <input type="password" id="password" name="password" placeholder="your_password" value="{config.xtream.password if config and config.xtream.password else ''}" required>
        </div>
        <button type="submit">Save & Validate Credentials</button>
    </form>
    <form method="post" action="/refresh" style="margin-top: 20px;">
        <button type="submit" {'disabled' if not is_configured else ''}>Refresh VOD Cache</button>
    </form>
    <p style="margin-top: 15px; color: #666; font-size: 0.9em;">
        Last refresh: {last_refresh}
    </p>
</div>
<div class="links">
    <h3>Virtual Filesystem:</h3>
    <a href="/fs/">/fs/</a> - Virtual filesystem root
    <a href="/fs/movies/">/fs/movies/</a> - Movies (requires Xtream config)
    <a href="/fs/series/">/fs/series/</a> - Series (Sprint 4)
    <a href="/fs/samples/">/fs/samples/</a> - Sample files
</div>
<div class="info">
    <h3>Health Check:</h3>
    <p><a href="/healthz">/healthz</a> - JSON status</p>
</div>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.post("/config", response_class=HTMLResponse)
async def save_config_route(
    base_url: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    enable_vod: bool = Form(True),
    movies_include_all: bool = Form(True),
    movies_include_categories: bool = Form(True)
):
    """Save Xtream credentials and validate"""
    global config

    try:
        # Validate credentials
        success, message = await validate_credentials(base_url, username, password)

        if success:
            # Update config
            from app.config import XtreamCredentials, LibrarySettings
            if config is None:
                config = Config()
            config.xtream = XtreamCredentials(base_url=base_url, username=username, password=password)
            config.library.enable_vod = enable_vod
            config.library.movies_include_all = movies_include_all
            config.library.movies_include_categories = movies_include_categories

            save_config(config)

            # Auto-refresh cache on successful config
            try:
                await refresh_vod_cache()
            except Exception as e:
                # Don't fail config save if cache refresh fails
                pass

        return RedirectResponse(url=f"/?{'success' if success else 'error'}", status_code=303)

    except Exception as e:
        # Sanitize error
        error_msg = str(e).replace(username, "USERNAME").replace(password, "PASSWORD")
        return RedirectResponse(url=f"/?error={error_msg}", status_code=303)


@app.post("/refresh", response_class=HTMLResponse)
async def refresh_route():
    """Refresh VOD cache"""
    try:
        await refresh_vod_cache()
        return RedirectResponse(url="/?success=refresh", status_code=303)
    except HTTPException as e:
        return RedirectResponse(url=f"/?error={e.detail}", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/?error=Unexpected error", status_code=303)


@app.get("/healthz")
async def healthz():
    """Health check endpoint"""
    is_configured = config_manager.is_configured() if config_manager else False
    return {
        "status": "ok",
        "sprint": 3,
        "xtream_configured": is_configured,
        "vod_categories": len(cache.vod_categories) if cache else 0,
        "vod_streams": len(cache.vod_streams) if cache else 0
    }


@app.get("/fs/", response_class=HTMLResponse)
@app.get("/fs/{path:path}", response_class=HTMLResponse)
async def get_fs(request: Request, path: str = ""):
    """Handle GET requests for filesystem paths"""
    if tree is None:
        raise HTTPException(status_code=503, detail="Server not ready")

    if not path.startswith("/"):
        path = "/" + path
    node = tree.resolve(path)
    if node is None:
        raise HTTPException(status_code=404, detail="Not found")
    if node.is_directory():
        if not path.endswith("/") and path != "":
            return RedirectResponse(url=f"/fs{path.rstrip('/')}/", status_code=301)
        listing_html = httpfs.get_directory_listing(path, request=request) if httpfs else ""
        return HTMLResponse(content=listing_html)

    # Handle file requests
    if node.type == NodeType.XTREAM_VOD_FILE:
        # Rate limiting check
        client_ip = request.client.host if request.client else "unknown"
        rate_limiter = get_rate_limiter()
        if not rate_limiter.check(client_ip):
            raise HTTPException(status_code=429, detail="Too Many Requests")

        # Stream from Xtream proxy
        upstream_url = node.upstream_url
        if not upstream_url:
            # Build URL from credentials
            if config and config_manager and config_manager.is_configured():
                upstream_url = f"{config.xtream.base_url}/movie/{config.xtream.username}/{config.xtream.password}/{node.stream_id}.{node.container_extension}"
            else:
                raise HTTPException(status_code=503, detail="Xtream credentials not configured")

        # Get Range header
        range_header = request.headers.get("range")

        # Return streaming response
        return await stream_vod_from_node(node, range_header=range_header)

    return httpfs.serve_file(path) if httpfs else Response(status_code=503, content="Server not ready")


@app.head("/fs/")
@app.head("/fs/{path:path}")
def head_fs(request: Request, path: str = ""):
    """Handle HEAD requests - lightweight, no upstream calls"""
    if tree is None:
        raise HTTPException(status_code=503, detail="Server not ready")

    if not path.startswith("/"):
        path = "/" + path
    node = tree.resolve(path)
    if node is None:
        raise HTTPException(status_code=404, detail="Not found")
    if node.is_directory():
        if httpfs:
            httpfs._track_scanner_access(request)
        return httpfs.head_directory(path, has_trailing_slash=path.endswith("/")) if httpfs else Response(status_code=503, content="Server not ready")
    else:
        # For Xtream VOD files, trigger lazy fetch if metadata missing
        if node.type == NodeType.XTREAM_VOD_FILE and node.provider_name and node.stream_id and warmer and metadata_cache:
            if not metadata_cache.has(node.provider_name, node.stream_id):
                # Fire-and-forget lazy fetch - does not block HEAD response
                asyncio.create_task(warmer.request_single(node.provider_name, node.stream_id))

        return httpfs.head_file(path) if httpfs else Response(status_code=503, content="Server not ready")


@app.get("/cdn/{path:path}")
async def get_cdn_redirect(path: str):
    """Redirect to direct CDN/upstream URL for a VOD file.

    Bypasses the local proxy and redirects directly to the upstream Xtream URL.
    Only works when enable_cdn_direct is True in config.
    HEAD requests remain local for metadata without hitting CDN.

    Note: This exposes the upstream URL (including credentials) to the client.
    Use with caution - only enable in trusted networks.
    """
    if tree is None:
        raise HTTPException(status_code=503, detail="Server not ready")

    if not config or not config.httpfs.enable_cdn_direct:
        raise HTTPException(status_code=404, detail="CDN direct mode is disabled")

    if not path.startswith("/"):
        path = "/" + path

    node = tree.resolve(path)
    if node is None:
        raise HTTPException(status_code=404, detail="Not found")
    if not node.is_file() or node.type != NodeType.XTREAM_VOD_FILE:
        raise HTTPException(status_code=400, detail="CDN redirect only available for VOD files")

    if not node.upstream_url:
        raise HTTPException(status_code=503, detail="No upstream URL available")

    logger = __import__('logging').getLogger(__name__)
    logger.info(f"CDN redirect: {node.name} -> {node.upstream_url}")

    return RedirectResponse(
        url=node.upstream_url,
        status_code=302,
        headers={"X-Cdn-Url": node.upstream_url}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)
