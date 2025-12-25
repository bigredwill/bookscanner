# Ubuntu Camera Access Fix

## Problem
Ubuntu's GVFS (GNOME Virtual File System) automatically mounts cameras when connected, which prevents gphoto2 from accessing them directly.

## Quick Fix (Temporary)
Run the provided script before each scanning session:
```bash
./kill_camera_processes.sh
uv run scan.py
```

The script kills these processes:
- `gvfs-gphoto2-volume-monitor`
- `gvfs-mtp-volume-monitor`
- `gvfsd-gphoto2`

**Note:** These processes may restart automatically after a few seconds.

## Permanent Solution (Recommended)

### Option 1: Disable GVFS Camera Support (Cleanest)
Prevent GVFS from automatically mounting cameras:

```bash
# Disable auto-mounting
sudo chmod -x /usr/lib/gvfs/gvfsd-gphoto2
sudo chmod -x /usr/lib/gvfs/gvfs-gphoto2-volume-monitor

# If you ever want to re-enable:
# sudo chmod +x /usr/lib/gvfs/gvfsd-gphoto2
# sudo chmod +x /usr/lib/gvfs/gvfs-gphoto2-volume-monitor
```

After running this, cameras won't auto-mount in file manager, but gphoto2 will work perfectly.

### Option 2: Create udev Rules
Create a rule to prevent auto-mounting for specific cameras:

```bash
sudo nano /etc/udev/rules.d/99-gphoto2.rules
```

Add this line (replace with your camera's vendor/product ID):
```
ATTRS{idVendor}=="04a9", ATTRS{idProduct}=="3331", ENV{GVFS_DISABLE_VOLUME_MONITOR}="1"
```

Find your camera IDs with: `lsusb`

Then reload rules:
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### Option 3: Stop GVFS Services Completely
**Warning:** This affects all GVFS functionality.

```bash
systemctl --user stop gvfs-gphoto2-volume-monitor.service
systemctl --user disable gvfs-gphoto2-volume-monitor.service
```

## Verification
After applying the permanent fix, verify cameras are accessible:

```bash
gphoto2 --auto-detect
```

Should show both cameras without errors.

## Current scan.py Behavior
The script automatically kills interfering processes on startup, but this is only temporary. Use a permanent solution above for best results.
