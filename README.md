# xtream-vodfs - Sprint 3

## Overview

xtream-vodfs is a local HTTP virtual filesystem for Xtream Codes VOD content. It exposes IPTV provider VOD libraries as a browsable, mountable filesystem compatible with rclone's `:http:` backend. Think of it as a **virtual filesystem adapter** — your Xtream providers become directories you can browse, mount with FUSE, and stream from.

### Current Capabilities

- **Multi-Provider Support** — Configure multiple Xtream providers simultaneously; each appears as a separate subdirectory under `/fs/movies/`
- **Real Xtream VOD Integration** — Fetches live categories and streams from Xtream Codes APIs
- **Background Metadata Warming** — Enriches VOD listings with duration, bitrate, and codec info via `get_vod_info` API (bounded concurrency, resumable across restarts)
- **Lazy Metadata Fetching** — HEAD requests on files trigger on-demand metadata fetch when the cache is cold, so files browsed during normal use get warmed automatically
- **Persistent Caches** — VOD listings and metadata survive restarts via JSON cache files
- **Streaming Proxy** — Range-header forwarding for seekable video playback
- **CDN Direct Mode** — Optional bypass of local proxy for direct upstream URLs
- **Scanner Detection** — Detects Plex/Emby/Jellyfin scanners and applies safe delays to prevent aggressive scanning
- **Rate Limiting** — Per-client rate limiting for streaming endpoints
- **rclone Compatibility** — Full support for `lsf`, `lsd`, `tree`, `cat`, and `mount` operations

## Installation

### Requirements

- Python 3.11+
- pip or uv

### Setup

```bash
cd /home/onehottake/Projects/xtream-vodfs

# Install dependencies
python3 -m pip install -e ".[dev]"

# Or with uv (if available)
uv pip install -e ".[dev]"
```

## Running the Server

### Quick Start

The easiest way to run xtream-vodfs is using the provided startup script:

```bash
# Start the server and mount with rclone
./run.sh start

# Check status
./run.sh status

# Stop everything
./run.sh stop

# Restart
./run.sh restart
```

The script will:
- Start the FastAPI server on http://127.0.0.1:8080
- Mount the virtual filesystem to `/tmp/xtream-vodfs-mount` using rclone
- Track PIDs for proper cleanup
- Save logs to `server.log` and `rclone.log`

After starting, you can browse the mount:

```bash
ls -la /tmp/xtream-vodfs-mount/
ls -la /tmp/xtream-vodfs-mount/movies/
```

Alternatively, start the FastAPI server directly:

```bash
cd /home/onehottake/Projects/xtream-vodfs
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

The server will start at `http://127.0.0.1:8080`.

