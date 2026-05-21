# Implementation Plan: xtream-vodfs

## Overview

5-sprint plan to build a local-first HTTP virtual filesystem that exposes Xtream Codes VOD and Series as a read-only directory tree compatible with rclone's `:http:` backend for Plex mounting.

---

## SPRINT 1 — rclone-compatible HTTP filesystem skeleton

### Goal
Prove rclone can mount our local HTTP virtual filesystem before integrating Xtream.

### Scope
- FastAPI app skeleton (`app/main.py`)
- Configuration model (`app/config.py`)
- Hardcoded virtual tree with sample data
- Apache/nginx-style directory listing HTML template
- GET directory → HTML listing
- HEAD file → 200 with Accept-Ranges: bytes
- HEAD directory → 200 or 301 if missing trailing slash
- GET file → serve from a local sample file or test upstream URL
- Virtual tree abstraction (`app/tree.py`)
- HTTP filesystem layer (`app/httpfs.py`)
- Basic tests (`tests/test_tree.py`, `tests/test_httpfs.py`)

### Deliverables
- `code/app/main.py` — FastAPI app with `/fs/` routes
- `code/app/config.py` — Pydantic config model
- `code/app/tree.py` — Virtual filesystem tree abstraction
- `code/app/httpfs.py` — HTTP filesystem handlers (GET/HEAD directory/file)
- `code/app/templates/listing.html` — Jinja2 directory listing template
- `code/tests/test_tree.py` — Tree structure tests
- `code/tests/test_httpfs.py` — HTTP handler tests
- `code/pyproject.toml` — Project dependencies

### Acceptance Tests
- `rclone lsf :http,url='http://127.0.0.1:8080/fs/':` lists files
- `rclone lsd :http,url='http://127.0.0.1:8080/fs/':` lists directories
- `rclone tree :http,url='http://127.0.0.1:8080/fs/':` shows tree
- `rclone mount` works, files appear under mount point
- `cat` or `vlc` can read a sample file through the mount
- HEAD on file returns 200 with Accept-Ranges: bytes
- HEAD on directory returns 200
- Directory without trailing slash returns 301
- File not found returns 404
- Directory not found returns 404
- No Xtream code yet

### Manual Test Commands
```bash
# Start server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080

# Test rclone listing
rclone lsf :http,url='http://127.0.0.1:8080/fs/':
rclone lsd :http,url='http://127.0.0.1:8080/fs/':
rclone tree :http,url='http://127.0.0.1:8080/fs/':

# Test mount
mkdir -p /tmp/xtream-vodfs-test
rclone mount :http,url='http://127.0.0.1:8080/fs/': /tmp/xtream-vodfs-test \
  --vfs-cache-mode full --dir-cache-time 12h --poll-interval 0 &

# Verify files appear
ls -la /tmp/xtream-vodfs-test/

# Read a sample file
cat /tmp/xtream-vodfs-test/movies/All/sample.txt

# Cleanup
fusermount -u /tmp/xtream-vodfs-test 2>/dev/null || umount /tmp/xtream-vodfs-test 2>/dev/null
```

### Risks
- rclone may not parse our HTML format correctly
- HEAD behavior may not match rclone expectations
- URL escaping issues with special characters in filenames

### Definition of Done
- All acceptance tests pass
- rclone mount stable for 5+ minutes
- Sample file readable through mount
- Tests pass with `pytest`
- No Xtream-specific code in the codebase

---

## SPRINT 2 — Xtream VOD integration

### Goal
Make real Xtream VOD movies appear as virtual files and stream through the proxy.

### Scope
- Xtream API client (`app/xtream.py`)
- Credential storage (encrypted config or env vars)
- `get_vod_categories` implementation
- `get_vod_streams` implementation (with optional category_id)
- VOD tree builder (All + per-category views)
- Movies/All and Movies/Category directory views
- Stream proxy with Range header forwarding (`app/proxy.py`)
- `cached_only` HEAD mode (default)
- httpx async client for upstream requests
- Connection pooling
- Basic error handling (401, 403, 404, 5xx)

