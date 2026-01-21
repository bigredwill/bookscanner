#!/bin/bash

# Auto-backup script for captures folder
# Watches for changes and syncs new files to USB drive
# Only copies new files, never overwrites existing ones

CAPTURES_DIR="/home/salmon/Projects/scanner/captures"
BACKUP_DIR="/mnt/usb/captures"

echo "Starting backup watch for $CAPTURES_DIR -> $BACKUP_DIR"
echo "Only new files will be copied (--ignore-existing)"
echo "Press Ctrl+C to stop"
echo ""

while inotifywait -r -e modify,create,delete,move "$CAPTURES_DIR"; do
    echo "Change detected, syncing..."
    rsync -rv --progress --ignore-existing "$CAPTURES_DIR/" "$BACKUP_DIR/"
    echo "Sync complete"
    echo ""
done
