#!/bin/bash
# Kill all processes that might interfere with gphoto2

echo "Killing GVFS processes that interfere with camera access..."

# Kill GVFS processes
killall gvfs-gphoto2-volume-monitor 2>/dev/null
killall gvfs-mtp-volume-monitor 2>/dev/null
killall gvfsd-gphoto2 2>/dev/null

# Wait a moment
sleep 0.5

# Kill any lingering gphoto2 processes
killall gphoto2 2>/dev/null

# Verify they're gone
echo "Checking for remaining processes..."
pgrep -f "gvfs.*photo" && echo "WARNING: Some GVFS processes still running" || echo "✓ All GVFS camera processes killed"

echo ""
echo "You can now run: uv run scan.py"
echo ""
echo "Note: GVFS processes may restart automatically."
echo "If issues persist, add this to prevent auto-restart:"
echo "  chmod -x /usr/lib/gvfs/gvfsd-gphoto2"
echo "  chmod -x /usr/lib/gvfs/gvfs-gphoto2-volume-monitor"
