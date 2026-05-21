# Research Notes: emby-xtream and netv

## emby-xtream Analysis
**Repository:** https://github.com/firestaerter3/emby-xtream
**Approach:** Emby Server plugin (DLL)

### Key Architecture Decisions

1. **STRM Files, Not HTTP Filesystem**
   - Emby-xtream generates `.strm` files (one per movie/episode)
   - Each STRM contains direct Xtream stream URL
   - Emby treats STRM as native library and handles metadata/artwork
   - **Our approach is different** - we're building HTTP filesystem for rclone

2. **Direct URLs, No Proxying by Default**
   - Stream URLs are constructed directly: `{base_url}/movie/{username}/{password}/{stream_id}.{ext}`
   - No intermediate proxy for VOD (except Live TV via Dispatcharr)
   - **This validates our CDN URL exposure design** - direct URLs are standard

3. **Simple Caching Strategy**
   - M3U cache: 15 minutes
   - EPG cache: 30 minutes
   - No complex per-file metadata caching
   - **Our directory listing cache (60s TTL) follows this pattern**

4. **Folder Organization Modes**
   - Single folder: All movies in `Movies/`
   - Multiple folders: One folder per category
   - Custom mapping: User-defined folders with category assignments
   - **We could consider adding folder organization modes if needed**

5. **Metadata Matching**
   - TMDB/TVDb ID folder naming: `Show Name [tvdbid=81189]`
   - Fallback lookup to Emby's metadata providers
   - **We use synthetic timestamps instead - simpler for HTTP filesystem**

### What They Don't Do
- ❌ Complex HEAD modes (cached_only, upstream_probe, etc.)
- ❌ Per-file metadata cache (size, content-type, last-modified)
- ❌ Streaming proxy for VOD (only Live TV via Dispatcharr)
- ❌ Range forwarding - they let Plex/Emby handle streaming directly

### Security Note from emby-xtream
> Xtream Codes protocol requires username/password in every stream URL
> Credentials appear in STRM files and M3U playlists in plaintext
> Dispatcharr provides credential-free proxy URLs as solution

**This validates our credential sanitization approach.**

---

## netv Analysis
**Repository:** https://github.com/jvdillon/netv
**Approach:** Self-hosted web interface for IPTV streams

### Key Architecture Decisions

1. **Minimal, Player-Only Design**
   - "Intentionally minimal" - does one thing: play IPTV streams
   - Not a media server or library manager
   - **Validates our principle: keep it simple**

2. **Direct Streaming with Transcoding Pipeline**
   - Smart passthrough: h264+aac remux without re-encoding (zero CPU)
   - Full GPU pipeline: NVDEC → NVENC/VAAPI (CPU stays idle)
   - Probe caching: Streams probed once, episodes share probe data
   - **Much more complex than our approach** - we're not transcoding

3. **HTTP Passthrough for HTTPS**
   - Auto-proxies HTTP streams when behind HTTPS
   - **Similar to our HTTP filesystem serving content**

4. **Session Recovery**
   - VOD sessions survive restarts
   - Resume playback functionality
   - **Nice feature, but out of scope for our HTTP filesystem approach**

### What netv Does (That We Don't Need)
- ❌ Live rewind buffer
- ❌ AI upscaling (real-time 4x via TensorRT)
- ❌ Smart seeking with segment reuse
- ❌ User management and roles
- ❌ Full web UI with EPG grid

---

## Lessons Learned

### 1. Complexity Anti-Pattern
- emby-xtream: **Simple** (STRM files, direct URLs)
- netv: **Complex** (transcoding pipeline, GPU acceleration)
- **Our simplification was correct** - we removed head_mode complexity

### 2. HTTP Filesystem vs Plugin/Player
- **emby-xtream (plugin):** Uses STRM files → Emby handles streaming
- **netv (player):** Has transcoding pipeline → Direct streaming to client
- **xtream-vodfs (HTTP filesystem):** Serves Apache-style listings → rclone mounts

Our approach is fundamentally different and simpler than netv's player.

### 3. Caching Strategy Validation
Both emby-xtream and netv use simple, time-based caching:
- emby-xtream: 15min M3U, 30min EPG
- netv: Probe cache (share across episodes)
- **Our 60s directory listing cache is in line with this philosophy**

### 4. Direct URLs vs Proxying
- emby-xtream: Direct URLs (except Live TV via Dispatcharr)
- netv: Direct streaming with optional transcoding
- **Our enable_cdn_direct option is appropriate** - direct URLs are standard

### 5. Metadata Handling
- emby-xtream: TMDB/TVDb IDs in folder names
- netv: Probe caching for stream info
- **Our synthetic size + timestamp is sufficient** for rclone/Plex

---

## Design Validation

Our current simplification approach aligns with industry practice:

| Feature | emby-xtream | netv | xtream-vodfs (simplified) | Status |
|---------|-------------|------|---------------------------|--------|
| HTTP filesystem | ❌ STRM files | ❌ Player | ✅ Apache-style listings | ✅ Unique to us |
| Proxy for VOD | ❌ Direct URLs | ❌ Direct stream | ✅ Optional CDN direct | ✅ Appropriate |
| Per-file metadata cache | ❌ None | ✅ Probe cache | ❌ Removed (synthetic) | ✅ Simplified |
| HEAD modes | ❌ None | ❌ None | ❌ Removed | ✅ Correct simplification |
| Caching strategy | ✅ Simple time-based | ✅ Probe cache | ✅ 60s TTL listing | ✅ Aligned |
| Credential sanitization | ⚠️ Dispatcharr only | ✅ N/A | ✅ All logs/errs | ✅ Needed |

---

## Recommendations

### ✅ Keep Current Simplified Approach
1. Synthetic size (1MB) for HEAD responses
2. Directory listing cache (60s TTL)
3. Rate limiting
4. Scanner detection
5. Credential sanitization

### 🤔 Consider for Future
1. **Folder organization modes** (from emby-xtream):
   - Single folder (current `All/`)
   - Per-category folders
   - Custom mapping
2. **Dispatcharr-style credential-free URLs** (if security requirement grows)

### ❌ Do NOT Add
1. Transcoding pipeline (too complex, out of scope)
2. Complex per-file metadata caching (unnecessary for HTTP filesystem)
3. HEAD modes (we removed them, don't add back)
4. Live rewind/buffer (player feature, not filesystem)

---

## Conclusion

The research validates our simplification direction:
- **Simple > Complex**: Both emby-xtream and netv prioritize simplicity
- **Direct URLs > Proxying**: Industry standard is direct streaming
- **Time-based Caching > Per-file Caching**: Simpler and sufficient
- **HTTP Filesystem is Unique**: No direct equivalent - we're filling a gap

Our simplified Sprint 3 is on the right track. The system is now:
- ✅ Simple and predictable
- ✅ rclone-compatible
- ✅ No Content-Length: 0 bugs
- ✅ No unnecessary complexity

**Ready to proceed to Sprint 4 (Series) or production testing.**