### Deliverables
- `code/app/xtream.py` — Xtream API client
- `code/app/proxy.py` — Streaming proxy handler
- `code/app/models.py` — Pydantic models for Xtream responses
- Updated `code/app/tree.py` — VOD tree builder
- Updated `code/app/config.py` — Xtream credential config
- `code/.env.example` — Environment variable template
- `code/tests/test_naming.py` — (start) Title cleaning tests

### Acceptance Tests
- User can enter Xtream credentials via config
- VOD categories load from provider
- Movies appear under `/fs/movies/All/` and `/fs/movies/Category Name/`
- `rclone lsf` sees movie files with correct extensions
- A mounted file can be opened in VLC
- Range headers are forwarded to upstream
- Credentials are not logged
- 401/403 from upstream handled gracefully
- HEAD on movie files returns 200 with Accept-Ranges: bytes (cached_only)

### Manual Test Commands
```bash
# Configure credentials
cp .env.example .env
# Edit .env with real credentials

# Start server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080

# Test VOD listing
rclone lsf :http,url='http://127.0.0.1:8080/fs/movies/':
rclone lsf :http,url='http://127.0.0.1:8080/fs/movies/All/':

# Test mount and playback
mkdir -p /tmp/xtream-movies
rclone mount :http,url='http://127.0.0.1:8080/fs/movies/': /tmp/xtream-movies \
  --vfs-cache-mode full --dir-cache-time 12h --poll-interval 0 &

# Open a movie in VLC
vlc /tmp/xtream-movies/All/Movie\ Name\ \(2024\).mkv

# Test Range header
curl -H "Range: bytes=0-1023" http://127.0.0.1:8080/fs/movies/All/Movie\ Name\ \(2024\).mkv -o /dev/null -v

# Cleanup
fusermount -u /tmp/xtream-movies 2>/dev/null || umount /tmp/xtream-movies 2>/dev/null
```

### Risks
- Provider API variance (string vs int IDs, missing fields)
- Stream URL format differences between providers
- Large VOD libraries causing slow initial load
- Provider rate limiting

### Definition of Done
- VOD movies browseable through rclone mount
- At least one movie playable in VLC through proxy
- Range requests forwarded correctly (206 Partial Content works)
- No credentials in logs or error output
- All tests pass

---

## SPRINT 3 — Plex-safe behavior, naming, caching

### Goal
Make scanning a non-trivial VOD library safe and Plex-friendly.

### Scope
- Title cleaner (`app/naming.py`)
  - Box tag removal: `|UK|`, `┃US┃`, `│EN│`
  - Country-dash prefix removal: `EN - `, `US - `
  - Year extraction from titles
  - User-configurable remove terms
- Duplicate handling (first wins, append `[xtream-ID]`)
- Persistent JSON cache under `/config`
- TTL-based caching:
  - VOD categories: 12h
  - VOD streams: 6-24h
  - HEAD metadata: 24h
- Manual refresh endpoint (`POST /api/refresh`)
- Rate limiting for upstream requests
- Exponential backoff on 429/5xx
- `head_mode` configuration:
  - `cached_only` (default)
  - `upstream_probe`
  - `synthetic_size`
- Global concurrency limit
- Plex-safe mode documentation

### Deliverables
- `code/app/naming.py` — Title cleaning and duplicate handling
- `code/app/cache.py` — In-memory + JSON persistent cache
- Updated `code/app/config.py` — head_mode, TTLs, rate limits
- Updated `code/app/xtream.py` — Cached API calls with backoff
- Updated `code/app/httpfs.py` — head_mode support
- `code/tests/test_naming.py` — Comprehensive naming tests
- `code/tests/test_cache.py` — Cache TTL and persistence tests

