#!/bin/bash
# WSLg / GUI support installed on top of system + dev-tools.
# Kept separate from dev-tools.sh because:
#   - these packages only matter for GUI / desktop-style images
#   - headless or CI-only images can skip this layer entirely to slim down
#   - GUI libs change at a different cadence than CLI dev tools
# Run as root (usually right after dev-tools.sh).
set -euo pipefail

# Previous scripts clean their apt lists, so refresh the index here.
apt-get update

# --- X11 / D-Bus session ---
apt-get -y install dbus-x11

# --- CJK fonts (render zh/ja/ko correctly in GUI apps) ---
apt-get -y install fonts-wqy-zenhei fonts-noto-cjk

# --- OpenGL / Mesa (GL apps, rviz, etc.) ---
apt-get -y install mesa-utils libgl1 libglx-mesa0

# --- Audio (PulseAudio over WSLg) ---
apt-get -y install pulseaudio

rm -rf /var/lib/apt/lists/*
