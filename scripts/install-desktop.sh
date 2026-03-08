#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP_TEMPLATE="$DIR/mastercontrol.desktop"
INSTALL_DIR="$HOME/.local/share/applications"
INSTALLED_FILE="$INSTALL_DIR/mastercontrol.desktop"

if [ ! -f "$DESKTOP_TEMPLATE" ]; then
    echo "ERROR: $DESKTOP_TEMPLATE not found"
    exit 1
fi

mkdir -p "$INSTALL_DIR"

# Generate .desktop file with correct absolute paths
sed "s|INSTALL_DIR|$DIR|g" "$DESKTOP_TEMPLATE" > "$INSTALLED_FILE"

# Update desktop database if available
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$INSTALL_DIR" 2>/dev/null || true
fi

echo "Desktop launcher installed to $INSTALLED_FILE"
echo "You should now see 'Master Control' in your application menu."
