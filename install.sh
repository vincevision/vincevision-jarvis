#!/bin/bash

# ═══════════════════════════════════════════════════════════════════
#   JARVIS INSTALLER
#   Full setup for Debian / Ubuntu / Kali / Parrot Linux
#   Run: sudo bash install.sh
# ═══════════════════════════════════════════════════════════════════

# ── Colors ──────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── Banner ───────────────────────────────────────────────────────────
print_banner() {
    echo -e "${CYAN}"
    echo "  ╔══════════════════════════════════════════════╗"
    echo "  ║           JARVIS - Full Installer            ║"
    echo "  ║    AI Assistant + Offensive Security Suite   ║"
    echo "  ╚══════════════════════════════════════════════╝"
    echo -e "${NC}"
}

ok()   { echo -e "${GREEN}[OK]${NC}   $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERR]${NC}  $1"; }
step() { echo -e "\n${CYAN}══ $1 ══${NC}"; }

# ── Must be root ─────────────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    echo "🔐 Requesting root..."
    exec sudo bash "$0" "$@"
    exit
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REAL_USER=$(logname 2>/dev/null || who | awk '{print $1}' | head -1)
REAL_HOME=$(eval echo "~$REAL_USER")

print_banner
echo "  📁 Installing from : $SCRIPT_DIR"
echo "  👤 User            : $REAL_USER"
echo "  🏠 Home            : $REAL_HOME"
echo ""

# ════════════════════════════════════════════════════════════════════
# STEP 1 — SYSTEM UPDATE
# ════════════════════════════════════════════════════════════════════
step "Step 1: Updating System"
apt-get update -y
apt-get upgrade -y
ok "System updated"

# ════════════════════════════════════════════════════════════════════
# STEP 2 — CORE SYSTEM DEPENDENCIES
# ════════════════════════════════════════════════════════════════════
step "Step 2: Installing Core System Dependencies"
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    python3-tk \
    build-essential \
    libssl-dev \
    libffi-dev \
    portaudio19-dev \
    libasound2-dev \
    libopencv-dev \
    ffmpeg \
    git \
    curl \
    wget \
    unzip \
    zip \
    p7zip-full \
    jq \
    tmux \
    screen \
    htop \
    tree \
    xauth \
    xhost \
    xclip \
    xsel \
    xdotool \
    xinput \
    x11-utils \
    wmctrl \
    scrot \
    libnotify-bin \
    qrencode \
    tesseract-ocr \
    code 2>/dev/null || true
ok "Core system dependencies installed"

# ════════════════════════════════════════════════════════════════════
# STEP 3 — NETWORK & RECON TOOLS
# ════════════════════════════════════════════════════════════════════
step "Step 3: Installing Network & Recon Tools"
apt-get install -y \
    nmap \
    arp-scan \
    netcat-openbsd \
    socat \
    whois \
    dnsutils \
    net-tools \
    iproute2 \
    iputils-ping \
    traceroute \
    tcpdump \
    tshark \
    wireshark \
    curl \
    wget 2>/dev/null || true
ok "Network tools installed"

# ════════════════════════════════════════════════════════════════════
# STEP 4 — WIFI OFFENSIVE TOOLS
# ════════════════════════════════════════════════════════════════════
step "Step 4: Installing WiFi Offensive Tools"
apt-get install -y \
    aircrack-ng \
    wifite \
    hostapd \
    dnsmasq \
    iw \
    wireless-tools \
    wpasupplicant \
    macchanger \
    mdk4 \
    mdk3 \
    bettercap 2>/dev/null || true

# hcxdumptool and hcxtools for PMKID attacks
apt-get install -y \
    hcxdumptool \
    hcxtools 2>/dev/null || true

# hostapd-wpe for KARMA attacks
apt-get install -y hostapd-wpe 2>/dev/null || true

ok "WiFi offensive tools installed"

