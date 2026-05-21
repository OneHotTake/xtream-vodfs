# rclone HTTP Backend Behavior

## How `:http,url=` works

rclone's HTTP backend is a **read-only** remote that treats a webserver's directory listings as a filesystem.

Usage:
```
rclone lsf :http,url='http://127.0.0.1:8080/fs/':
rclone mount :http,url='http://127.0.0.1:8080/fs/': /mnt/point --vfs-cache-mode full
```

The URL must end with `/` to be treated as a directory. If it doesn't, rclone sends a HEAD request to determine if it's a file or directory.

## Directory Listing Expectations

rclone parses HTML directory listings by:
1. Fetching the URL with GET
2. Checking `Content-Type: text/html`
3. Parsing the HTML DOM for `<a>` tags with `href` attributes
4. Resolving relative hrefs against the base URL
5. Determining file vs directory by trailing `/` in href

Key parsing rules (from `rclone/backend/http/http.go`):
- Walks the full HTML DOM looking for `<a>` tags (not just `<pre>` blocks)
- Extracts `href` attribute from each `<a>` tag
- Resolves hrefs relative to the request URL
- Rejects hrefs containing `?` (query params)
- Rejects hrefs pointing to different host/scheme
- Rejects hrefs not under the root path
- Rejects hrefs containing `/` unless it's the trailing character (single-level only)
- Deduplicates names seen

**Directory detection**: Names ending with `/` are directories. Everything else is a file.

**File verification**: For each non-directory name, rclone sends a concurrent HEAD request to:
- Find file size (Content-Length)
- Check the file actually exists
- Check if it's actually a directory (redirect to trailing-slash URL)

## HEAD Behavior

rclone sends HEAD requests for every file in a directory listing (controlled by `--http-no-head`):

1. **Size discovery**: Reads `Content-Length` header
2. **Existence check**: 404 = file doesn't exist, skips it
3. **Directory detection**: 301/302 redirect to URL ending with `/` = it's a directory
4. **Metadata**: Reads `Content-Type`, `Last-Modified`, `Content-Disposition`, `Cache-Control`, etc.

HEAD response handling (from `getFsEndpoint` and `head` methods):
- 404 → assumes directory (if checking a path without trailing slash)
- 301/302/303/307/308 → checks Location header; if ends with `/` = directory, otherwise = file
- 2xx → assumes file
- 5xx/403 → assumes file (error case)
- If HEAD fails entirely → assumes file

## `--http-no-head`

When set, rclone skips HEAD requests entirely:
- Directory listings are much faster
- File sizes are unknown (-1)
- Modification times are unknown
- Non-existent files may appear in listings

For our use case, we should NOT rely on users setting `--http-no-head`. Our output must work with default rclone behavior.

## Read-Only Behavior

The HTTP backend is strictly read-only:
- Put/Update/Delete all return `errorReadOnly`
- No hash calculation
- No `rclone about` support (no free space info)

## VFS Cache Implications

When using `rclone mount` with `--vfs-cache-mode full`:
- rclone caches directory listings based on `--dir-cache-time`
- File content is cached locally as it's read
- `--poll-interval 0` is required because HTTP has no change notification
- HEAD requests during listing are the main source of upstream load during scans

**Critical**: During a Plex scan, rclone will:
1. List each directory (GET)
2. HEAD every file in each listing
3. GET file content when Plex reads it

Our caching strategy must handle the HEAD storm efficiently.

## HTML Format Requirements

rclone parses ANY valid HTML with `<a href="...">` links. It does NOT require a specific format.

Tested formats (from rclone test files):
- nginx autoindex (`<pre>` with `<a>` tags)
- Apache autoindex (table-based)
- Caddy browse template
- Simple memstore format

Minimal working format:
```html
<!doctype html>
<html>
<head><title>Index of /path/</title></head>
<body>
<h1>Index of /path/</h1>
<hr>
<pre>
<a href="../">../</a>
<a href="file.txt">file.txt</a>
<a href="dir/">dir/</a>
</pre>
<hr>
</body>
</html>
```

Key rules:
- Directories MUST have href ending with `/`
- Files MUST NOT have href ending with `/`
- Parent link `../` should be present when not at root
- hrefs must be URL-escaped (rclone uses `rest.URLPathEscape`)
- No JavaScript required
- No CSS required

## 301 Redirect for Missing Trailing Slash

When rclone encounters a path without trailing slash:
1. Sends HEAD request
2. If response is 301/302 with Location ending in `/`, treats as directory
3. If response is 200, treats as file

Our server should return 301 to the trailing-slash version for directories accessed without trailing slash.
