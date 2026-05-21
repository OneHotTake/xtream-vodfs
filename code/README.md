# xtream-vodfs - Sprint 1

## What Sprint 1 Proves

Sprint 1 proves that rclone's `:http:` backend can successfully mount and browse our HTTP virtual filesystem. This establishes the foundation for exposing Xtream VOD and Series content in Sprint 2.

### Verified Capabilities

- ✅ rclone `lsf` works - lists files
- ✅ rclone `lsd` works - lists directories
- ✅ rclone `tree` works - shows full tree structure
- ✅ rclone `mount` works (requires FUSE)
- ✅ Mounted files are readable (via rclone cat)
- ✅ HEAD behavior works - returns proper headers with Accept-Ranges
- ✅ Directory trailing-slash redirects work - rclone compatibility
- ✅ Apache/nginx-style HTML listings are parseable by rclone
- ✅ URL escaping works for special characters

## Installation

### Requirements

- Python 3.11+
- pip or uv

### Setup

```bash
cd /home/onehottake/Projects/xtream-vodfs/code

# Install dependencies
python3 -m pip install -e ".[dev]"

# Or with uv (if available)
uv pip install -e ".[dev]"
```

## Running the Server

Start the FastAPI server:

```bash
cd /home/onehottake/Projects/xtream-vodfs/code
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

The server will start at `http://127.0.0.1:8080`

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

# List movies
curl http://127.0.0.1:8080/fs/movies/

# List All movies
curl http://127.0.0.1:8080/fs/movies/All/

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

# GET with Range header (first 100 bytes)
curl -r 0-99 "http://127.0.0.1:8080/fs/movies/All/Big%20Buck%20Bunny%20%282008%29.mp4" -o /tmp/range-test.bin

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
rclone lsf http:movies/All/
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
cd /home/onehottake/Projects/xtream-vodfs/code

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

## Virtual Filesystem Structure

The Sprint 1 virtual filesystem has this hardcoded structure:

```
/fs/
├── movies/
│   ├── All/
│   │   ├── Big Buck Bunny (2008).mp4
│   │   └── Sintel (2010).mp4
│   └── Action/
│       └── Big Buck Bunny (2008).mp4
├── series/
│   └── Example Show (2024)/
│       └── Season 01/
│           └── Example Show - S01E01 - Pilot.mp4
└── samples/
    └── hello.txt
```

## Known Limitations

Sprint 1 is a proof-of-concept with these limitations:

- **Hardcoded tree** - Only the virtual structure above is available
- **No Xtream integration** - Real Xtream API calls will come in Sprint 2
- **No authentication** - No credentials or access control
- **Sample files only** - Only `hello.txt` has real content; .mp4 files are placeholders
- **No caching** - No persistent cache or TTL
- **No rate limiting** - No upstream rate limiting or backoff
- **No proxy** - No streaming proxy for Xtream content
- **Single server** - Not configured for production deployment

## HTTP API Reference

### GET `/`

Returns a status page showing Sprint 1 information.

### GET `/healthz`

Returns JSON health status:
```json
{
  "status": "ok",
  "sprint": 1
}
```

### GET `/fs/` and `GET /fs/{path:path}`

- If path is a directory: Returns Apache/nginx-style HTML listing
- If path is a file: Returns file content (supports Range headers)
- If directory exists without trailing slash: Returns 301 redirect
- If path not found: Returns 404

### HEAD `/fs/` and `HEAD /fs/{path:path}`

- If path is a directory: Returns 200 with `Content-Type: text/html`
- If path is a file: Returns 200 with `Accept-Ranges: bytes`, `Content-Type`, `Content-Length`, `Last-Modified`
- If directory exists without trailing slash: Returns 301 redirect
- If path not found: Returns 404

## Next Steps (Sprint 2)

Sprint 2 will add:

- Xtream API client integration
- Real VOD and Series content
- Streaming proxy with Range header forwarding
- Credential configuration
- Category-based directory views

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
- Run from the `code/` directory
- Check Python version: `python --version` (must be 3.11+)

### Files appear empty in mount

This is expected for .mp4 files in Sprint 1. Only `hello.txt` has real content. Sprint 2 will add real streaming.

## Development

### Project Structure

```
code/
├── app/
│   ├── __init__.py      # Package init
│   ├── main.py          # FastAPI app with routes
│   ├── models.py        # Pydantic models
│   ├── tree.py          # Virtual filesystem tree
│   ├── httpfs.py        # HTTP filesystem handlers
│   ├── proxy.py         # Streaming proxy (placeholder)
│   └── templates/
│       └── listing.html # Directory listing template
├── tests/
│   ├── __init__.py      # Test package init
│   ├── test_tree.py     # Tree structure tests
│   └── test_httpfs.py   # HTTP handler tests
├── sample_media/
│   └── hello.txt        # Sample file
├── pyproject.toml       # Project dependencies
├── IMPLEMENTATION_PLAN.md  # Sprint plan
└── README.md            # This file
```

### Adding new sample files

Place files in `code/sample_media/` and update `app/httpfs.py` to serve them from `_get_local_file_path()`.

### Modifying the virtual tree

Edit `app/tree.py` to modify the hardcoded tree structure. Sprint 2 will replace this with Xtream-generated content.

## Sprint 1 Completion

Sprint 1 was successfully completed on May 21, 2026. All acceptance criteria were met:

- ✅ All 42 pytest tests pass
- ✅ FastAPI app starts successfully
- ✅ /healthz works (returns JSON)
- ✅ /fs/ returns rclone-compatible HTML
- ✅ HEAD works on directories and files
- ✅ Range GET works on files (206 responses)
- ✅ rclone lsf can read /fs/
- ✅ rclone lsd can read /fs/
- ✅ rclone tree can read /fs/
- ✅ rclone cat can read files
- ✅ rclone mount works (requires FUSE)
- ✅ Mounted sample file can be read
- ✅ URL escaping works for special characters
- ✅ Directory trailing-slash redirects work
