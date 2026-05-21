# Plex + rclone Behavior Notes

## How Plex Scans Libraries

When Plex scans a library mounted via rclone:

1. **Directory enumeration**: Plex walks the directory tree recursively
2. **File identification**: Plex identifies media files by extension (.mkv, .mp4, .avi, etc.)
3. **Metadata matching**: Plex matches filenames against TMDB/TVDB using its scanner agents
4. **Media analysis**: For each file, Plex may:
   - Read file size
   - Read file metadata (via ffprobe/mediainfo)
   - Sample the beginning of the file for codec info

## Plex Naming Requirements

### Movies
Plex expects:
```
Movies/
  Movie Name (Year).ext
  Movie Name (Year).ext        # duplicate handling
  Movie Name (Year) [unique].ext
```

- Year in parentheses is critical for accurate matching
- Clean titles without provider tags improve match rate
- Folder-per-movie mode: `Movie Name (Year)/Movie Name (Year).ext`

### TV Series
Plex expects:
```
Series/
  Show Name (Year)/
    Season 01/
      Show Name - S01E01 - Episode Title.ext
      Show Name - S01E02 - Episode Title.ext
    Season 02/
      ...
```

- Show name with year for disambiguation
- Season folders named `Season XX` (zero-padded)
- Episode files: `Show - SXXEXX - Title.ext`
- Season 00 for specials

## rclone VFS + Plex Interaction

When Plex scans an rclone mount:

1. rclone caches directory listings for `--dir-cache-time` duration
2. Each directory listing triggers GET + HEAD for every entry
3. When Plex opens a file, rclone streams it and caches to `--vfs-cache-mode`
4. Plex's media analysis reads the beginning of files (may trigger partial GETs with Range headers)

### Critical Performance Considerations

- **HEAD storm**: A library with 1000 movies across 50 directories = 1050 HEAD requests per scan
- **No polling**: HTTP has no change notification, so `--poll-interval 0` is required
- **Cache duration**: `--dir-cache-time 12h` means changes won't be visible for 12 hours
- **VFS cache**: `--vfs-cache-mode full` caches file content locally, reducing upstream load on re-reads

### Recommended rclone mount flags for Plex
```
rclone mount :http,url='http://127.0.0.1:8080/fs/': /mnt/xtream \
  --vfs-cache-mode full \
  --vfs-cache-max-size 50G \
  --dir-cache-time 12h \
  --poll-interval 0 \
  --cache-dir /tmp/rclone-cache \
  --log-level INFO
```

## Plex Scanner Risks

### Risk: Aggressive scanning
Plex may scan the entire library on startup and periodically. This triggers:
- Full directory tree walk
- HEAD requests for every file
- Potential media analysis on every file

**Mitigation**: Our `cached_only` HEAD mode returns cached metadata without upstream probes.

### Risk: File size mismatch
If HEAD returns incorrect Content-Length, Plex may:
- Fail to analyze the file
- Show incorrect duration
- Mark file as unavailable

**Mitigation**: Default `cached_only` mode only returns known sizes. `synthetic_size` mode is an escape hatch.

### Risk: Slow response times
If our proxy is slow to respond to HEAD/GET requests, Plex may:
- Timeout during scanning
- Mark files as unavailable
- Show "analyzing" indefinitely

**Mitigation**: FastAPI async handling, connection pooling via httpx, cached responses.

### Risk: Range request failures
Plex uses Range headers for media analysis. If we don't forward them correctly:
- Plex cannot analyze files
- Seeking in Plex fails
- Playback may fail

**Mitigation**: Exact Range header forwarding in the streaming proxy.

## Mount Strategy

For best Plex compatibility, recommend **separate mounts** for Movies and Series:

```
# Movies mount
rclone mount :http,url='http://127.0.0.1:8080/fs/movies/': /mnt/xtream-movies \
  --vfs-cache-mode full --dir-cache-time 12h --poll-interval 0

# Series mount
rclone mount :http,url='http://127.0.0.1:8080/fs/series/': /mnt/xtream-series \
  --vfs-cache-mode full --dir-cache-time 12h --poll-interval 0
```

This allows independent cache management and avoids scanning both libraries simultaneously.