# ════════════════════════════════════════════════════════════════════
# STEP 5 — EXPLOITATION TOOLS
# ════════════════════════════════════════════════════════════════════
step "Step 5: Installing Exploitation Tools"

# Metasploit Framework
if ! command -v msfconsole &>/dev/null; then
    info "Installing Metasploit Framework..."
    curl https://raw.githubusercontent.com/rapid7/metasploit-omnibus/master/config/templates/metasploit-framework-wrappers/msfupdate.erb \
        > /tmp/msfinstall 2>/dev/null
    chmod +x /tmp/msfinstall
    /tmp/msfinstall 2>/dev/null || warn "Metasploit install failed — install manually"
else
    ok "Metasploit already installed"
fi

# ExploitDB / Searchsploit
apt-get install -y exploitdb 2>/dev/null || \
    pip3 install exploitdb 2>/dev/null || \
    warn "exploitdb install failed"

# Other exploit tools
apt-get install -y \
    hydra \
    john \
    hashcat \
    sqlmap \
    nikto \
    gobuster \
    dirb \
    wpscan \
    crunch \
    cewl \
    medusa 2>/dev/null || true

ok "Exploitation tools installed"

# ════════════════════════════════════════════════════════════════════
# STEP 6 — OSINT TOOLS
# ════════════════════════════════════════════════════════════════════
step "Step 6: Installing OSINT Tools"

apt-get install -y \
    theharvester \
    recon-ng \
    maltego \
    exiftool \
    libimage-exiftool-perl 2>/dev/null || true

ok "OSINT system tools installed"

# ════════════════════════════════════════════════════════════════════
# STEP 7 — DARK WEB / ANONYMITY TOOLS
# ════════════════════════════════════════════════════════════════════
step "Step 7: Installing Dark Web & Anonymity Tools"

apt-get install -y \
    tor \
    torsocks \
    proxychains4 \
    torbrowser-launcher 2>/dev/null || true

# Enable and start Tor service
systemctl enable tor 2>/dev/null || true
systemctl start tor 2>/dev/null || true

# Configure proxychains for Tor
PROXY_CONF="/etc/proxychains4.conf"
if [ -f "$PROXY_CONF" ]; then
    sed -i 's/^strict_chain/#strict_chain/'   "$PROXY_CONF"
    sed -i 's/^#dynamic_chain/dynamic_chain/' "$PROXY_CONF"
    if ! grep -q "socks5.*9050" "$PROXY_CONF"; then
        echo "socks5 127.0.0.1 9050" >> "$PROXY_CONF"
    fi
    ok "Proxychains configured for Tor"
else
    warn "proxychains4.conf not found"
fi

ok "Dark web tools installed"

# ════════════════════════════════════════════════════════════════════
# STEP 8 — FORENSICS & STEGANOGRAPHY TOOLS
# ════════════════════════════════════════════════════════════════════
step "Step 8: Installing Forensics & Steganography Tools"

apt-get install -y \
    binwalk \
    steghide \
    foremost \
    strings \
    gdb \
    ltrace \
    strace \
    radare2 \
    objdump \
    hexdump \
    xxd \
    volatility3 2>/dev/null || true

ok "Forensics tools installed"

# ════════════════════════════════════════════════════════════════════
# STEP 9 — SECURITY & SNIFFING TOOLS
# ════════════════════════════════════════════════════════════════════
step "Step 9: Installing Security & Sniffing Tools"

apt-get install -y \
    snort \
    suricata \
    iptables \
    ufw \
    fail2ban \
    rkhunter \
    chkrootkit \
    aide 2>/dev/null || true

ok "Security tools installed"

# ════════════════════════════════════════════════════════════════════
# STEP 10 — BLUETOOTH TOOLS
# ════════════════════════════════════════════════════════════════════
step "Step 10: Installing Bluetooth Tools"

apt-get install -y \
    bluetooth \
    bluez \
    bluez-tools \
    rfkill \
    btscanner \
    blueman 2>/dev/null || true

