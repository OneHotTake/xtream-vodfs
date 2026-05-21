# Research Summary

## Reference Projects

### 1. rclone (upstream/rclone)
**Useful for**: Understanding the HTTP backend's directory parsing, HEAD behavior, and VFS cache implications. The source code (`backend/http/http.go`) is the definitive reference for what our HTML output must satisfy.

**Does NOT solve**: Anything about Xtream APIs, naming conventions, or streaming proxies. It's purely the client-side of our HTTP server.

**Key takeaway**: rclone parses ANY HTML with `<a href>` tags. Directories end with `/`, files don't. HEAD requests are sent for every file unless `--http-no-head` is set.

### 2. emby-xtream (upstream/emby-xtream)
**Useful for**: Title cleaning patterns (ContentNameCleaner), episode naming format, season folder structure, category handling, and deduplication strategies.

**Does NOT solve**: Virtual filesystem serving, streaming proxy, or rclone compatibility. It writes STRM files to disk for Emby.

**Key takeaway**: Box tag regex `[\u2503\u2502|][^\u2503\u2502|]+[\u2503\u2502|]`, country-dash prefix `^[A-Z]{2}\s+-\s+`, episode format `{show} - S{season:02}E{episode:02} - {title}.{ext}`.

### 3. Jellyfin-Xtream-Library (upstream/Jellyfin-Xtream-Library)
**Useful for**: STRM organization patterns, incremental sync concepts, NFO sidecar generation, and folder naming with metadata IDs.

**Does NOT solve**: Same as emby-xtream - it's a Jellyfin plugin writing files to disk.

**Key takeaway**: Folder structure `Movie Name (2023) [tmdbid-12345]/` and `Show Name (2008) [tvdbid-81189]/Season 01/` for reliable metadata matching.

### 4. iptv-proxy (upstream/iptv-proxy)
**Useful for**: Stream proxy patterns, credential rewriting, and Xtream API action routing.

**Does NOT solve**: Virtual filesystem, naming, or Plex compatibility. It's a credential proxy.

**Key takeaway**: Simple proxy pattern: receive request, construct upstream URL, forward response. Range header forwarding is critical.

### 5. tuliprox (upstream/tuliprox)
**Useful for**: Architecture inspiration - connection management, streaming, provider failover concepts.

**Does NOT solve**: Our use case is much simpler. Tuliprox is a multi-user enterprise system in Rust.

**Key takeaway**: Streaming proxy with shared connections and bandwidth management. Overkill for our single-user local tool.

### 6. go.xtream-codes (upstream/go.xtream-codes)
**Useful for**: Xtream API field names, response structures, and provider variance handling (FlexInt, ConvertibleBoolean).

**Does NOT solve**: Python implementation, caching, HTTP serving, or naming.

**Key takeaway**: API endpoints are simple: `player_api.php?username=X&password=X&action=get_*`. Response fields vary by provider in type (string vs int).

### 7. WsgiDAV (upstream/wsgidav)
**Useful for**: Fallback reference only. WebDAV provides better file semantics than raw HTTP.

**Does NOT solve**: Our v1 approach is rclone HTTP, not WebDAV.

**Key takeaway**: If rclone HTTP proves too brittle for Plex, WebDAV is a viable alternative with proper PROPFIND/GET semantics.

---

## rclone HTTP Behavior Requirements

1. **Directory listings**: HTML with `<a href>` tags, directories end with `/`, files don't
2. **HEAD for files**: rclone sends HEAD to get Content-Length, verify existence, detect directories
3. **HEAD for directories**: 301 redirect to trailing-slash version if accessed without `/`
4. **GET for files**: Stream the content, support Range headers
5. **Content-Type**: `text/html` for directories, appropriate MIME type for files
6. **No JavaScript/CSS**: rclone only needs `<a href>` tags in valid HTML
7. **URL escaping**: hrefs must be URL-escaped

---

## Xtream API Endpoints Needed

| Endpoint | Purpose | Cache TTL |
|----------|---------|-----------|
| `player_api.php` (no action) | Authentication | Session |
| `action=get_vod_categories` | VOD category list | 12h |
| `action=get_vod_streams` | VOD movie list | 6-24h |
| `action=get_vod_streams&category_id=X` | VOD by category | 6-24h |
| `action=get_vod_info&vod_id=X` | VOD details (optional) | Lazy |
| `action=get_series_categories` | Series category list | 12h |
| `action=get_series` | Series list | 12h |
| `action=get_series&category_id=X` | Series by category | 12h |
| `action=get_series_info&series_id=X` | Episode details (lazy) | 7d |

---

## Plex Scanner Risk Summary

| Risk | Severity | Mitigation |
|------|----------|------------|
| HEAD storm during scan | High | `cached_only` mode, aggressive caching |
| File size mismatch | Medium | Only return known sizes, Accept-Ranges always |
| Slow response times | Medium | Async FastAPI, httpx connection pooling |
| Range request failures | High | Exact Range header forwarding |
| Aggressive periodic rescans | Medium | Document `--dir-cache-time 12h` |

---

## Recommended Naming/Layout Strategy

### Movies
```
/fs/movies/
  All/
    Clean Movie Title (2024).mkv
    Clean Movie Title (2024) [xtream-12345].mkv   # duplicate
  Category Name/
    Clean Movie Title (2024).mkv
```

### Series
```
/fs/series/
  Show Name (2021)/
    Season 01/
      Show Name - S01E01 - Episode Title.mkv
      Show Name - S01E02 - Episode Title.mkv
    Season 02/
      ...
```

### Title Cleaning Rules
1. Remove box tags: `|UK|`, `┃US┃`, `│EN│`
2. Remove country-dash prefixes: `EN - `, `US - ` (2-letter only)
3. Remove user-configurable terms
4. Extract year if present in title
5. Format: `Clean Title (Year).ext`
6. Duplicates: append `[xtream-ID]`

---

## How This Differs from STRM Generators

| Aspect | STRM Generators | xtream-vodfs |
|--------|----------------|--------------|
| Storage | Writes .strm files to disk | No disk writes, virtual HTTP |
| Credentials | Embedded in .strm files | Never exposed in filesystem |
| Updates | Periodic sync required | Real-time via API cache |
| Disk space | Requires disk for .strm files | Zero disk for content |
| Plex setup | Point library at directory | Mount via rclone :http: |
| Streaming | Direct to Xtream URLs | Proxied through our server |
| HEAD handling | Not applicable | Critical for rclone compatibility |

---

## Implementation Risks and Mitigations

See `implementation-risks.md` for detailed risk analysis.

Top 3 risks:
1. **Provider API variance** - Use flexible Pydantic models, defensive parsing
2. **Plex scanner overload** - `cached_only` HEAD mode, aggressive caching, rate limiting
3. **rclone HTTP incompatibility** - Test against rclone from Sprint 1, use proven HTML format