### Acceptance Tests
- 100+ movie tree builds quickly from cache (sub-second listing)
- Duplicate names do not collide (`[xtream-ID]` suffix)
- Plex-friendly names generated from messy provider titles
- Repeated `rclone lsf` calls do not hammer upstream (cached)
- `cached_only` HEAD mode avoids upstream calls entirely
- `upstream_probe` mode caches HEAD results
- `synthetic_size` mode returns configured size
- Cache persists across restarts (JSON file)
- Refresh endpoint invalidates cache
- Rate limiting prevents upstream overload
- Backoff on 429/5xx responses

### Manual Test Commands
```bash
# Test naming
python -c "from app.naming import clean_title; print(clean_title('|US| The Matrix [FHD]'))"

# Test cache behavior
# 1. Start server, list movies (populates cache)
# 2. Stop server, restart
# 3. List movies again (should use cache, no upstream calls)

# Test refresh
curl -X POST http://127.0.0.1:8080/api/refresh

# Test head_mode
# Set head_mode=cached_only in config
curl -I http://127.0.0.1:8080/fs/movies/All/Movie.mkv

# Test rate limiting
# Rapidly request listings, verify no upstream overload
for i in {1..20}; do curl -s http://127.0.0.1:8080/fs/movies/ > /dev/null; done
```

### Risks
- Title cleaning may be too aggressive or not aggressive enough
- Cache invalidation timing affects content freshness
- Rate limiting may be too strict for some providers
- JSON cache file corruption on crash

### Definition of Done
- All naming tests pass with diverse provider title samples
- Cache hits > 90% on repeated listings
- No upstream calls during `cached_only` HEAD
- Plex library scan completes without provider errors
- All tests pass

---

## SPRINT 4 — Lazy Series support

### Goal
Expose TV series without hammering the provider.

### Scope
- `get_series_categories` implementation
- `get_series` implementation (with optional category_id)
- Lazy `get_series_info` — only fetch when browsing a specific show
- Series virtual tree: `Show Name (Year)/Season XX/Episode`
- Cache series info per show with 7-day TTL
- Episode path resolution from `get_series_info` response
- Tests for episode path resolution
- Series/All view (all shows flat)
- Series/Category view

### Deliverables
- Updated `code/app/xtream.py` — Series API methods
- Updated `code/app/tree.py` — Series tree builder with lazy loading
- Updated `code/app/models.py` — Series/Episode models
- Updated `code/app/cache.py` — Per-show cache with 7d TTL
- `code/tests/test_tree.py` — Series tree tests (lazy loading)

### Acceptance Tests
- `/fs/series/` lists shows without fetching episode details
- Entering one show directory fetches only that show's details
- Episodes appear as `Season XX/Show Name - SXXEXX - Title.ext` files
- `rclone lsf` can list series directories and files
- `rclone mount` can mount and read series files
- No startup storm of `get_series_info` calls
- Series cache persists across restarts
- Lazy loading verified (only fetched shows are cached)

### Manual Test Commands
```bash
# Start server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080

# Test series listing (should NOT fetch series_info)
rclone lsf :http,url='http://127.0.0.1:8080/fs/series/':

# Enter a specific show (SHOULD fetch series_info for that show only)
rclone lsf :http,url='http://127.0.0.1:8080/fs/series/Show\ Name\ \(2021\)/':

# Check cache (only the browsed show should be cached)
cat /config/series_cache.json

# Test mount
mkdir -p /tmp/xtream-series
rclone mount :http,url='http://127.0.0.1:8080/fs/series/': /tmp/xtream-series \
  --vfs-cache-mode full --dir-cache-time 12h --poll-interval 0 &

# Browse to an episode
ls /tmp/xtream-series/Show\ Name\ \(2021\)/Season\ 01/

# Cleanup
fusermount -u /tmp/xtream-series 2>/dev/null || umount /tmp/xtream-series 2>/dev/null
```