ok "Bluetooth tools installed"

# ════════════════════════════════════════════════════════════════════
# STEP 11 — SMART HOME / IOT TOOLS
# ════════════════════════════════════════════════════════════════════
step "Step 11: Installing Smart Home & IoT Tools"

apt-get install -y \
    mosquitto \
    mosquitto-clients \
    zigbee2mqtt 2>/dev/null || true

ok "Smart home tools installed"

# ════════════════════════════════════════════════════════════════════
# STEP 12 — BROWSER TOOLS
# ════════════════════════════════════════════════════════════════════
step "Step 12: Installing Browser Dependencies"

apt-get install -y \
    chromium \
    chromium-driver \
    firefox-esr 2>/dev/null || true

# Brave Browser
if ! command -v brave-browser &>/dev/null; then
    info "Installing Brave Browser..."
    curl -fsS https://dl.brave.com/install.sh | bash 2>/dev/null || \
        warn "Brave install failed — install manually from brave.com"
else
    ok "Brave already installed"
fi

# ── NEW: signal-cli for Number Tracer ───────────────────────────────
if ! command -v signal-cli &>/dev/null; then
    info "Installing signal-cli (for Number Tracer Signal lookups)..."
    apt-get install -y signal-cli 2>/dev/null || \
        warn "signal-cli not in apt — install manually if needed"
else
    ok "signal-cli already installed"
fi

ok "Browser tools installed"

# ════════════════════════════════════════════════════════════════════
# STEP 13 — GIVE TOOLS CAPABILITIES (No sudo needed)
# ════════════════════════════════════════════════════════════════════
step "Step 13: Setting Security Tool Capabilities"

for tool in arp-scan nmap tcpdump; do
    TOOL_PATH=$(which $tool 2>/dev/null)
    if [ -n "$TOOL_PATH" ]; then
        setcap cap_net_raw,cap_net_admin=eip "$TOOL_PATH" 2>/dev/null
        ok "$tool — capabilities set"
    fi
done

ok "Tool capabilities configured"

# ════════════════════════════════════════════════════════════════════
# STEP 14 — PYTHON VIRTUAL ENVIRONMENT
# ════════════════════════════════════════════════════════════════════
step "Step 14: Setting Up Python Virtual Environment"

cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    sudo -u "$REAL_USER" python3 -m venv venv
    ok "Virtual environment created"
else
    ok "Virtual environment already exists"
fi

# Activate venv
source venv/bin/activate

ok "Virtual environment activated"

# ════════════════════════════════════════════════════════════════════
# STEP 15 — BOOTSTRAP MINIMAL DEPS (for dependency_manager)
# ════════════════════════════════════════════════════════════════════
step "Step 15: Bootstrapping pip & dependency manager"

pip install --upgrade pip --quiet
pip install wheel setuptools --quiet
# Bare minimum needed for dependency_manager.py to run
pip install requests --quiet 2>/dev/null || true

ok "Bootstrap complete"

# ════════════════════════════════════════════════════════════════════
# STEP 16 — AUTO DEPENDENCY MANAGER (NEW)
# ════════════════════════════════════════════════════════════════════
step "Step 16: Running JARVIS Auto-Dependency Manager"

if [ -f "$SCRIPT_DIR/core/dependency_manager.py" ]; then
    info "Detected dependency_manager.py — using it for Python packages"

    # Sync requirements.txt with registry
    sudo -u "$REAL_USER" "$SCRIPT_DIR/venv/bin/python" \
        -m core.dependency_manager --update 2>/dev/null || \
        warn "Could not update requirements.txt"

    # Install everything (including optional)
    sudo -u "$REAL_USER" "$SCRIPT_DIR/venv/bin/python" \
        -m core.dependency_manager --install --all 2>/dev/null || \
        warn "Some auto-managed packages failed"

    ok "Auto-managed dependencies installed"
