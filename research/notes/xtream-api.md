# Xtream API Field Reference

## Authentication

All API calls go through `player_api.php` (or `panel_api.php` for some providers):

```
GET {base_url}/player_api.php?username={user}&password={pass}&action={action}
```

Authentication response:
```json
{
  "user_info": {
    "username": "...",
    "password": "...",
    "message": "...",
    "auth": 1,
    "status": "Active",
    "exp_date": "1234567890",
    "is_trial": "0",
    "active_cons": "0",
    "max_connections": "1",
    "allowed_output_formats": ["ts", "m3u8", "mp4", "mkv"]
  },
  "server_info": {
    "url": "...",
    "port": "8080",
    "https_port": "8443",
    "server_protocol": "http",
    "rtmp_port": "25463",
    "timezone": "Europe/London",
    "timestamp_now": 1234567890,
    "time_now": "2024-01-01 12:00:00",
    "process": true
  }
}
```

**Note**: `exp_date`, `active_cons`, `max_connections`, `is_trial` may come as strings or numbers depending on provider. Use flexible parsing.

## VOD Endpoints

### get_vod_categories
```
GET {base}/player_api.php?username=X&password=X&action=get_vod_categories
```
Response: Array of category objects
```json
[
  {
    "category_id": "1",
    "category_name": "Action Movies",
    "parent_id": 0
  }
]
```

### get_vod_streams
```
GET {base}/player_api.php?username=X&password=X&action=get_vod_streams
GET {base}/player_api.php?username=X&password=X&action=get_vod_streams&category_id=1
```
Response: Array of stream objects
```json
[
  {
    "num": 1,
    "name": "|US| The Matrix [FHD]",
    "stream_type": "movie",
    "stream_id": 12345,
    "stream_icon": "http://...",
    "container_extension": "mkv",
    "category_id": "1",
    "category_name": "Action Movies",
    "added": "2024-01-01 12:00:00",
    "is_adult": "0",
    "rating": 5,
    "rating_5based": 4.5
  }
]
```

### get_vod_info (optional/lazy)
```
GET {base}/player_api.php?username=X&password=X&action=get_vod_info&vod_id=12345
```
Response:
```json
{
  "info": {
    "movie_image": "http://...",
    "plot": "...",
    "cast": "Actor1, Actor2",
    "director": "Director Name",
    "genre": "Action",
    "duration": "120 min",
    "duration_secs": 7200,
    "bitrate": 5000,
    "rating": 8.5,
    "releasedate": "1999-03-31",
    "tmdb_id": 603,
    "backdrop_path": ["http://...", "..."],
    "youtube_trailer": "...",
    "video": {...},
    "audio": {...}
  },
  "movie_data": {
    "stream_id": 12345,
    "name": "The Matrix",
    "container_extension": "mkv",
    "category_id": "1",
    "added": "2024-01-01 12:00:00"
  }
}
```

## Series Endpoints

### get_series_categories
```
GET {base}/player_api.php?username=X&password=X&action=get_series_categories
```
Response: Same format as VOD categories.

### get_series
```
GET {base}/player_api.php?username=X&password=X&action=get_series
GET {base}/player_api.php?username=X&password=X&action=get_series&category_id=1
```
Response: Array of series objects
```json
[
  {
    "num": 1,
    "name": "Breaking Bad",
    "series_id": 54321,
    "cover": "http://...",
    "plot": "...",
    "cast": "...",
    "director": "...",
    "genre": "Crime, Drama",
    "releaseDate": "2008-01-20",
    "last_modified": "1234567890",
    "rating": 5,
    "rating_5based": 4.9,
    "backdrop_path": ["http://..."],
    "youtube_trailer": "...",
    "episode_run_time": "45",
    "category_id": "2",
    "stream_type": "series"
  }
]
```

### get_series_info
```
GET {base}/player_api.php?username=X&password=X&action=get_series_info&series_id=54321
```
**Note**: Some providers use `series` instead of `series_id` as the parameter name.

Response:
```json
{
  "seasons": [
    {"air_date": "2008-01-20", "episode_count": 7, "id": 1, "name": "Season 1", "cover": "...", "cover_big": "..."}
  ],
  "info": {
    "name": "Breaking Bad",
    "cover": "http://...",
    "plot": "...",
    "cast": "...",
    "director": "...",
    "genre": "...",
    "releaseDate": "2008-01-20",
    "last_modified": "1234567890",
    "rating": "...",
    "rating_5based": 4.9,
    "backdrop_path": ["http://..."],
    "youtube_trailer": "..."
  },
  "episodes": {
    "1": [
      {
        "id": "100001",
        "episode_num": 1,
        "season": 1,
        "title": "Pilot",
        "container_extension": "mkv",
        "added": "2024-01-01 12:00:00",
        "info": {
          "name": "Pilot",
          "plot": "...",
          "duration_secs": 3600,
          "duration": "60 min",
          "movie_image": "http://...",
          "rating": 8.0,
          "releasedate": "2008-01-20",
          "video": {...},
          "audio": {...},
          "bitrate": 3000
        }
      }
    ]
  }
}
```

**Important**: The `episodes` key is a map where keys are season numbers as strings ("1", "2", etc.) and values are arrays of episode objects.

## Stream URLs

### VOD
```
{base_url}/movie/{username}/{password}/{stream_id}.{container_extension}
```

### Series Episode
```
{base_url}/series/{username}/{password}/{episode_id}.{container_extension}
```

### Live (not in scope for v1)
```
{base_url}/live/{username}/{password}/{stream_id}.{extension}
```

## Provider Variance Notes

From inspecting `go.xtream-codes` (tellytv):

1. **ID types**: `category_id`, `stream_id`, `series_id` may be strings or integers. The Go library uses `FlexInt` to handle both.
2. **Boolean types**: `auth`, `is_trial` may be strings ("0"/"1") or booleans.
3. **Timestamps**: `exp_date`, `added`, `last_modified` may be Unix timestamps (string or int) or date strings.
4. **series_id parameter**: Some providers accept `series_id`, others accept `series` for `get_series_info`.
5. **Episode ID**: In series episodes, the `id` field is a string (not int) and is used in the stream URL.
6. **container_extension**: May be missing from individual episodes; fall back to the series-level or use "mp4".
7. **Season 0**: Some providers use season 0 for specials; handle gracefully.
8. **Empty episode titles**: Episode `title` may be empty; use episode number as fallback.

## Python Client References

- `chazlarson/py-xtream-codes`: Basic Python wrapper, similar endpoint coverage to Go library
- `pyxtream`: More feature-complete, includes M3U generation

Both confirm the same endpoint structure. The API is simple HTTP GET with JSON responses.