### Risks
- `get_series_info` response format varies by provider
- Episode IDs may be strings or integers
- Season 0 (specials) handling
- Large series with many seasons/episodes
- `series_id` vs `series` parameter name variance

### Definition of Done
- Series browseable without fetching all episode details
- Lazy loading verified (only browsed shows trigger API calls)
- Episode files correctly named and playable
- No startup API storm
- All tests pass

---

## SPRINT 5 — Docker, docs, hardening, end-to-end Plex workflow

### Goal
Make this usable as a local appliance.

### Scope
- Dockerfile (multi-stage, slim Python image)
- docker-compose.yml
- `/config` volume for persistent configuration
- `.env.example` with all options documented
- Healthcheck endpoint (`/health`)
- Optional UI password for web interface
- Optional Basic Auth for `/fs/` endpoint
- Security hardening:
  - Bind 127.0.0.1 by default
  - No credentials in logs
  - No credentials in HTML output
  - No credentials in exception text
- README.md with:
  - Quick start guide
  - Configuration reference
  - rclone mount commands
  - Plex library setup instructions
  - Troubleshooting guide
- Final end-to-end tests
- Performance tuning

### Deliverables
- `code/Dockerfile`
- `code/docker-compose.yml`
- `code/.env.example`
- `code/README.md`
- `code/app/security.py` — Auth middleware
- `code/app/main.py` — Healthcheck endpoint, auth integration
- Updated `code/app/config.py` — Auth config, bind address
- `code/app/templates/config.html` — Config UI (if implemented)

### Acceptance Tests
- `docker compose up` starts successfully
- Configuration persists across container restarts
- rclone mount commands documented and tested
- Plex Movies library setup documented and tested
- Plex TV library setup documented and tested
- Security defaults are local/private (127.0.0.1)
- No credentials in logs under any circumstance
- All tests pass
- Healthcheck returns 200

### Manual Test Commands
```bash
# Docker setup
cd code
cp .env.example .env
# Edit .env with real credentials
docker compose up -d

# Verify healthcheck
curl http://127.0.0.1:8080/health

# Test rclone mount
mkdir -p /tmp/xtream-vodfs
rclone mount :http,url='http://127.0.0.1:8080/fs/': /tmp/xtream-vodfs \
  --vfs-cache-mode full \
  --dir-cache-time 12h \
  --poll-interval 0 \
  --cache-dir /tmp/rclone-xtream-vodfs-cache \
  --log-level INFO &

# Verify full tree
rclone tree :http,url='http://127.0.0.1:8080/fs/':

# Test Plex setup (manual)
# 1. Add Movies library in Plex pointing to /tmp/xtream-vodfs/movies
# 2. Add TV library in Plex pointing to /tmp/xtream-vodfs/series
# 3. Scan libraries
# 4. Verify movies and shows appear with metadata

# Test auth (if enabled)
curl -u user:pass http://127.0.0.1:8080/fs/

# Cleanup
fusermount -u /tmp/xtream-vodfs 2>/dev/null || umount /tmp/xtream-vodfs 2>/dev/null
docker compose down
```

### Risks
- Docker networking issues (port conflicts, DNS)
- Plex library scanning may take time with large libraries
- Auth middleware may interfere with rclone
- Documentation may be incomplete for edge cases

### Definition of Done
- Clean Docker setup works from scratch
- Full end-to-end test: Xtream → xtream-vodfs → rclone mount → Plex scan → playback
- README covers all setup scenarios
- Security audit: no credential leaks
- All tests pass
- Project is usable by someone following the README alone

---

## Sprint Summary

| Sprint | Focus | Key Deliverable |
|--------|-------|-----------------|
| 1 | rclone HTTP skeleton | Virtual FS with rclone compatibility |
| 2 | VOD integration | Real Xtream movies streaming |
| 3 | Plex-safe caching | Naming, caching, rate limiting |
| 4 | Lazy Series | Series without API storm |
| 5 | Docker + docs | Production-ready appliance |