else
    warn "core/dependency_manager.py not found — falling back to requirements.txt"
fi

# ════════════════════════════════════════════════════════════════════
# STEP 17 — REQUIREMENTS.TXT (Fallback / additional packages)
# ════════════════════════════════════════════════════════════════════
step "Step 17: Installing requirements.txt Packages"

if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt 2>/dev/null || \
        warn "Some packages failed — check requirements.txt"
    ok "requirements.txt packages installed"
else
    warn "requirements.txt not found"
fi

ok "Core Python packages done"

# ════════════════════════════════════════════════════════════════════
# STEP 18 — OSINT PYTHON PACKAGES
# ════════════════════════════════════════════════════════════════════
step "Step 18: Installing OSINT Python Packages"

OSINT_PACKAGES=(
    "sherlock-project"
    "holehe"
    "h8mail"
    "stem"
    "pwncat-cs"
    "shodan"
    "censys"
    "dnspython"
    "tldextract"
    "fake-useragent"
    "instaloader"
    "tweepy"
    "socid-extractor"
)

for pkg in "${OSINT_PACKAGES[@]}"; do
    pip install "$pkg" --quiet 2>/dev/null && \
        ok "Installed: $pkg" || \
        warn "Failed: $pkg (non-critical)"
done

ok "OSINT Python packages done"

# ════════════════════════════════════════════════════════════════════
# STEP 19 — OFFENSIVE SECURITY PYTHON PACKAGES
# ════════════════════════════════════════════════════════════════════
step "Step 19: Installing Offensive Security Python Packages"

OFFENSIVE_PACKAGES=(
    "pynput"
    "evdev"
    "mss"
    "pyperclip"
    "cryptography"
    "impacket"
    "scapy"
    "paramiko"
    "netaddr"
)

for pkg in "${OFFENSIVE_PACKAGES[@]}"; do
    pip install "$pkg" --quiet 2>/dev/null && \
        ok "Installed: $pkg" || \
        warn "Failed: $pkg (non-critical)"
done

ok "Offensive Python packages done"

# ════════════════════════════════════════════════════════════════════
# STEP 20 — NUMBER TRACER PACKAGES (NEW)
# ════════════════════════════════════════════════════════════════════
step "Step 20: Installing Number Tracer Packages"

TRACER_PACKAGES=(
    "phonenumbers"
    "beautifulsoup4"
    "telethon"
    "Pillow"
)

for pkg in "${TRACER_PACKAGES[@]}"; do
    pip install "$pkg" --quiet 2>/dev/null && \
        ok "Installed: $pkg" || \
        warn "Failed: $pkg"
done

ok "Number Tracer packages done"

# ════════════════════════════════════════════════════════════════════
# STEP 21 — PLAYWRIGHT BROWSERS
# ════════════════════════════════════════════════════════════════════
step "Step 21: Installing Playwright Browsers"

# Module form: cannot be shadowed by a global `playwright` from Node/another venv.
if python -m playwright install chromium; then
    ok "Chromium installed"
else
    warn "Chromium download failed — browser agents will not work yet."
    echo "    Retry:  python -m playwright install --with-deps chromium"
    echo "    Diagnose: python -m playwright install --dry-run chromium"
fi
python -m playwright install firefox 2>/dev/null || true
python -m playwright install-deps  2>/dev/null || true

# Verify the binary really exists instead of trusting the exit code alone.
python - <<'PYCHECK' || true
from core.browser_check import chromium_status, describe
st = chromium_status()
print(("✅ " if st["installed"] else "⚠️  ") + describe(st))
PYCHECK

# ════════════════════════════════════════════════════════════════════
# STEP 22 — CREATE JARVIS DIRECTORIES
# ════════════════════════════════════════════════════════════════════
step "Step 22: Creating JARVIS Directories"

