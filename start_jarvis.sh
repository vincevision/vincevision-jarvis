#!/bin/bash

# ═══════════════════════════════════════════════
#   JARVIS AUTO START SCRIPT
#   Runs as root with full audio/display access
#   Fixed for Kali Linux / Parrot OS
# ═══════════════════════════════════════════════

echo "🤖 Starting JARVIS..."

# ── Get the real script directory ───────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── If not root relaunch as root ────────────────
if [ "$EUID" -ne 0 ]; then
    export JARVIS_REAL_USER="$USER"
    export JARVIS_REAL_HOME="$HOME"
    export JARVIS_REAL_UID="$(id -u)"
    export JARVIS_XDG_RUNTIME="/run/user/$(id -u)"
    export JARVIS_DBUS="$DBUS_SESSION_BUS_ADDRESS"
    export JARVIS_DISPLAY="${DISPLAY:-:0}"
    echo "🔐 Requesting root privileges..."
    exec sudo -E bash "$0" "$@"
    exit
fi

echo "✅ Running as root"

# ── Restore real user info ───────────────────────
REAL_USER="${JARVIS_REAL_USER:-$(logname 2>/dev/null || who | awk '{print $1}' | head -1)}"
REAL_HOME="${JARVIS_REAL_HOME:-$(eval echo ~$REAL_USER)}"
REAL_UID="${JARVIS_REAL_UID:-1000}"
RUNTIME_DIR="${JARVIS_XDG_RUNTIME:-/run/user/$REAL_UID}"
REAL_DISPLAY="${JARVIS_DISPLAY:-:0}"

echo "👤 Real user: $REAL_USER"
echo "🏠 Home: $REAL_HOME"
echo "🔢 UID: $REAL_UID"

# ═══════════════════════════════════════════════
#   DISPLAY ACCESS
# ═══════════════════════════════════════════════

# ═══════════════════════════════════════════════
#   DISPLAY ACCESS
# ═══════════════════════════════════════════════

echo "🖥️ Setting up display..."

export DISPLAY="${REAL_DISPLAY:-:0}"

# ── Find the REAL Xauthority file ───────────────
# On Wayland/XWayland the real auth is NOT ~/.Xauthority
# It is in /run/user/UID/.mutter-Xwaylandauth.*
# or /run/user/UID/.xauth*

REAL_XAUTH=""

# Method 1: Check mutter Xwayland auth (GNOME Wayland)
for f in /run/user/$REAL_UID/.mutter-Xwaylandauth.* \
          /run/user/$REAL_UID/.xauth* \
          /run/user/$REAL_UID/gdm/Xauthority \
          /tmp/.Xauthority-$REAL_USER \
          /tmp/.xauth*; do
    for match in $f; do
        if [ -f "$match" ] && [ -s "$match" ]; then
            REAL_XAUTH="$match"
            echo "   ✅ Found real Xauth: $REAL_XAUTH"
            break 2
        fi
    done
done

# Method 2: Ask the real user directly
if [ -z "$REAL_XAUTH" ]; then
    REAL_XAUTH=$(sudo -u "$REAL_USER" bash -c \
        'echo $XAUTHORITY' 2>/dev/null)
    if [ -n "$REAL_XAUTH" ] && [ -f "$REAL_XAUTH" ] && [ -s "$REAL_XAUTH" ]; then
        echo "   ✅ Got Xauth from user env: $REAL_XAUTH"
    else
        REAL_XAUTH=""
    fi
fi