On first run, the server creates a `config/config.json` file. Configure your Xtream providers by editing this file (see [Multi-Provider Configuration](#1-multi-provider-support)) or use the web UI at `http://127.0.0.1:8080/`.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `XTREAM_VODFS_CONFIG_DIR` | `./config` | Override the configuration directory path |

### Configuration Options

The `config/config.json` file supports these sections:

| Section | Description |
|---------|-------------|
| `providers` | List of Xtream provider credentials (multi-provider mode) |
| `xtream` | Legacy single-provider credentials (fallback) |
| `library` | Content filtering: `enable_vod`, `enable_series`, `include_categories`, `exclude_categories`, `movies_include_all`, `movies_include_categories` |
| `httpfs` | HTTP filesystem settings: `enable_cdn_direct`, `enable_scanner_detection`, `cache_content_type`, `dir_listing_cache_ttl` |
| `metadata_warmer` | Background warming settings (see [Metadata Warming](#3-background-metadata-warming)) |

## Testing with curl

### Basic connectivity

```bash
# Health check
curl http://127.0.0.1:8080/healthz

# Status page
curl http://127.0.0.1:8080/

# Filesystem root
curl -I http://127.0.0.1:8080/fs/
curl http://127.0.0.1:8080/fs/
```

### Directory listings

```bash
# List /fs/
curl http://127.0.0.1:8080/fs/

# List movies (multi-provider mode shows provider subdirectories)
curl http://127.0.0.1:8080/fs/movies/

# List movies for a specific provider
curl http://127.0.0.1:8080/fs/movies/real-debrid/

# List All movies for a provider
curl http://127.0.0.1:8080/fs/movies/real-debrid/All/

# List series
curl http://127.0.0.1:8080/fs/series/

# List samples
curl http://127.0.0.1:8080/fs/samples/
```

### File operations

```bash
# HEAD request on file
curl -I "http://127.0.0.1:8080/fs/samples/hello.txt"

# GET file content
curl "http://127.0.0.1:8080/fs/samples/hello.txt"

# HEAD on VOD file (triggers lazy metadata fetch if not cached)
curl -I "http://127.0.0.1:8080/fs/movies/real-debrid/All/Movie%20Name%20(2024).mkv"

# GET with Range header (first 100 bytes) — works via streaming proxy
curl -r 0-99 "http://127.0.0.1:8080/fs/movies/real-debrid/All/Movie%20Name%20(2024).mkv" -o /tmp/range-test.bin

# Verify range response
curl -r 0-99 "http://127.0.0.1:8080/fs/samples/hello.txt" -v -o /tmp/range-test.bin
```

### Trailing slash redirects

```bash
# Without trailing slash (should redirect)
curl -I http://127.0.0.1:8080/fs/movies

# With trailing slash (should work)
curl -I http://127.0.0.1:8080/fs/movies/
```

## Testing with rclone

### Install rclone (if not installed)

```bash
curl https://rclone.org/install.sh | sudo bash
```

### Configure rclone

Create or edit `~/.config/rclone/rclone.conf`:

```ini
[http]
type = http
url = http://127.0.0.1:8080/fs/
```

### List operations

```bash
# List files (lsf)
rclone lsf http:

# List directories (lsd)
rclone lsd http:

# Show tree
rclone tree http:

# List specific directory
rclone lsf http:movies/real-debrid/All/
rclone lsf http:movies/super-iptv/Action/
rclone lsd http:series/
```

### Read file via rclone

```bash
# Read hello.txt
rclone cat http:samples/hello.txt

# Copy file locally
rclone copy http:samples/hello.txt /tmp/
```

### Mount operations

```bash
# Create mount point
mkdir -p /tmp/xtream-vodfs

# Mount the filesystem
rclone mount http: /tmp/xtream-vodfs \
  --vfs-cache-mode full \
  --dir-cache-time 12h \
  --poll-interval 0 \
  --cache-dir /tmp/rclone-xtream-vodfs-cache \
  --log-level INFO
```

The mount command will block and keep the filesystem mounted. Open a new terminal for verification.

### Verification

```bash
# Browse the mount
find /tmp/xtream-vodfs -maxdepth 4 -type f -o -type d

# List directories
ls -lah /tmp/xtream-vodfs/
ls -lah /tmp/xtream-vodfs/movies/
ls -lah /tmp/xtream-vodfs/movies/All/

# Read a file
cat /tmp/xtream-vodfs/samples/hello.txt

# Verify file content (should be "Hello, World!")
cat /tmp/xtream-vodfs/samples/hello.txt

# Check movie files exist
ls -lah /tmp/xtream-vodfs/movies/All/

# Check series structure
ls -lah /tmp/xtream-vodfs/series/Example\ Show\ \(2024\)/Season\ 01/
```

### Unmount

```bash
# Unmount the filesystem
fusermount -u /tmp/xtream-vodfs 2>/dev/null || umount /tmp/xtream-vodfs 2>/dev/null

# Clean up cache
rm -rf /tmp/rclone-xtream-vodfs-cache
```

## Running Tests

Run pytest tests:

```bash
cd /home/onehottake/Projects/xtream-vodfs

# Run all tests
python3 -m pytest tests/ -v

# Run with verbose output
python3 -m pytest tests/ -v

# Run specific test file
python3 -m pytest tests/test_tree.py
python3 -m pytest tests/test_httpfs.py

# Run with coverage
python3 -m pytest --cov=app --cov-report=html
```

## 1. Multi-Provider Support

xtream-vodfs supports multiple Xtream providers simultaneously. Each provider gets its own subdirectory under `/fs/movies/`, keeping libraries organized and avoiding filename collisions.

### Configuration

Add a `providers` list to `config/config.json`. Each entry requires a unique `provider_name`:

```json
{
  "providers": [
    {
      "provider_name": "real-debrid",
      "base_url": "http://real-debrid.com:8080",
      "username": "user1",
      "password": "pass1"
    },
    {
      "provider_name": "super-iptv",
      "base_url": "http://superiptv.com:8080",
      "username": "user2",
      "password": "pass2"
    }
  ]
}
```

### Provider Name Rules

- Must be unique across all providers
- Auto-sanitized to lowercase `[a-z0-9_-]` (special characters replaced with `-`)
- Used as the directory name in the filesystem and as a key prefix in metadata caches

### Filesystem Layout

Multi-provider mode creates this structure:

```
/fs/movies/
├── real-debrid/          ← Provider namespace
│   ├── All/              ← All movies from this provider
│   └── Action/           ← Category folders
├── super-iptv/
│   ├── All/
│   └── Action/
└── another-provider/     ← Add as many as needed
```

### Backward Compatibility

If you omit the `providers` list, the legacy single-provider `xtream` field is used as a fallback:

```json
{
  "xtream": {
    "base_url": "http://example.com:8080",
    "username": "user",
    "password": "pass"
  }
}
```

In single-provider mode, the filesystem stays flat (no provider subdirectory):
```
/fs/movies/All/
/fs/movies/Action/
```

When both `providers` and `xtream` are present, the `providers` list takes precedence.

## 2. Metadata Cache

### What It Does

The metadata cache stores enriched VOD metadata fetched from the `get_vod_info` Xtream API endpoint. This includes details beyond what the basic streams list provides:

- **Duration** — Movie runtime in seconds (`duration_secs`)
- **Bitrate** — Average bitrate in kbps (`bitrate`)
- **Video Info** — Codec, resolution, aspect ratio (opaque dict)
- **Audio Info** — Codec, channels, sample rate (opaque dict)
- **Rating** — User rating from the provider
- **Plot/Synopsis** — Short description
- **Cast & Director** — Credits
- **Release Date** — Original release date
- **TMDB ID** — TheMovieDB reference
- **Backdrop & Poster** — Image URLs
- **YouTube Trailer** — Trailer link

### Cache File

- **Location:** `config/metadata_cache.json`
- **Format:** Versioned JSON with a `fetched_at` timestamp and `entries` map
- **Key Format:** `{provider_name}:{stream_id}` (e.g., `real-debrid:12345`)

Example cache structure:
```json
{
  "version": 1,
  "fetched_at": "2026-05-21T12:00:00",
  "entries": {
    "real-debrid:12345": {
      "name": "Movie Title",
      "duration_secs": 7260,
      "bitrate": 8500,
      "rating": 8.5,
      "video": { "codec": "h264", "width": 1920, "height": 1080 },
      "audio": { "codec": "aac", "channels": 6 },
      "fetched_at": "2026-05-21T12:00:00"
    }
  }
}
```

### Persistence Behavior

- **On Startup:** Cache is loaded from disk automatically. If no cache file exists or the version doesn't match, it starts empty.
- **On New Data:** Each new metadata entry marks the cache as dirty. A debounced save writes to disk after 50 new entries or 10 seconds of inactivity.
- **On Shutdown:** The background warmer saves a final copy when it completes.

### Usage in HEAD Responses

When the metadata cache has data for a VOD file, `HEAD` responses include an estimated `Content-Length` calculated from bitrate × duration. This enables media players and scanners to see approximate file sizes during directory listing and probing.

## 3. Background Metadata Warming

### How It Works

The metadata warmer is a background task that enriches VOD listings by fetching `get_vod_info` for every stream across all providers. It starts automatically after the VOD cache is refreshed and runs asynchronously — it does **not** block server startup or filesystem availability.

### Bounded Concurrency

The warmer uses an `asyncio.Semaphore` to limit the number of concurrent API calls. This prevents overwhelming your Xtream providers:

| Setting | Default | Description |
|---------|---------|-------------|
| `concurrency` | 12 | Maximum concurrent `get_vod_info` requests |
| `delay_seconds` | 0.5 | Pause between scheduling batches |
| `retry_attempts` | 2 | Number of retries per failed fetch |
| `retry_backoff_seconds` | 5.0 | Base backoff multiplier (capped at 10s) |
| `stale_after_days` | 30 | Re-fetch entries older than this |

### Resumability

The warmer only fetches metadata for streams that are **not already cached**. On subsequent runs:

1. Cache is loaded from disk on startup
2. Warmer checks which streams are missing from cache
3. Only fetches metadata for new or expired (older than `stale_after_days`) entries
4. Previously cached metadata is reused immediately

This means a full re-fetch only happens when you add new providers or the cache is cleared.

### Error Handling

- Failed fetches are retried up to `retry_attempts + 1` times with exponential backoff (×2 each attempt, capped at 10 seconds)
- Streams that fail all retries are tracked in a `_failed` set and skipped for the remainder of the run
- A warning is logged for each stream that exhausts its retries

### Configuration

Add a `metadata_warmer` section to `config/config.json`:

```json
{
  "metadata_warmer": {
    "enabled": true,
    "concurrency": 12,
    "delay_seconds": 0.5,
    "retry_attempts": 2,
    "retry_backoff_seconds": 5.0,
    "stale_after_days": 30
  }
}
```

To disable background warming entirely, set `"enabled": false`.

### Progress Tracking

The warmer exposes a `warming_progress()` method that returns:

```json
{
  "total": 150,
  "fetched": 87,
  "failed": 2,
  "pending": 5,
  "elapsed_seconds": 45.2,
  "percent_complete": 58.0,
  "is_warming": true
}
```

This can be used for monitoring and dashboards.

## 4. Lazy Fetching

### What It Is

Lazy fetching is a complementary mechanism to the background warmer. When a `HEAD` request arrives for a VOD file whose metadata isn't cached, the server kicks off a **fire-and-forget** metadata fetch for that specific stream — without blocking the response.

### How It Works

1. A `HEAD` request arrives at `/fs/movies/real-debrid/All/Movie%20Name%20(2024).mkv`
2. The server resolves the file node, checks the metadata cache
3. If metadata is **missing**, it schedules a background fetch via `warmer.request_single()`
4. The `HEAD` response returns immediately with estimated `Content-Length` (using synthetic 1MB default)
5. The background fetch populates the cache for future HEAD/GET requests

### Coordination with Background Warmer

Lazy fetching shares the same internal `_pending` set as the background warmer. This prevents:

- **Duplicate requests** — If both the warmer and a lazy fetch target the same stream, only one API call is made
- **Redundant work** — If the warmer already fetched or failed a stream, lazy fetch skips it

### Benefits

- **Early warming** — Files you browse or probe during normal use get their metadata warmed ahead of the background cycle
- **Non-blocking** — Directory listings and HEAD responses remain fast, with no upstream API delays
- **Transparent** — Works automatically; no user configuration needed

## 5. First Run vs Subsequent Runs

### First Run

On the very first start with no cached data:

1. Server starts immediately — `/fs/` is available and responsive
2. VOD categories and streams are fetched from all configured providers
3. The virtual filesystem tree is built and served
4. The background metadata warmer starts, fetching `get_vod_info` for every stream with bounded concurrency
5. Filesystem is fully browsable during warming — you can list directories, HEAD files, and stream content right away
6. Metadata populates progressively as the warmer completes

### Subsequent Runs

On subsequent starts with existing caches:

1. VOD cache (`config/cache.json`) is loaded from disk — no API calls needed
2. Metadata cache (`config/metadata_cache.json`) is loaded from disk
3. The warmer compares cached entries against the current stream list
4. Only new or stale (older than `stale_after_days`) streams are fetched
5. Previously enriched metadata is available immediately for all cached entries
6. `HEAD` responses include accurate `Content-Length` from cached metadata

### Cache Files

| File | Contents | Created On |
|------|----------|------------|
| `config/cache.json` | VOD categories and stream listings | First refresh |
| `config/metadata_cache.json` | Enriched VOD metadata (duration, bitrate, codecs) | First warming |

### Clearing the Cache

To force a full re-fetch, delete the cache files:

```bash
rm -f config/cache.json config/metadata_cache.json
```

Then restart the server or trigger a refresh via the web UI.

### Duplicate Movie Versions

Since cache keys use `{provider_name}:{stream_id}`, the same movie from different providers or with different stream IDs is stored as separate cache entries. This ensures:

- No metadata collision between providers
- Each stream version is independently enriched
- Filesystem deduplication uses `[xtream-{id}]` suffixes within a provider directory

## Virtual Filesystem Structure

The filesystem is dynamically built from configured Xtream providers. With multiple providers, the structure looks like this:

```
/fs/
├── movies/
│   ├── real-debrid/
│   │   ├── All/
│   │   │   ├── Movie A (2024).mkv
│   │   │   └── Movie B (2023).mkv
│   │   └── Action/
│   │       └── Movie A (2024).mkv
│   └── super-iptv/
│       ├── All/
│       │   └── Movie A (2024).mkv    ← Same movie, different provider
│       └── Action/
│           └── Movie A (2024).mkv
├── series/
│   └── COMING_SOON.txt               ← Series support planned for Sprint 4
└── samples/
    └── hello.txt                     ← Config-free sample file
```

### Structure Rules

- Each provider gets its own top-level directory under `/fs/movies/`
- Each provider contains an `All/` directory with every movie from that provider
- Each provider has category directories (e.g., `Action/`, `Comedy/`)
- Movie filenames are cleaned: IPTV tags removed, year extracted, duplicates get `[xtream-{id}]` suffix
- Series placeholder exists; full series support is planned
- `/fs/samples/` works without any configuration for quick testing

## Known Limitations

Current limitations:

- **Series not implemented** — Only VOD movies are supported; series support is planned for Sprint 4
- **No authentication** — No access control on the filesystem endpoints
- **Approximate file sizes** — Without real-size data from Xtream APIs, `Content-Length` is estimated from metadata or synthetic
- **No Web UI for multi-provider** — Multi-provider configuration is managed via config file only (the web UI configures single-provider mode)
- **Single server** — Not configured for production deployment (no process manager, no TLS)

## HTTP API Reference

### GET `/`

Returns a status and configuration page showing connection state, VOD statistics, and links to the filesystem.

### GET `/healthz`

Returns JSON health status:
```json
{
  "status": "ok",
  "sprint": 3,
  "xtream_configured": true,
  "vod_categories": 25,
  "vod_streams": 1847
}
```

### GET `/fs/` and `GET /fs/{path:path}`

- If path is a directory: Returns Apache/nginx-style HTML listing
- If path is a VOD file: Streams content from upstream Xtream server (supports Range headers)
- If path is a sample file: Returns local file from `sample_media/`
- If directory exists without trailing slash: Returns 301 redirect
- If path not found: Returns 404
- If rate limited: Returns 429 Too Many Requests

### HEAD `/fs/` and `HEAD /fs/{path:path}`

- If path is a directory: Returns 200 with `Content-Type: text/html`
- If path is a VOD file: Returns 200 with `Accept-Ranges: bytes`, `Content-Type`, `Content-Length` (estimated from cached metadata or synthetic), `Last-Modified`. Triggers lazy metadata fetch if cache is cold.
- If directory exists without trailing slash: Returns 301 redirect
- If path not found: Returns 404

### GET `/cdn/{path:path}`

Redirects directly to the upstream Xtream CDN URL (bypasses the local streaming proxy). Must be enabled via `httpfs.enable_cdn_direct: true` in config. Only available for VOD files.

### POST `/config`

Accepts form data to configure Xtream credentials and library settings. Validates credentials before saving. Triggers automatic VOD cache refresh on success.

### POST `/refresh`

Triggers a full VOD cache refresh for all configured providers. Returns a redirect to the status page.

## Next Steps

Planned future enhancements:

- Series support (full season/episode browsing)
- Configurable filesystem path templates (custom naming, custom layouts)
- Expiration and TTL for cached metadata (auto-refresh stale entries)
- Web UI for multi-provider configuration
- Prometheus metrics for warming progress and cache hit rates
- Per-provider rate limiting and connection pooling

## Troubleshooting

### Server won't start

Check if port 8080 is already in use:
```bash
lsof -i :8080
```

Use a different port if needed:
```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8081
```

### rclone mount fails

- Ensure the server is running
- Check rclone version (requires v1.53+)
- Verify the URL is accessible: `curl http://127.0.0.1:8080/healthz`
- Check rclone logs with `--log-level DEBUG`
- Ensure FUSE is installed: `lsmod | grep fuse`

### Tests fail

- Ensure all dependencies are installed: `python3 -m pip install -e ".[dev]"`
- Run from the project root directory
- Check Python version: `python --version` (must be 3.11+)

### Files appear empty in mount

Sample files (`hello.txt`) have content. Xtream VOD files are streamed live from your providers — they'll appear with synthetic sizes until the metadata warmer populates the cache with real bitrate/duration data. After warming completes, HEAD responses show estimated sizes and GET requests stream content from the upstream server.

## Development

### Project Structure

```
├── app/
│   ├── __init__.py       # Package init
│   ├── main.py           # FastAPI app with routes
│   ├── models.py         # Pydantic models (credentials, streams, metadata)
│   ├── config.py         # Config management (multi-provider, warmer settings)
│   ├── xtream.py         # Xtream API client
│   ├── cache.py          # VOD category/stream cache (JSON persistence)
│   ├── metadata_cache.py # Enriched VOD metadata cache (JSON persistence)
│   ├── tree.py           # Virtual filesystem tree builder
│   ├── httpfs.py         # HTTP filesystem handlers (HEAD, listings, lazy fetch)
│   ├── proxy.py          # Streaming proxy with Rate limiting
│   ├── warmer.py         # Background metadata warmer (bounded concurrency)
│   ├── naming.py         # Title cleaning, year extraction, duplicate handling
│   └── templates/
│       └── listing.html  # Directory listing template
├── code/
│   └── config/           # Provider credentials and settings (legacy path)
├── tests/
│   ├── __init__.py       # Test package init
│   ├── test_tree.py      # Tree structure tests
│   └── test_httpfs.py    # HTTP handler tests
├── sample_media/
│   └── hello.txt         # Sample file for config-free testing
├── pyproject.toml        # Project dependencies
├── IMPLEMENTATION_PLAN.md  # Sprint plan
└── README.md             # This file
```

### Adding new sample files

Place files in `sample_media/` and update `app/httpfs.py` to serve them from `_get_local_file_path()`. Sample files are served alongside Xtream VOD content under `/fs/samples/`.

### Modifying the virtual tree

The virtual tree is built dynamically from cached Xtream data in `app/tree.py`. To modify how the filesystem is structured:
- **Provider layout** — Edit `VirtualTree._build_vod_tree()` and `_build_provider_subtree()` in `app/tree.py`
- **Naming/filename cleaning** — Edit `app/naming.py` to adjust IPTV tag removal, year extraction, or duplicate handling
- **Category filtering** — Adjust `library.include_categories` / `library.exclude_categories` in `config/config.json`

## Completion Status

All implementation phases (1–6) are complete.

### Sprint 1 — Foundation (Completed May 21, 2026)

- ✅ rclone `lsf` / `lsd` / `tree` / `cat` / `mount` compatibility
- ✅ HEAD with Accept-Ranges, directory trailing-slash redirects
- ✅ Apache/nginx-style HTML listings parseable by rclone
- ✅ URL escaping for special characters

### Sprint 2 — Xtream VOD Integration (Completed)

- ✅ Xtream API client (`get_vod_categories`, `get_vod_streams`)
- ✅ VOD cache with JSON persistence
- ✅ Virtual filesystem tree from real API data
- ✅ Category-based directory views
- ✅ Credential configuration and validation
- ✅ Streaming proxy with Range header forwarding

### Sprint 3 — Multi-Provider & Metadata (Completed)

- ✅ Multi-provider support with per-provider namespaces
- ✅ Background metadata warming with bounded concurrency
- ✅ Metadata cache (`get_vod_info` enrichment) with persistent storage
- ✅ Lazy fetching triggered on HEAD requests
- ✅ Resumability across restarts (only fetches missing metadata)
- ✅ Error handling and retry logic for metadata fetches
- ✅ CDN direct URL mode (opt-in)
- ✅ Scanner detection (Plex/Emby/Jellyfin)
- ✅ Content-Type caching
- ✅ Directory listing cache with TTL
- ✅ Rate limiting for streaming proxy