DIRS=(
    "$REAL_HOME/jarvis_captures/wifi"
    "$REAL_HOME/jarvis_captures/payloads"
    "$REAL_HOME/jarvis_captures/osint"
    "$REAL_HOME/jarvis_captures/darkweb"
    "$REAL_HOME/jarvis_captures/keylogger"
    "$REAL_HOME/jarvis_captures/exploits"
    "$REAL_HOME/JarvisProjects"
    "$SCRIPT_DIR/config"
    "$SCRIPT_DIR/config/telegram_sessions"
    "$SCRIPT_DIR/memory"
    "$SCRIPT_DIR/logs"
    "$SCRIPT_DIR/core"
    "$SCRIPT_DIR/actions"
    "$SCRIPT_DIR/agent"
    "$SCRIPT_DIR/reports/number_traces"
    "$SCRIPT_DIR/reports/telegram_photos"
)

for dir in "${DIRS[@]}"; do
    mkdir -p "$dir"
    chown "$REAL_USER:$REAL_USER" "$dir"
    ok "Created: $dir"
done

ok "Directories created"

# ════════════════════════════════════════════════════════════════════
# STEP 23 — SUDOERS (Passwordless for JARVIS tools)
# ════════════════════════════════════════════════════════════════════
step "Step 23: Configuring Passwordless Sudo"

JARVIS_PATH="$SCRIPT_DIR/start_jarvis.sh"
SUDOERS_FILE="/etc/sudoers.d/jarvis"

if [ ! -f "$SUDOERS_FILE" ]; then
    cat > "$SUDOERS_FILE" << EOF
# ── JARVIS Passwordless Permissions ──────────────────────────────
# Core
$REAL_USER ALL=(ALL) NOPASSWD: /bin/bash $JARVIS_PATH

# Network tools
$REAL_USER ALL=(ALL) NOPASSWD: /usr/bin/nmap
$REAL_USER ALL=(ALL) NOPASSWD: /usr/bin/arp-scan
$REAL_USER ALL=(ALL) NOPASSWD: /usr/sbin/tcpdump
$REAL_USER ALL=(ALL) NOPASSWD: /usr/bin/tshark

# WiFi tools
$REAL_USER ALL=(ALL) NOPASSWD: /usr/sbin/airmon-ng
$REAL_USER ALL=(ALL) NOPASSWD: /usr/sbin/airodump-ng
$REAL_USER ALL=(ALL) NOPASSWD: /usr/sbin/aireplay-ng
$REAL_USER ALL=(ALL) NOPASSWD: /usr/sbin/aircrack-ng
$REAL_USER ALL=(ALL) NOPASSWD: /usr/bin/wifite
$REAL_USER ALL=(ALL) NOPASSWD: /usr/sbin/hostapd
$REAL_USER ALL=(ALL) NOPASSWD: /usr/sbin/hostapd-wpe
$REAL_USER ALL=(ALL) NOPASSWD: /usr/sbin/dnsmasq
$REAL_USER ALL=(ALL) NOPASSWD: /usr/sbin/macchanger
$REAL_USER ALL=(ALL) NOPASSWD: /usr/bin/hcxdumptool
$REAL_USER ALL=(ALL) NOPASSWD: /usr/bin/hcxtools
$REAL_USER ALL=(ALL) NOPASSWD: /usr/sbin/iw
$REAL_USER ALL=(ALL) NOPASSWD: /usr/bin/iwconfig
$REAL_USER ALL=(ALL) NOPASSWD: /usr/sbin/bettercap

# Exploitation tools
$REAL_USER ALL=(ALL) NOPASSWD: /usr/bin/msfconsole
$REAL_USER ALL=(ALL) NOPASSWD: /usr/bin/msfvenom
$REAL_USER ALL=(ALL) NOPASSWD: /usr/bin/searchsploit
$REAL_USER ALL=(ALL) NOPASSWD: /usr/bin/hydra
$REAL_USER ALL=(ALL) NOPASSWD: /usr/sbin/john
$REAL_USER ALL=(ALL) NOPASSWD: /usr/bin/hashcat