# Method 3: Search common locations
if [ -z "$REAL_XAUTH" ]; then
    for f in \
        /run/user/$REAL_UID/* \
        /tmp/.X*-lock \
        /tmp/.xauth*
    do
        for match in $f; do
            if [ -f "$match" ] && [ -s "$match" ]; then
                # Check if it contains MIT-MAGIC-COOKIE
                if file "$match" 2>/dev/null | grep -qi "data\|MIT"; then
                    REAL_XAUTH="$match"
                    echo "   ✅ Found Xauth by search: $REAL_XAUTH"
                    break 2
                fi
            fi
        done
    done
fi

# ── Copy real auth to standard locations ────────
if [ -n "$REAL_XAUTH" ]; then
    # Copy to root
    cp "$REAL_XAUTH" /root/.Xauthority 2>/dev/null
    chmod 600 /root/.Xauthority

    # Copy to vincent
    cp "$REAL_XAUTH" "$REAL_HOME/.Xauthority" 2>/dev/null
    chmod 644 "$REAL_HOME/.Xauthority"

    export XAUTHORITY=/root/.Xauthority
    echo "   ✅ Xauthority configured: /root/.Xauthority"
else
    echo "   ⚠️  No Xauth file found, generating new cookie..."
    xauth generate "$DISPLAY" . trusted 2>/dev/null
    export XAUTHORITY=/root/.Xauthority
fi

# ── Extract and add cookie manually ─────────────
COOKIE=$(sudo -u "$REAL_USER" \
    XAUTHORITY="${REAL_XAUTH:-$REAL_HOME/.Xauthority}" \
    xauth list "$DISPLAY" 2>/dev/null | head -1)

if [ -n "$COOKIE" ]; then
    xauth -f /root/.Xauthority add $COOKIE 2>/dev/null
    echo "   ✅ Cookie added to root"
fi

# ── Grant display permissions ────────────────────
xhost +local:                    > /dev/null 2>&1
xhost +si:localuser:root         > /dev/null 2>&1
xhost +si:localuser:"$REAL_USER" > /dev/null 2>&1
xhost +                          > /dev/null 2>&1

echo "✅ Display configured: $DISPLAY"

# ═══════════════════════════════════════════════
#   AUDIO ACCESS
# ═══════════════════════════════════════════════

echo "🎤 Setting up audio..."

export XDG_RUNTIME_DIR="$RUNTIME_DIR"

# PulseAudio
PULSE_SOCKET="$RUNTIME_DIR/pulse/native"
if [ -S "$PULSE_SOCKET" ]; then
    export PULSE_SERVER="unix:$PULSE_SOCKET"
    chmod 777 "$PULSE_SOCKET" 2>/dev/null
    echo "✅ PulseAudio socket found"
else
    echo "⚠️  PulseAudio socket not found, starting..."
    sudo -u "$REAL_USER" pulseaudio --start 2>/dev/null
    sleep 1
    if [ -S "$PULSE_SOCKET" ]; then
        export PULSE_SERVER="unix:$PULSE_SOCKET"
        chmod 777 "$PULSE_SOCKET" 2>/dev/null
        echo "✅ PulseAudio started"
    fi
fi

# PipeWire
PIPEWIRE_SOCKET="$RUNTIME_DIR/pipewire-0"
if [ -S "$PIPEWIRE_SOCKET" ]; then
    export PIPEWIRE_RUNTIME_DIR="$RUNTIME_DIR"
    chmod 777 "$PIPEWIRE_SOCKET" 2>/dev/null
    echo "✅ PipeWire socket found"
fi

# Add root to audio group
usermod -aG audio root 2>/dev/null

# Copy Pulse cookie
export PULSE_RUNTIME_PATH="$RUNTIME_DIR/pulse"
export PULSE_COOKIE="$REAL_HOME/.config/pulse/cookie"
if [ -f "$REAL_HOME/.config/pulse/cookie" ]; then
    mkdir -p /root/.config/pulse
    cp "$REAL_HOME/.config/pulse/cookie" \
       /root/.config/pulse/cookie 2>/dev/null
    chmod 600 /root/.config/pulse/cookie 2>/dev/null
    echo "✅ Pulse cookie copied"
fi

# ═══════════════════════════════════════════════
#   DBUS ACCESS
# ═══════════════════════════════════════════════

echo "🔌 Setting up DBus..."

DBUS_ADDR="${JARVIS_DBUS:-}"
if [ -z "$DBUS_ADDR" ]; then
    DBUS_ADDR=$(sudo -u "$REAL_USER" \
        bash -c 'echo $DBUS_SESSION_BUS_ADDRESS' 2>/dev/null)
fi

if [ -n "$DBUS_ADDR" ]; then
    export DBUS_SESSION_BUS_ADDRESS="$DBUS_ADDR"
    echo "✅ DBus configured"
else
    DBUS_SOCKET="$RUNTIME_DIR/bus"
    if [ -S "$DBUS_SOCKET" ]; then
        export DBUS_SESSION_BUS_ADDRESS="unix:path=$DBUS_SOCKET"
        echo "✅ DBus socket found"
    else
        echo "⚠️  DBus not available — using memory backend"
        export GSETTINGS_BACKEND=memory
    fi
fi

# ═══════════════════════════════════════════════
#   GTK / ICON THEME FIX
#   Fixes Flat-Remix-Blue-Dark SVG crash as root
# ═══════════════════════════════════════════════

echo "🎨 Fixing GTK for root..."

# Force Adwaita theme (PNG icons not SVG)
export GTK_THEME=Adwaita
export ICON_THEME=Adwaita
export GSK_RENDERER=cairo
export GDK_RENDERING=cairo
export GLYCIN_DISABLE_SANDBOX=1
export GDK_PIXBUF_DISALLOW_URI=1

# Qt — use Fusion style (no native GTK dialogs)
export QT_STYLE_OVERRIDE=Fusion
export QT_QPA_PLATFORMTHEME=
export XDG_CURRENT_DESKTOP=generic
export DESKTOP_SESSION=

# Write GTK config for root
mkdir -p /root/.config/gtk-3.0
mkdir -p /root/.config/gtk-4.0

cat > /root/.config/gtk-3.0/settings.ini << 'GTKEOF'
[Settings]
gtk-icon-theme-name=Adwaita
gtk-theme-name=Adwaita
gtk-font-name=Sans 10
gtk-error-bell=false
GTKEOF

cat > /root/.config/gtk-4.0/settings.ini << 'GTKEOF'
[Settings]
gtk-icon-theme-name=Adwaita
gtk-theme-name=Adwaita
gtk-font-name=Sans 10
gtk-error-bell=false
GTKEOF

# Disable SVG pixbuf loader for root
# This is the main fix for the bwrap/glycin crash
CACHE_FILE=$(find /usr/lib -name "loaders.cache" 2>/dev/null | head -1)
if [ -n "$CACHE_FILE" ]; then
    mkdir -p /root/.config/gdk-pixbuf
    CUSTOM_CACHE="/root/.config/gdk-pixbuf/loaders.cache"
    grep -v -i "svg\|glycin" "$CACHE_FILE" \
        > "$CUSTOM_CACHE" 2>/dev/null
    export GDK_PIXBUF_MODULE_FILE="$CUSTOM_CACHE"
    echo "✅ SVG loader disabled"
else
    echo "⚠️  loaders.cache not found"
fi

# Apply gsettings with memory backend
export GSETTINGS_BACKEND=memory
gsettings set org.gnome.desktop.interface \
    icon-theme 'Adwaita' 2>/dev/null || true
gsettings set org.gnome.desktop.interface \
    gtk-theme 'Adwaita' 2>/dev/null || true

# Also fix for real user permanently
sudo -u "$REAL_USER" gsettings set \
    org.gnome.desktop.interface \
    icon-theme 'Adwaita' 2>/dev/null || true

echo "✅ GTK configured"

# ═══════════════════════════════════════════════
#   PYTHON ENVIRONMENT
# ═══════════════════════════════════════════════

echo "🐍 Setting up Python..."

cd "$SCRIPT_DIR"

if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
    source "$SCRIPT_DIR/venv/bin/activate"
    echo "✅ Virtual environment activated"
else
    echo "❌ Virtual environment not found at $SCRIPT_DIR/venv"
    echo "Run: python3 -m venv venv && pip install -r requirements.txt"
    exit 1
fi

echo "🐍 Python: $(python3 --version)"

# ═══════════════════════════════════════════════
#   PRE-FLIGHT CHECKS
# ═══════════════════════════════════════════════

echo "🔊 Testing audio..."
python3 -c "
import sounddevice as sd
devices = sd.query_devices()
print(f'✅ Audio devices: {len(devices)}')
" 2>/dev/null || {
    echo "⚠️  Audio test failed, trying user mode..."
    cd "$SCRIPT_DIR"
    sudo -u "$REAL_USER" \
        DISPLAY="$DISPLAY" \
        XAUTHORITY="$REAL_HOME/.Xauthority" \
        XDG_RUNTIME_DIR="$RUNTIME_DIR" \
        DBUS_SESSION_BUS_ADDRESS="$DBUS_ADDR" \
        GTK_THEME=Adwaita \
        GSK_RENDERER=cairo \
        GDK_PIXBUF_MODULE_FILE="${GDK_PIXBUF_MODULE_FILE:-}" \
        QT_STYLE_OVERRIDE=Fusion \
        QT_QPA_PLATFORMTHEME= \
        GLYCIN_DISABLE_SANDBOX=1 \
        bash -c "source venv/bin/activate && python3 main.py"
    status=$?
    if [ "$status" -ne 0 ]; then
        echo ""
        echo "❌ JARVIS failed to start (exit code $status)."
        if [ -t 0 ]; then
            read -r -p "Press Enter to close this window..." _
        fi
    fi
    exit "$status"
}

echo "🖥️  Testing display..."
python3 -c "
import os, subprocess
result = subprocess.run(
    ['xdpyinfo'],
    capture_output=True, text=True,
    env={**os.environ, 'DISPLAY': '${DISPLAY}'}
)
if result.returncode == 0:
    print('✅ Display OK')
else:
    print('⚠️  Display check failed (may still work)')
" 2>/dev/null || echo "⚠️  xdpyinfo not found"

# ═══════════════════════════════════════════════
#   LAUNCH JARVIS
# ═══════════════════════════════════════════════

echo ""
echo "═══════════════════════════════════════"
echo "🚀 Launching Jarvis..."
echo "═══════════════════════════════════════"
echo ""

# Launch with all fixes and filter noise
python3 main.py 2> >(grep -v \
    "qt.qpa.wayland\|ALSA lib\|snd_pcm\|pcm.c\|QDBusError\|portal\|Xlib.xauth\|bwrap\|glycin\|gdk-pixbuf\|Bail out\|gtkiconhelper\|ensure_surface\|Flat-Remix\|image-missing\|Error creating proxy\|g-io-error\|Session DBus\|qt.qpa.theme\|non-zero\|key repeat" >&2)
status=$?

echo ""
if [ "$status" -ne 0 ]; then
    echo "❌ JARVIS failed to start (exit code $status)."
    if [ -t 0 ]; then
        read -r -p "Press Enter to close this window..." _
    fi
    exit "$status"
fi

echo "🔄 Jarvis has exited."