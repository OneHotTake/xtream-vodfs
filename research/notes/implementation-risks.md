# Implementation Risks and Mitigations

## Risk 1: rclone HTTP Backend Incompatibility

**Description**: rclone's HTTP backend may not parse our directory listings correctly, or HEAD behavior may cause issues.

**Likelihood**: Medium
**Impact**: High (core functionality broken)

**Mitigations**:
- Test against rclone with actual HTML output from Sprint 1
- Use the exact nginx/apache autoindex format that rclone's tests validate against
- Implement proper 301 redirects for directories without trailing slash
- Support `--http-no-head` mode gracefully (no required HEAD for basic operation)
- Test with `rclone lsf`, `rclone lsd`, `rclone tree`, and `rclone mount`

**Detection**: Sprint 1 acceptance tests will catch this immediately.

---

## Risk 2: Provider API Variance

**Description**: Different Xtream providers return different field types, missing fields, or non-standard responses.

**Likelihood**: High
**Impact**: Medium (some providers may not work)

**Mitigations**:
- Use Pydantic v2 with `model_config = ConfigDict(extra="ignore")` for flexible parsing
- Handle string/int/bool type variance (like `FlexInt` in Go library)
- Defensive URL construction with fallback container extensions
- Test with multiple providers if possible
- Log parsing errors without exposing credentials

**Detection**: Integration testing with real provider in Sprint 2.

---

## Risk 3: Plex Scanner Overload

**Description**: Plex scanning triggers too many HEAD/GET requests, overwhelming our server or the upstream provider.

**Likelihood**: High
**Impact**: High (provider may ban, Plex may fail)

**Mitigations**:
- `cached_only` HEAD mode by default (no upstream probes)
- Aggressive in-memory caching with JSON persistence
- Configurable TTLs per endpoint type
- Global concurrency limit for upstream requests
- Backoff on 429/5xx responses
- Document recommended rclone mount flags (`--dir-cache-time 12h`, `--poll-interval 0`)

**Detection**: Monitor request rates during Sprint 3 testing.

---

## Risk 4: Streaming Proxy Performance

**Description**: Proxying large video files may introduce latency, buffering, or memory issues.

**Likelihood**: Medium
**Impact**: High (playback failures)

**Mitigations**:
- Use `httpx.AsyncClient.stream()` for zero-copy streaming
- Never buffer entire files
- Forward Range headers exactly
- Use connection pooling
- Set appropriate timeouts
- Strip hop-by-hop headers

**Detection**: VLC/cat playback tests in Sprint 2, Plex playback in Sprint 5.

---

## Risk 5: Title Cleaning Over-Aggression

**Description**: Over-cleaning titles may remove important information, causing Plex matching failures.

**Likelihood**: Medium
**Impact**: Medium (poor metadata matching)

**Mitigations**:
- Conservative cleaning: only remove well-known patterns (box tags, country-dash prefixes)
- User-configurable remove-terms list
- Option to disable cleaning entirely
- Preserve year information for matching
- Log cleaned names for debugging

**Detection**: Manual testing with diverse provider titles in Sprint 3.

---

## Risk 6: Series Info API Storm

**Description**: Fetching `get_series_info` for every show at startup overwhelms the provider.

**Likelihood**: High (if not designed carefully)
**Impact**: High (provider ban, slow startup)

**Mitigations**:
- Lazy loading: only fetch series info when browsing that show's directory
- Never fetch all series info at startup
- Per-show cache with 7-day TTL
- Rate limiting between API calls
- Backoff on errors

**Detection**: Sprint 4 acceptance tests verify no startup storm.

---

## Risk 7: Duplicate Name Collisions

**Description**: Two different movies/series with the same cleaned name collide in the virtual filesystem.

**Likelihood**: Medium
**Impact**: Medium (content inaccessible)

**Mitigations**:
- First clean name wins
- Duplicates append `[xtream-ID]` suffix
- Track seen names per directory
- Log collisions for debugging

**Detection**: Sprint 3 tests with synthetic duplicate data.

---

## Risk 8: Credential Exposure

**Description**: Xtream credentials may leak in logs, error messages, HTML output, or generated URLs visible to unauthorized users.

**Likelihood**: Low (if designed carefully)
**Impact**: Critical (account compromise)

**Mitigations**:
- Never log credentials (sanitize all log output)
- No credentials in HTML directory listings
- No credentials in exception text
- Optional auth for `/fs/` endpoint
- Bind to 127.0.0.1 by default
- Store config with safe permissions
- `.env.example` without real values

**Detection**: Code review, security audit in Sprint 5.

---

## Risk 9: Content-Length Mismatch

**Description**: Incorrect Content-Length in HEAD responses may cause Plex/rclone issues.

**Likelihood**: Medium
**Impact**: Medium (file analysis failures)

**Mitigations**:
- `cached_only` mode: only return Content-Length if known from API response
- `upstream_probe` mode: optional HEAD probe with caching
- `synthetic_size` mode: emergency fallback (documented as inaccurate)
- Always return `Accept-Ranges: bytes`
- Let actual GET response provide accurate Content-Length

**Detection**: rclone mount + VLC playback tests in Sprint 2/3.

---

## Risk 10: Docker Deployment Complexity

**Description**: Docker setup may be difficult for non-technical users.

**Likelihood**: Medium
**Impact**: Medium (adoption barrier)

**Mitigations**:
- Simple `docker-compose.yml` with sensible defaults
- `/config` volume for persistent configuration
- Healthcheck endpoint
- Clear README with step-by-step instructions
- `.env.example` with comments

**Detection**: Clean-room Docker setup test in Sprint 5.