# Security tools
$REAL_USER ALL=(ALL) NOPASSWD: /usr/bin/nikto
$REAL_USER ALL=(ALL) NOPASSWD: /usr/bin/sqlmap
$REAL_USER ALL=(ALL) NOPASSWD: /usr/bin/gobuster

# Anonymity tools
$REAL_USER ALL=(ALL) NOPASSWD: /bin/systemctl start tor
$REAL_USER ALL=(ALL) NOPASSWD: /bin/systemctl stop tor
$REAL_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart tor
$REAL_USER ALL=(ALL) NOPASSWD: /usr/bin/proxychains4

# System
$REAL_USER ALL=(ALL) NOPASSWD: /sbin/ip
$REAL_USER ALL=(ALL) NOPASSWD: /bin/ip
$REAL_USER ALL=(ALL) NOPASSWD: /sbin/ifconfig
EOF

    chmod 440 "$SUDOERS_FILE"
    ok "Passwordless sudo configured"
else
    ok "Passwordless sudo already configured"
fi

# ════════════════════════════════════════════════════════════════════
# STEP 24 — MAKE SCRIPTS EXECUTABLE
# ════════════════════════════════════════════════════════════════════
step "Step 24: Setting Script Permissions"

chmod +x "$SCRIPT_DIR/start_jarvis.sh" 2>/dev/null || true
chmod +x "$SCRIPT_DIR/setup.py"        2>/dev/null || true
chmod +x "$SCRIPT_DIR/install.sh"      2>/dev/null || true

chown -R "$REAL_USER:$REAL_USER" "$SCRIPT_DIR"

ok "Permissions set"

# ════════════════════════════════════════════════════════════════════
# STEP 25 — DESKTOP SHORTCUT
# ════════════════════════════════════════════════════════════════════
step "Step 25: Creating Desktop Shortcut"

DESKTOP_DIR="$REAL_HOME/Desktop"
mkdir -p "$DESKTOP_DIR"

DESKTOP_FILE="$DESKTOP_DIR/Jarvis.desktop"
cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Type=Application
Name=JARVIS
Comment=AI Assistant with Offensive Security Suite
Exec=bash "$SCRIPT_DIR/start_jarvis.sh"
Icon=$SCRIPT_DIR/face.png
Terminal=true
Hidden=false
X-GNOME-Autostart-enabled=true
Categories=Security;Network;
EOF

chmod +x "$DESKTOP_FILE"
chown "$REAL_USER:$REAL_USER" "$DESKTOP_FILE"
ok "Desktop shortcut created"

# ════════════════════════════════════════════════════════════════════
# STEP 26 — GLOBAL COMMAND
# ════════════════════════════════════════════════════════════════════
step "Step 26: Creating Global 'jarvis' Command"

cat > /usr/local/bin/jarvis << EOF
#!/bin/bash
bash "$SCRIPT_DIR/start_jarvis.sh"
EOF

chmod +x /usr/local/bin/jarvis
ok "Global 'jarvis' command created"

# ════════════════════════════════════════════════════════════════════
# STEP 27 — AUTOSTART ON LOGIN
# ════════════════════════════════════════════════════════════════════
step "Step 27: Configuring Autostart"

AUTOSTART_DIR="$REAL_HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

cat > "$AUTOSTART_DIR/jarvis.desktop" << EOF
[Desktop Entry]
Type=Application
Name=JARVIS
Comment=AI Assistant Auto Start
Exec=bash "$SCRIPT_DIR/start_jarvis.sh"
Terminal=true
Hidden=false
X-GNOME-Autostart-enabled=true
EOF

chown -R "$REAL_USER:$REAL_USER" "$AUTOSTART_DIR"
ok "Autostart configured"

