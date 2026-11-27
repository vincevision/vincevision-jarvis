#!/bin/bash

# ═══════════════════════════════════════════════
#   JARVIS DESKTOP APP CREATOR
#   Creates a proper app icon that works like
#   a real installed application
# ═══════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REAL_USER=$(logname 2>/dev/null || who | awk '{print $1}' | head -1)
REAL_HOME=$(eval echo "~$REAL_USER")

echo "🤖 Creating JARVIS Desktop App..."

# ── Copy icon to proper location ────────────────
ICON_DIR="/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$ICON_DIR"

if [ -f "$SCRIPT_DIR/face.png" ]; then
    cp "$SCRIPT_DIR/face.png" "$ICON_DIR/jarvis.png"
    echo "✅ Icon installed"
else
    # Create a simple icon if face.png doesn't exist
    python3 - << 'PYEOF'
try:
    from PIL import Image, ImageDraw, ImageFont
    import os

    img  = Image.new("RGB", (256, 256), "#0a0a1a")
    draw = ImageDraw.Draw(img)

    # Draw circle background
    draw.ellipse([10, 10, 246, 246], fill="#1a1a2e", outline="#00d4ff", width=4)

    # Draw J text
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 120
        )
    except Exception:
        font = ImageFont.load_default()

    draw.text((75, 60), "J", fill="#00d4ff", font=font)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    img.save(os.path.join(script_dir, "face.png"))
    img.save("/usr/share/icons/hicolor/256x256/apps/jarvis.png")
    print("✅ Icon created")
except Exception as e:
    print(f"⚠️ Could not create icon: {e}")
PYEOF
fi

# ── Create wrapper script ────────────────────────
WRAPPER="/usr/local/bin/jarvis-app"
cat > "$WRAPPER" << WRAPPER_EOF
#!/bin/bash
cd "$SCRIPT_DIR"
bash "$SCRIPT_DIR/start_jarvis.sh"
WRAPPER_EOF
chmod +x "$WRAPPER"
echo "✅ Wrapper created"

# ── Create .desktop file for app menu ───────────
DESKTOP_DIR="/usr/share/applications"
cat > "$DESKTOP_DIR/jarvis.desktop" << DESKTOP_EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=JARVIS
GenericName=AI Assistant
Comment=Tony Stark's AI Assistant - Powered by Gemini
Exec=bash "$SCRIPT_DIR/start_jarvis.sh"
Icon=jarvis
Terminal=true
Categories=Utility;AI;Assistant;
Keywords=jarvis;ai;assistant;gemini;
StartupNotify=true
StartupWMClass=JARVIS
DESKTOP_EOF

echo "✅ App menu entry created"

# ── Create desktop shortcut ──────────────────────
DESKTOP_FILE="$REAL_HOME/Desktop/JARVIS.desktop"
cat > "$DESKTOP_FILE" << DESKTOP_EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=JARVIS
GenericName=AI Assistant
Comment=Tony Stark's AI Assistant
Exec=bash "$SCRIPT_DIR/start_jarvis.sh"
Icon=$SCRIPT_DIR/face.png
Terminal=true
Categories=Utility;AI;
StartupNotify=true
DESKTOP_EOF

chmod +x "$DESKTOP_FILE"
chown "$REAL_USER:$REAL_USER" "$DESKTOP_FILE"
echo "✅ Desktop shortcut created"

# ── Make it trusted (GNOME) ──────────────────────
sudo -u "$REAL_USER" gio set "$DESKTOP_FILE" \
    metadata::trusted true 2>/dev/null || true

# ── Update icon cache ────────────────────────────
gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo ""
echo "═══════════════════════════════════════"
echo "✅ JARVIS APP INSTALLED!"
echo "═══════════════════════════════════════"
echo ""
echo "You can now launch JARVIS by:"
echo "  1. Double clicking the desktop icon"
echo "  2. Searching 'JARVIS' in app menu"
echo "  3. Typing 'jarvis' in terminal"
echo ""