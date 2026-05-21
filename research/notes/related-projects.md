# Related Projects Analysis

## emby-xtream (Emby.Xtream.Plugin)
**Repo**: https://github.com/firestaerter3/emby-xtream

**What it is**: An Emby Server plugin that syncs Xtream content as STRM files.

**What we learn from it**:
- ContentNameCleaner: Regex-based title cleaning (box tags `|UK|`, `┃US┃`, country-dash prefixes `EN - `)
- Series episode naming: `Show Name - S01E01 - Episode Title.strm`
- Season folders: `Season 01/` (zero-padded)
- TMDB ID appending: `[tmdbid=603]` for metadata matching
- Smart sync: skips existing files, hashes to detect changes
- Category-based folder organization modes
- Cross-listing deduplication
- Dispatcharr integration for credential-free URLs

**What it does NOT solve**:
- It writes STRM files to disk (we serve virtual filesystem over HTTP)
- It's Emby-specific (we target Plex via rclone)
- No streaming proxy (STRM files contain direct Xtream URLs)
- No HEAD request handling (rclone's concern)

**Key naming patterns to borrow**:
- Box tag removal: `[\u2503\u2502|][^\u2503\u2502|]+[\u2503\u2502|]`
- Country-dash prefix: `^[A-Z]{2}\s+-\s+`
- Episode format: `{show} - S{season:02}E{episode:02} - {title}.{ext}`

---

## Jellyfin-Xtream-Library
**Repo**: https://github.com/firestaerter3/Jellyfin-Xtream-Library

**What it is**: A Jellyfin plugin that syncs Xtream content as STRM files with NFO sidecars.

**What we learn from it**:
- Same author as emby-xtream, similar architecture
- Folder structure: `Movie Name (2023) [tmdbid-12345]/Movie Name (2023) [tmdbid-12345].strm`
- Series: `Show Name (2008) [tvdbid-81189]/Season 01/Show Name - S01E01 - Pilot.strm`
- Incremental sync with checksums
- Rate limiting with automatic retry on 429
- Orphan cleanup with 20% safety threshold
- NFO sidecar generation for instant media info

**What it does NOT solve**:
- Same STRM-file approach, not virtual filesystem
- Jellyfin-specific metadata provider integration
- No HTTP serving layer

---

## iptv-proxy
**Repo**: https://github.com/pierre-emmanuelJ/iptv-proxy

**What it is**: A Go proxy that rewrites Xtream credentials and URLs.

**What we learn from it**:
- Uses `go.xtream-codes` library for API calls
- Proxies all Xtream API actions (login, categories, streams, EPG)
- Rewrites credentials in API responses
- Rewrites stream URLs to point through proxy
- Supports both M3U and Xtream API proxying

**What it does NOT solve**:
- It's a credential proxy, not a virtual filesystem
- No directory listing / file tree abstraction
- No Plex-specific naming
- No caching layer

**Relevant for**: Stream proxy patterns, credential handling

---

## tuliprox
**Repo**: https://github.com/euzu/tuliprox

**What it is**: A high-performance Rust IPTV proxy and playlist processor.

**What we learn from it**:
- Mature architecture: B+Tree storage, async I/O, connection management
- Multiple output formats: M3U, Xtream API, HDHomeRun, STRM
- Reverse proxy mode with shared streams
- Provider failover and DNS rotation
- Bandwidth throttling
- HLS session management

**What it does NOT solve**:
- Much more complex than we need (Rust, B+Tree, multi-user)
- STRM output is file-based, not virtual HTTP
- Over-engineered for our single-user local use case

**Relevant for**: Architecture inspiration for streaming proxy, connection management

---

## go.xtream-codes (tellytv)
**Repo**: https://github.com/tellytv/go.xtream-codes

**What it is**: A Go client library for the Xtream Codes API.

**What we learn from it**:
- Complete API coverage: auth, categories, streams, series info, VOD info, EPG
- Flexible type handling: `FlexInt`, `FlexFloat`, `ConvertibleBoolean` for provider variance
- Stream URL construction: `{base}/{type}/{user}/{pass}/{id}.{ext}`
- Series episodes: `episodes` is a `map[string][]SeriesEpisode` keyed by season number
- VOD info structure: `info` + `movie_data` nested objects

**What it does NOT solve**:
- It's a Go library (we use Python)
- No caching, no HTTP serving
- No naming/cleaning logic

**Relevant for**: API field names, response structure, provider variance handling

---

## WsgiDAV
**Repo**: https://github.com/mar10/wsgidav

**What it is**: A Python WebDAV server.

**What we learn from it**:
- WebDAV as alternative to rclone HTTP backend
- More robust file/directory semantics
- Better support for file size, modification times
- Built-in authentication

**What it does NOT solve**:
- WebDAV is NOT our v1 approach (rclone HTTP is)
- More complex than needed
- Plex support for WebDAV is less tested than rclone

**Relevant for**: Fallback plan if rclone HTTP proves too brittle

---

## Summary of What Each Project Solves

| Project | Solves | Doesn't Solve |
|---------|--------|---------------|
| emby-xtream | Naming conventions, episode format, category handling | Not virtual FS, Emby-specific |
| Jellyfin-Xtream-Library | STRM organization, incremental sync, NFO | Not virtual FS, Jellyfin-specific |
| iptv-proxy | Stream proxying, credential rewriting | No virtual FS, no naming |
| tuliprox | Architecture, streaming, failover | Over-engineered, Rust |
| go.xtream-codes | API field names, response structure | Go library, no FS layer |
| WsgiDAV | WebDAV alternative | Not our v1 approach |