# ════════════════════════════════════════════════════════════════════
# STEP 28 — CHECK API KEYS
# ════════════════════════════════════════════════════════════════════
step "Step 28: Checking API Keys"

API_FILE="$SCRIPT_DIR/config/api_keys.json"
if [ -f "$API_FILE" ]; then
    GEMINI=$(python3 -c "
import json
try:
    d=json.load(open('$API_FILE'))
    print('✅' if d.get('gemini_api_key') else '❌ Missing')
except:
    print('❌ Error')
" 2>/dev/null)
    GROQ=$(python3 -c "
import json
try:
    d=json.load(open('$API_FILE'))
    print('✅' if d.get('groq_api_key') else '❌ Missing')
except:
    print('❌ Error')
" 2>/dev/null)
    echo "  Gemini API : $GEMINI"
    echo "  Groq API   : $GROQ"
else
    warn "No api_keys.json found at $API_FILE"
    warn "Create it with your API keys before starting JARVIS"

    # Create template
    cat > "$API_FILE" << EOF
{
    "gemini_api_key": "YOUR_GEMINI_API_KEY_HERE",
    "groq_api_key":   "YOUR_GROQ_API_KEY_HERE"
}
EOF
    chown "$REAL_USER:$REAL_USER" "$API_FILE"
    ok "Template api_keys.json created at $API_FILE"
fi

# ════════════════════════════════════════════════════════════════════
# STEP 29 — VERIFY CRITICAL TOOLS
# ════════════════════════════════════════════════════════════════════
step "Step 29: Verifying Critical Tool Installation"

TOOLS_TO_CHECK=(
    "python3"
    "pip3"
    "nmap"
    "aircrack-ng"
    "tor"
    "proxychains4"
    "searchsploit"
    "msfconsole"
    "theHarvester"
    "hydra"
    "hashcat"
    "tcpdump"
    "macchanger"
    "hcxdumptool"
    "bettercap"
    "tesseract"
)

echo ""
for tool in "${TOOLS_TO_CHECK[@]}"; do
    if command -v "$tool" &>/dev/null; then
        ok "$tool"
    else
        warn "$tool — not found (optional)"
    fi
done

# ════════════════════════════════════════════════════════════════════
# STEP 30 — DEPENDENCY STATUS REPORT (NEW)
# ════════════════════════════════════════════════════════════════════
step "Step 30: Final Python Dependency Report"

if [ -f "$SCRIPT_DIR/core/dependency_manager.py" ]; then
    sudo -u "$REAL_USER" "$SCRIPT_DIR/venv/bin/python" \
        -m core.dependency_manager --check 2>/dev/null || true
fi

# ════════════════════════════════════════════════════════════════════
# DONE
# ════════════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}"
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║        JARVIS INSTALLATION COMPLETE!         ║"
echo "  ╚══════════════════════════════════════════════╝"
echo -e "${NC}"
echo ""
echo "  Start JARVIS:"
echo "    1. Type:            jarvis"
echo "    2. Desktop shortcut: Double click Jarvis icon"
echo "    3. Direct:          python3 $SCRIPT_DIR/main.py"
echo ""
echo "  Capture directories:"
echo "    ~/jarvis_captures/wifi"
echo "    ~/jarvis_captures/payloads"
echo "    ~/jarvis_captures/osint"
echo "    ~/jarvis_captures/darkweb"
echo "    ~/jarvis_captures/keylogger"
echo "    ~/jarvis_captures/exploits"
echo ""
echo "  Reports:"
echo "    $SCRIPT_DIR/reports/number_traces/"
echo "    $SCRIPT_DIR/reports/telegram_photos/"
echo ""
echo "  API Keys file:"
echo "    $SCRIPT_DIR/config/api_keys.json"
echo ""
echo "  💡 First launch will run the Number Tracer setup wizard"
echo "     to configure Telegram & other API keys."
echo ""
echo -e "${CYAN}  🤖 Ready, sir.${NC}"
echo ""