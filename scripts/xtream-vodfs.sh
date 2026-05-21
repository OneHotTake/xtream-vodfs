#!/bin/bash
#
# xtream-vodfs startup script
# Manages the FastAPI server and rclone mount
#
# Usage: ./scripts/xtream-vodfs.sh [start|stop|restart|status]
#

set -e

# Configuration - always use project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="$PROJECT_ROOT/.pids"
MOUNT_POINT="/tmp/xtream-vodfs-mount"
SERVER_PID_FILE="$PID_DIR/server.pid"
RCLONE_PID_FILE="$PID_DIR/rclone.pid"
SERVER_PORT=18080
SERVER_HOST="127.0.0.1"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Ensure PID directory exists
mkdir -p "$PID_DIR"

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if server is running
is_server_running() {
    if [ -f "$SERVER_PID_FILE" ]; then
        pid=$(cat "$SERVER_PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            return 0
        else
            rm -f "$SERVER_PID_FILE"
            return 1
        fi
    fi
    return 1
}

# Check if rclone mount is running
is_rclone_running() {
    if [ -f "$RCLONE_PID_FILE" ]; then
        pid=$(cat "$RCLONE_PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            return 0
        else
            rm -f "$RCLONE_PID_FILE"
            return 1
        fi
    fi
    return 1
}

# Start the server
start_server() {
    if is_server_running; then
        log_warn "Server is already running (PID: $(cat $SERVER_PID_FILE))"
        return 0
    fi
    
    log_info "Starting xtream-vodfs server on $SERVER_HOST:$SERVER_PORT..."
    
    cd "$PROJECT_ROOT"
    
    # Start server in background with proper output redirection
    python3 -m uvicorn app.main:app \
        --host "$SERVER_HOST" \
        --port "$SERVER_PORT" \
        > "$PROJECT_ROOT/server.log" 2>&1 &
    
    local pid=$!
    echo $pid > "$SERVER_PID_FILE"
    
    # Wait for server to start and verify it's still running
    sleep 3
    
    if is_server_running; then
        log_info "Server started successfully (PID: $(cat $SERVER_PID_FILE))"
        log_info "Server logs: $PROJECT_ROOT/server.log"
    else
        log_error "Server failed to start. Check $PROJECT_ROOT/server.log"
        rm -f "$SERVER_PID_FILE"
        return 1
    fi
}

# Stop the server
stop_server() {
    if ! is_server_running; then
        log_warn "Server is not running"
        return 0
    fi
    
    log_info "Stopping server (PID: $(cat $SERVER_PID_FILE))..."
    kill $(cat "$SERVER_PID_FILE")
    rm -f "$SERVER_PID_FILE"
    
    # Wait for process to terminate
    sleep 2
    
    if is_server_running; then
        log_warn "Server still running, forcing kill..."
        kill -9 $(cat "$SERVER_PID_FILE") 2>/dev/null || true
        rm -f "$SERVER_PID_FILE"
    fi
    
    log_info "Server stopped"
}

# Start rclone mount
start_rclone() {
    if is_rclone_running; then
        log_warn "Rclone mount is already running (PID: $(cat $RCLONE_PID_FILE))"
        return 0
    fi
    
    log_info "Creating mount point: $MOUNT_POINT"
    mkdir -p "$MOUNT_POINT"
    
    # Configure rclone remote
    log_info "Configuring rclone remote..."
    RCLONE_CONFIG="$HOME/.config/rclone/rclone.conf"
    cat > "$RCLONE_CONFIG" <<EOF
[xtream-vodfs]
type = http
url = http://$SERVER_HOST:$SERVER_PORT/fs/
EOF
    
    log_info "Starting rclone mount..."
    
    # Mount with recommended settings
    nohup rclone mount xtream-vodfs: "$MOUNT_POINT" \
        --vfs-cache-mode full \
        --dir-cache-time 12h \
        --cache-dir "$PROJECT_ROOT/.rclone-cache" \
        --log-level INFO \
        --log-file "$PROJECT_ROOT/rclone.log" \
        --daemon \
        2>&1 || true
    
    # Wait for mount to be ready
    sleep 3
    
    # Check if mount is active
    if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
        # Find the rclone mount process
        rclone_pid=$(pgrep -f "rclone mount.*$MOUNT_POINT" | head -1)
        if [ -n "$rclone_pid" ]; then
            echo "$rclone_pid" > "$RCLONE_PID_FILE"
            log_info "Rclone mount started successfully (PID: $rclone_pid)"
            log_info "Mount point: $MOUNT_POINT"
            log_info "Rclone logs: $PROJECT_ROOT/rclone.log"
        else
            log_error "Rclone mount process not found"
            return 1
        fi
    else
        log_error "Rclone mount failed. Check $PROJECT_ROOT/rclone.log"
        return 1
    fi
}

# Stop rclone mount
stop_rclone() {
    if ! is_rclone_running; then
        log_warn "Rclone mount is not running"
        return 0
    fi
    
    log_info "Stopping rclone mount (PID: $(cat $RCLONE_PID_FILE))..."
    
    # Try graceful unmount
    if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
        fusermount -u "$MOUNT_POINT" 2>/dev/null || umount "$MOUNT_POINT" 2>/dev/null || true
    fi
    
    # Kill the rclone process
    pid=$(cat "$RCLONE_PID_FILE")
    kill "$pid" 2>/dev/null || true
    rm -f "$RCLONE_PID_FILE"
    
    # Wait for process to terminate
    sleep 2
    
    if is_rclone_running; then
        log_warn "Rclone still running, forcing kill..."
        kill -9 "$pid" 2>/dev/null || true
        rm -f "$RCLONE_PID_FILE"
    fi
    
    log_info "Rclone mount stopped"
}

# Start everything
start() {
    log_info "Starting xtream-vodfs..."
    
    start_server
    if [ $? -ne 0 ]; then
        log_error "Failed to start server"
        exit 1
    fi
    
    start_rclone
    if [ $? -ne 0 ]; then
        log_error "Failed to start rclone mount"
        stop_server
        exit 1
    fi
    
    log_info "========================================="
    log_info "xtream-vodfs is running!"
    log_info "Server: http://$SERVER_HOST:$SERVER_PORT"
    log_info "Mount:  $MOUNT_POINT"
    log_info "========================================="
    log_info ""
    log_info "Use './scripts/xtream-vodfs.sh stop' to stop"
    log_info "Use './scripts/xtream-vodfs.sh status' to check status"
}

# Stop everything
stop() {
    log_info "Stopping xtream-vodfs..."
    
    stop_rclone
    stop_server
    
    log_info "xtream-vodfs stopped"
}

# Restart everything
restart() {
    log_info "Restarting xtream-vodfs..."
    stop
    sleep 2
    start
}

# Show status
status() {
    echo "========================================="
    echo "xtream-vodfs Status"
    echo "========================================="
    
    if is_server_running; then
        echo -e "Server: ${GREEN}Running${NC} (PID: $(cat $SERVER_PID_FILE))"
        echo "  URL:   http://$SERVER_HOST:$SERVER_PORT"
        echo "  Logs:  $PROJECT_ROOT/server.log"
    else
        echo -e "Server: ${RED}Stopped${NC}"
    fi
    
    if is_rclone_running; then
        echo -e "Mount:  ${GREEN}Running${NC} (PID: $(cat $RCLONE_PID_FILE))"
        echo "  Path:  $MOUNT_POINT"
        echo "  Logs:  $PROJECT_ROOT/rclone.log"
    else
        echo -e "Mount:  ${RED}Stopped${NC}"
    fi
    
    echo "========================================="
}

# Main
case "${1:-}" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
