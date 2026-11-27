# network_scanner.py
"""
JARVIS Network Scanner
───────────────────────
Scans local network for smart home devices
Generates QR codes for easy device connection
Shows results in a clean GUI window
"""

import os
import sys
import json
import socket
import threading
import platform
import subprocess
import ipaddress
import time
from pathlib import Path

_OS = platform.system()


# ─────────────────────────────────────────────
# DEVICE FINGERPRINTS
# ─────────────────────────────────────────────

DEVICE_SIGNATURES = {
    # Smart Home Hubs
    "home_assistant": {
        "ports":    [8123],
        "keywords": ["home-assistant", "hass.io", "homeassistant"],
        "name":     "Home Assistant",
        "icon":     "🏠",
        "category": "hub",
        "setup_url": "http://{ip}:8123",
    },
    "philips_hue": {
        "ports":    [80, 443],
        "keywords": ["hue", "philips", "meethue"],
        "name":     "Philips Hue Bridge",
        "icon":     "💡",
        "category": "lights",
        "setup_url": "http://{ip}/api",
    },
    "mqtt": {
        "ports":    [1883, 8883, 9001],
        "keywords": [],
        "name":     "MQTT Broker",
        "icon":     "📡",
        "category": "hub",
        "setup_url": "mqtt://{ip}:1883",
    },
    "tuya": {
        "ports":    [6668, 6669],
        "keywords": ["tuya", "smartlife"],
        "name":     "Tuya/Smart Life Device",
        "icon":     "🔌",
        "category": "plug",
        "setup_url": "http://{ip}",
    },
    "tapo": {
        "ports":    [80, 9999],
        "keywords": ["tapo", "tplink", "tp-link"],
        "name":     "TP-Link Tapo Device",
        "icon":     "🔌",
        "category": "plug",
        "setup_url": "http://{ip}",
    },
    "shelly": {
        "ports":    [80],
        "keywords": ["shelly", "shellies"],
        "name":     "Shelly Device",
        "icon":     "⚡",
        "category": "switch",
        "setup_url": "http://{ip}",
    },
    "sonoff": {
        "ports":    [80, 8081],
        "keywords": ["sonoff", "ewelink", "itead"],
        "name":     "Sonoff/eWeLink Device",
        "icon":     "⚡",
        "category": "switch",
        "setup_url": "http://{ip}",
    },
    "xiaomi": {
        "ports":    [54321, 80],
        "keywords": ["xiaomi", "miio", "mi home"],
        "name":     "Xiaomi Mi Home Device",
        "icon":     "🔆",
        "category": "smart",
        "setup_url": "http://{ip}",
    },
    "wled": {
        "ports":    [80],
        "keywords": ["wled", "aircooki"],
        "name":     "WLED LED Controller",
        "icon":     "🌈",
        "category": "lights",
        "setup_url": "http://{ip}",
    },
    "esphome": {
        "ports":    [80, 6053],
        "keywords": ["esphome", "esp32", "esp8266"],
        "name":     "ESPHome Device",
        "icon":     "📟",
        "category": "diy",
        "setup_url": "http://{ip}",
    },
    "router": {
        "ports":    [80, 443, 8080],
        "keywords": ["router", "gateway", "openwrt", "dd-wrt"],
        "name":     "Router/Gateway",
        "icon":     "📶",
        "category": "network",
        "setup_url": "http://{ip}",
    },
    "camera": {
        "ports":    [554, 8080, 8554, 80],
        "keywords": ["camera", "cam", "ipcam", "dahua", "hikvision"],
        "name":     "IP Camera",
        "icon":     "📷",
        "category": "camera",
        "setup_url": "http://{ip}",
    },
    "nas": {
        "ports":    [5000, 5001, 9000, 8080],
        "keywords": ["synology", "qnap", "nas"],
        "name":     "NAS Storage",
        "icon":     "💾",
        "category": "storage",
        "setup_url": "http://{ip}:5000",
    },
    "raspberry_pi": {
        "ports":    [22, 80, 5900],
        "keywords": ["raspberry", "raspbian", "rpi"],
        "name":     "Raspberry Pi",
        "icon":     "🍓",
        "category": "diy",
        "setup_url": "http://{ip}",
    },
    "printer": {
        "ports":    [9100, 631, 80],
        "keywords": ["printer", "print", "hp", "epson", "canon"],
        "name":     "Network Printer",
        "icon":     "🖨️",
        "category": "printer",
        "setup_url": "http://{ip}",
    },
    "generic_http": {
        "ports":    [80, 8080, 443],
        "keywords": [],
        "name":     "HTTP Device",
        "icon":     "🌐",
        "category": "other",
        "setup_url": "http://{ip}",
    },
    "ssh": {
        "ports":    [22],
        "keywords": [],
        "name":     "SSH Device",
        "icon":     "💻",
        "category": "computer",
        "setup_url": "ssh://{ip}",
    },
}


# ─────────────────────────────────────────────
# NETWORK HELPERS
# ─────────────────────────────────────────────

def _get_local_ip() -> str:
    """Get the local machine IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "192.168.1.1"


def _get_network_range() -> str:
    """Get the local network CIDR range."""
    local_ip = _get_local_ip()
    parts    = local_ip.split(".")
    return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"


def _get_hostname(ip: str) -> str:
    """Try to get hostname for an IP."""
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ""


def _get_mac_address(ip: str) -> str:
    """Try to get MAC address from ARP table."""
    try:
        if _OS == "Windows":
            result = subprocess.run(
                ["arp", "-a", ip],
                capture_output=True, text=True, timeout=3
            )
            for line in result.stdout.split("\n"):
                if ip in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        return parts[1]
        else:
            result = subprocess.run(
                ["arp", "-n", ip],
                capture_output=True, text=True, timeout=3
            )
            for line in result.stdout.split("\n"):
                if ip in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        return parts[2]
    except Exception:
        pass
    return ""


def _check_port(ip: str, port: int, timeout: float = 0.5) -> bool:
    """Check if a port is open."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def _http_fingerprint(ip: str, port: int = 80) -> str:
    """Try to get HTTP response to identify device."""
    try:
        import requests
        r = requests.get(
            f"http://{ip}:{port}",
            timeout=2,
            allow_redirects=True
        )
        return r.text[:2000].lower() + " " + str(r.headers).lower()
    except Exception:
        return ""


def _identify_device(ip: str, open_ports: list[int]) -> dict:
    """Identify device type from open ports and HTTP response."""
    http_content = ""

    # Get HTTP content for fingerprinting
    for port in [80, 8080, 8123]:
        if port in open_ports:
            http_content = _http_fingerprint(ip, port)
            if http_content:
                break

    # Check each device signature
    best_match  = None
    best_score  = 0

    for device_type, sig in DEVICE_SIGNATURES.items():
        score = 0

        # Port matching
        matching_ports = [p for p in sig["ports"] if p in open_ports]
        score += len(matching_ports) * 2

        # Keyword matching in HTTP content
        for kw in sig["keywords"]:
            if kw in http_content:
                score += 5

        if score > best_score:
            best_score  = score
            best_match  = device_type

    if best_match and best_score > 0:
        sig = DEVICE_SIGNATURES[best_match]
        return {
            "device_type": best_match,
            "name":        sig["name"],
            "icon":        sig["icon"],
            "category":    sig["category"],
            "setup_url":   sig["setup_url"].format(ip=ip),
        }

    # Generic device
    if open_ports:
        return {
            "device_type": "unknown",
            "name":        "Unknown Device",
            "icon":        "❓",
            "category":    "other",
            "setup_url":   f"http://{ip}",
        }

    return None


# ─────────────────────────────────────────────
# SCANNER
# ─────────────────────────────────────────────

def scan_network(
    network: str = None,
    timeout: float = 0.5,
    ports: list[int] = None,
    on_device_found=None,
    player=None,
) -> list[dict]:
    """
    Scan network for all devices.

    Args:
        network:         CIDR range e.g. '192.168.1.0/24'
        timeout:         Port timeout in seconds
        ports:           Ports to scan (default: common smart home ports)
        on_device_found: Callback when device found
        player:          UI player for logging

    Returns:
        List of found devices with full info
    """
    if not network:
        network = _get_network_range()

    if not ports:
        ports = [
            22,    # SSH
            80,    # HTTP
            443,   # HTTPS
            554,   # RTSP (cameras)
            1883,  # MQTT
            5000,  # Synology NAS
            5900,  # VNC
            6053,  # ESPHome
            6668,  # Tuya
            8080,  # HTTP alt
            8123,  # Home Assistant
            8554,  # RTSP alt
            8883,  # MQTT SSL
            9001,  # MQTT WebSocket
            9100,  # Printer
            9999,  # Tapo
            54321, # Xiaomi
        ]

    print(f"[Scanner] 🔍 Scanning {network}...")
    if player:
        player.write_log(f"[Scanner] Scanning {network}")

    local_ip = _get_local_ip()
    network_obj = ipaddress.IPv4Network(network, strict=False)
    all_ips  = [str(ip) for ip in network_obj.hosts()]

    found   = []
    lock    = threading.Lock()
    threads = []
    done    = [0]
    total   = len(all_ips)

    def scan_host(ip: str):
        # Skip our own IP
        if ip == local_ip:
            done[0] += 1
            return

        open_ports = []

        # Quick ping first
        try:
            if _OS == "Windows":
                ping_result = subprocess.run(
                    ["ping", "-n", "1", "-w", "500", ip],
                    capture_output=True, timeout=2
                )
                is_up = ping_result.returncode == 0
            else:
                ping_result = subprocess.run(
                    ["ping", "-c", "1", "-W", "1", ip],
                    capture_output=True, timeout=2
                )
                is_up = ping_result.returncode == 0
        except Exception:
            is_up = False

        # Check ports even if ping fails (some devices block ping)
        for port in ports:
            if _check_port(ip, port, timeout):
                open_ports.append(port)
                is_up = True

        if is_up or open_ports:
            # Get device info
            hostname = _get_hostname(ip)
            mac      = _get_mac_address(ip)
            device   = _identify_device(ip, open_ports)

            result = {
                "ip":         ip,
                "hostname":   hostname,
                "mac":        mac,
                "open_ports": open_ports,
                "is_up":      is_up,
                "device":     device,
                "scanned_at": time.strftime("%H:%M:%S"),
            }

            with lock:
                found.append(result)

            if on_device_found:
                on_device_found(result)

            device_name = device["name"] if device else "Device"
            icon        = device["icon"] if device else "📱"
            print(f"[Scanner] {icon} Found: {ip} — {device_name}")
            if player:
                player.write_log(f"[Scanner] {icon} {ip} — {device_name}")

        done[0] += 1

    # Launch threads
    for ip in all_ips:
        t = threading.Thread(target=scan_host, args=(ip,), daemon=True)
        threads.append(t)
        t.start()

        # Limit concurrent threads
        if len([t for t in threads if t.is_alive()]) > 100:
            time.sleep(0.01)

    # Wait for all to complete
    for t in threads:
        t.join(timeout=timeout + 2)

    # Sort by IP
    found.sort(key=lambda x: [int(p) for p in x["ip"].split(".")])

    print(f"[Scanner] ✅ Scan complete. Found {len(found)} devices.")
    return found


# ─────────────────────────────────────────────
# QR CODE GENERATOR
# ─────────────────────────────────────────────

def generate_qr(
    data: str,
    title: str = "",
    save_path: Path = None,
) -> Path:
    """
    Generate a QR code image.

    Args:
        data:      URL or text to encode
        title:     Label for the QR code
        save_path: Where to save the image

    Returns:
        Path to saved QR code image
    """
    try:
        import qrcode
        from PIL import Image, ImageDraw, ImageFont

        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)

        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_img = qr_img.convert("RGB")

        # Add title banner if provided
        if title:
            try:
                # Create banner
                banner_height = 60
                total_height  = qr_img.height + banner_height
                final_img     = Image.new("RGB", (qr_img.width, total_height), "white")

                # Draw banner background
                draw = ImageDraw.Draw(final_img)
                draw.rectangle(
                    [(0, 0), (qr_img.width, banner_height)],
                    fill="#1a1a2e"
                )

                # Add title text
                try:
                    font = ImageFont.truetype(
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                        18
                    )
                except Exception:
                    font = ImageFont.load_default()

                # Center text
                text_bbox = draw.textbbox((0, 0), title, font=font)
                text_w    = text_bbox[2] - text_bbox[0]
                text_x    = (qr_img.width - text_w) // 2
                draw.text((text_x, 15), title, fill="white", font=font)

                # Add URL below title
                try:
                    small_font = ImageFont.truetype(
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                        11
                    )
                except Exception:
                    small_font = font

                url_text  = data[:50] + "..." if len(data) > 50 else data
                url_bbox  = draw.textbbox((0, 0), url_text, font=small_font)
                url_w     = url_bbox[2] - url_bbox[0]
                url_x     = (qr_img.width - url_w) // 2
                draw.text((url_x, 38), url_text, fill="#aaaaaa", font=small_font)

                # Paste QR code below banner
                final_img.paste(qr_img, (0, banner_height))
                qr_img = final_img

            except Exception as e:
                print(f"[QR] Banner error: {e}")

        # Save
        if not save_path:
            save_path = Path.home() / "Desktop" / f"jarvis_qr_{int(time.time())}.png"

        save_path.parent.mkdir(parents=True, exist_ok=True)
        qr_img.save(str(save_path))
        return save_path

    except ImportError:
        raise ImportError(
            "qrcode or Pillow not installed. "
            "Run: pip install qrcode[pil]"
        )


def generate_device_qr(device: dict) -> Path:
    """Generate a QR code for a specific device."""
    ip       = device["ip"]
    dev_info = device.get("device", {}) or {}
    name     = dev_info.get("name", "Device")
    url      = dev_info.get("setup_url", f"http://{ip}")
    icon     = dev_info.get("icon", "📱")

    title = f"{icon} {name} ({ip})"
    path  = Path.home() / "Desktop" / f"qr_{ip.replace('.', '_')}.png"

    return generate_qr(url, title=title, save_path=path)


# ─────────────────────────────────────────────
# SCAN RESULTS GUI
# ─────────────────────────────────────────────

def show_scan_results(devices: list[dict], speak=None):
    """
    Show scan results in a beautiful GUI window
    with QR codes and device info.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
        from PIL import Image, ImageTk

        root = tk.Tk()
        root.title("🏠 JARVIS — Smart Home Device Scanner")
        root.geometry("1000x700")
        root.configure(bg="#0a0a1a")
        root.attributes("-topmost", True)

        # ── Header ──────────────────────────────
        header = tk.Frame(root, bg="#1a1a2e", pady=15)
        header.pack(fill="x")

        tk.Label(
            header,
            text="🏠 Smart Home Device Scanner",
            font=("Arial", 20, "bold"),
            fg="#00d4ff",
            bg="#1a1a2e"
        ).pack()

        local_ip = _get_local_ip()
        tk.Label(
            header,
            text=f"Your IP: {local_ip}  |  Found {len(devices)} devices",
            font=("Arial", 11),
            fg="#888888",
            bg="#1a1a2e"
        ).pack()

        # ── Main area ────────────────────────────
        main_frame = tk.Frame(root, bg="#0a0a1a")
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Left panel - device list
        left = tk.Frame(main_frame, bg="#0a0a1a", width=400)
        left.pack(side="left", fill="both", expand=True)

        tk.Label(
            left,
            text="📡 Discovered Devices",
            font=("Arial", 13, "bold"),
            fg="#ffffff",
            bg="#0a0a1a"
        ).pack(anchor="w", pady=(0, 5))

        # Scrollable device list
        canvas   = tk.Canvas(left, bg="#0a0a1a", highlightthickness=0)
        scrollbar = ttk.Scrollbar(left, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg="#0a0a1a")

        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Right panel - QR code
        right = tk.Frame(main_frame, bg="#0a0a1a", width=350)
        right.pack(side="right", fill="both", padx=(10, 0))

        tk.Label(
            right,
            text="📱 QR Code",
            font=("Arial", 13, "bold"),
            fg="#ffffff",
            bg="#0a0a1a"
        ).pack(anchor="w", pady=(0, 5))

        qr_label = tk.Label(right, bg="#0a0a1a")
        qr_label.pack(pady=10)

        qr_info = tk.Label(
            right,
            text="Click a device to generate QR code",
            font=("Arial", 10),
            fg="#888888",
            bg="#0a0a1a",
            wraplength=300
        )
        qr_info.pack()

        # Device URL label
        url_label = tk.Label(
            right,
            text="",
            font=("Arial", 10),
            fg="#00d4ff",
            bg="#0a0a1a",
            wraplength=300,
            cursor="hand2"
        )
        url_label.pack(pady=5)

        # Add to Jarvis button
        add_btn = tk.Button(
            right,
            text="➕ Add to Jarvis",
            font=("Arial", 11, "bold"),
            bg="#00d4ff",
            fg="#000000",
            relief="flat",
            padx=20,
            pady=8,
        )
        add_btn.pack(pady=10)

        save_qr_btn = tk.Button(
            right,
            text="💾 Save QR Code",
            font=("Arial", 10),
            bg="#1a1a2e",
            fg="#ffffff",
            relief="flat",
            padx=15,
            pady=6,
        )
        save_qr_btn.pack()

        current_device = [None]
        current_qr_path = [None]

        def select_device(device):
            """Handle device selection."""
            current_device[0] = device
            dev_info = device.get("device") or {}
            ip       = device["ip"]
            name     = dev_info.get("name", "Unknown Device")
            url      = dev_info.get("setup_url", f"http://{ip}")
            icon     = dev_info.get("icon", "📱")

            # Update URL label
            url_label.config(text=url)

            # Generate QR code
            try:
                qr_path = generate_device_qr(device)
                current_qr_path[0] = qr_path

                # Display QR code
                img    = Image.open(str(qr_path))
                img    = img.resize((280, 320), Image.LANCZOS)
                photo  = ImageTk.PhotoImage(img)
                qr_label.config(image=photo)
                qr_label.image = photo

                qr_info.config(
                    text=f"{icon} {name}\nIP: {ip}\nScan to open device",
                    fg="#ffffff"
                )

            except Exception as e:
                qr_info.config(
                    text=f"QR Error: {e}",
                    fg="#ff4444"
                )

            # Update add button
            def add_device():
                _add_device_to_jarvis(device, speak)
                add_btn.config(text="✅ Added!", bg="#00ff88")
                root.after(2000, lambda: add_btn.config(
                    text="➕ Add to Jarvis", bg="#00d4ff"
                ))

            add_btn.config(command=add_device)

            def save_qr():
                if current_qr_path[0]:
                    import shutil
                    dest = Path.home() / "Desktop" / f"jarvis_qr_{ip.replace('.', '_')}.png"
                    shutil.copy(str(current_qr_path[0]), str(dest))
                    save_qr_btn.config(text="✅ Saved!")
                    root.after(2000, lambda: save_qr_btn.config(text="💾 Save QR Code"))

            save_qr_btn.config(command=save_qr)

        # Category colors
        category_colors = {
            "hub":      "#00d4ff",
            "lights":   "#ffdd00",
            "plug":     "#ff8800",
            "switch":   "#ff8800",
            "camera":   "#ff4444",
            "network":  "#888888",
            "storage":  "#8888ff",
            "diy":      "#00ff88",
            "computer": "#aaaaaa",
            "printer":  "#cccccc",
            "smart":    "#ff88ff",
            "other":    "#555555",
        }

        # Populate device list
        for i, device in enumerate(devices):
            dev_info = device.get("device") or {}
            ip       = device["ip"]
            hostname = device.get("hostname", "")
            ports    = device.get("open_ports", [])
            name     = dev_info.get("name", "Unknown Device")
            icon     = dev_info.get("icon", "❓")
            category = dev_info.get("category", "other")
            color    = category_colors.get(category, "#555555")

            # Device card
            card = tk.Frame(
                scroll_frame,
                bg="#1a1a2e",
                relief="flat",
                padx=10,
                pady=8,
                cursor="hand2",
            )
            card.pack(fill="x", pady=3, padx=5)

            # Color indicator
            tk.Frame(card, bg=color, width=4).pack(side="left", fill="y")

            # Device info
            info_frame = tk.Frame(card, bg="#1a1a2e")
            info_frame.pack(side="left", fill="both", expand=True, padx=(8, 0))

            tk.Label(
                info_frame,
                text=f"{icon}  {name}",
                font=("Arial", 11, "bold"),
                fg="#ffffff",
                bg="#1a1a2e",
                anchor="w",
            ).pack(fill="x")

            detail = ip
            if hostname:
                detail += f"  ({hostname})"
            tk.Label(
                info_frame,
                text=detail,
                font=("Arial", 9),
                fg="#00d4ff",
                bg="#1a1a2e",
                anchor="w",
            ).pack(fill="x")

            if ports:
                ports_str = "Ports: " + ", ".join(str(p) for p in ports[:5])
                if len(ports) > 5:
                    ports_str += f" +{len(ports)-5}"
                tk.Label(
                    info_frame,
                    text=ports_str,
                    font=("Arial", 8),
                    fg="#555555",
                    bg="#1a1a2e",
                    anchor="w",
                ).pack(fill="x")

            # QR button
            qr_btn = tk.Label(
                card,
                text="📱",
                font=("Arial", 18),
                bg="#1a1a2e",
                cursor="hand2",
            )
            qr_btn.pack(side="right", padx=5)

            # Bind clicks
            def make_handler(d):
                return lambda e: select_device(d)

            for widget in [card, info_frame, qr_btn]:
                widget.bind("<Button-1>", make_handler(device))
            for child in info_frame.winfo_children():
                child.bind("<Button-1>", make_handler(device))

            # Hover effect
            def on_enter(e, c=card):
                c.config(bg="#2a2a3e")
                for w in c.winfo_children():
                    try:
                        w.config(bg="#2a2a3e")
                    except Exception:
                        pass

            def on_leave(e, c=card):
                c.config(bg="#1a1a2e")
                for w in c.winfo_children():
                    try:
                        w.config(bg="#1a1a2e")
                    except Exception:
                        pass

            card.bind("<Enter>", on_enter)
            card.bind("<Leave>", on_leave)

        # ── Bottom bar ───────────────────────────
        bottom = tk.Frame(root, bg="#1a1a2e", pady=10)
        bottom.pack(fill="x", side="bottom")

        tk.Button(
            bottom,
            text="🔄 Rescan Network",
            font=("Arial", 10),
            bg="#333355",
            fg="#ffffff",
            relief="flat",
            padx=15,
            pady=6,
            command=lambda: [root.destroy(), show_scan_gui(speak=speak)]
        ).pack(side="left", padx=10)

        tk.Button(
            bottom,
            text="📋 Generate All QR Codes",
            font=("Arial", 10),
            bg="#333355",
            fg="#ffffff",
            relief="flat",
            padx=15,
            pady=6,
            command=lambda: _generate_all_qr(devices)
        ).pack(side="left", padx=5)

        tk.Button(
            bottom,
            text="❌ Close",
            font=("Arial", 10),
            bg="#551a1a",
            fg="#ffffff",
            relief="flat",
            padx=15,
            pady=6,
            command=root.destroy
        ).pack(side="right", padx=10)

        # Auto-select first smart home device
        smart_devices = [
            d for d in devices
            if d.get("device", {}) and
            d["device"].get("category") in ("hub", "lights", "plug", "switch")
        ]
        if smart_devices:
            root.after(100, lambda: select_device(smart_devices[0]))
        elif devices:
            root.after(100, lambda: select_device(devices[0]))

        root.mainloop()

    except ImportError as e:
        print(f"[Scanner] GUI not available: {e}")
        # Fall back to terminal output
        _print_scan_results(devices)


def _print_scan_results(devices: list[dict]):
    """Print scan results to terminal."""
    print("\n" + "═" * 60)
    print("🏠 SMART HOME DEVICE SCAN RESULTS")
    print("═" * 60)
    for d in devices:
        dev  = d.get("device") or {}
        icon = dev.get("icon", "❓")
        name = dev.get("name", "Unknown")
        ip   = d["ip"]
        host = d.get("hostname", "")
        url  = dev.get("setup_url", f"http://{ip}")
        print(f"\n{icon} {name}")
        print(f"   IP:  {ip}" + (f" ({host})" if host else ""))
        print(f"   URL: {url}")
        if d.get("open_ports"):
            print(f"   Ports: {', '.join(str(p) for p in d['open_ports'])}")
    print("\n" + "═" * 60)


def _add_device_to_jarvis(device: dict, speak=None):
    """Add a discovered device to Jarvis smart home config."""
    from pathlib import Path
    import json

    def _get_base_dir():
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent
        return Path(__file__).resolve().parent.parent

    config_path = _get_base_dir() / "config" / "smart_home.json"

    try:
        if config_path.exists():
            with open(config_path, "r") as f:
                config = json.load(f)
        else:
            config = {}

        ip      = device["ip"]
        dev     = device.get("device") or {}
        dev_type = dev.get("device_type", "unknown")
        name    = dev.get("name", "Device")

        if "discovered_devices" not in config:
            config["discovered_devices"] = {}

        config["discovered_devices"][ip] = {
            "ip":       ip,
            "name":     name,
            "type":     dev_type,
            "url":      dev.get("setup_url", f"http://{ip}"),
            "hostname": device.get("hostname", ""),
            "ports":    device.get("open_ports", []),
            "added_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

        print(f"[Scanner] ✅ Added {name} ({ip}) to Jarvis config")

        if speak:
            speak(f"{name} at {ip} has been added to Jarvis, sir.")

    except Exception as e:
        print(f"[Scanner] Error adding device: {e}")


def _generate_all_qr(devices: list[dict]):
    """Generate QR codes for all devices."""
    desktop = Path.home() / "Desktop" / "jarvis_qr_codes"
    desktop.mkdir(exist_ok=True)

    count = 0
    for device in devices:
        try:
            dev  = device.get("device") or {}
            ip   = device["ip"]
            url  = dev.get("setup_url", f"http://{ip}")
            name = dev.get("name", f"Device {ip}")
            path = desktop / f"qr_{ip.replace('.', '_')}.png"
            generate_qr(url, title=name, save_path=path)
            count += 1
        except Exception:
            pass

    print(f"[Scanner] ✅ Generated {count} QR codes in: {desktop}")

    # Open the folder
    try:
        if _OS == "Linux":
            subprocess.Popen(["xdg-open", str(desktop)])
        elif _OS == "Darwin":
            subprocess.Popen(["open", str(desktop)])
        else:
            subprocess.Popen(["explorer", str(desktop)])
    except Exception:
        pass


# ─────────────────────────────────────────────
# MAIN SCAN FUNCTION
# ─────────────────────────────────────────────

def show_scan_gui(network: str = None, speak=None, player=None):
    """
    Run a full network scan and show results in GUI.
    """
    local_ip = _get_local_ip()
    network  = network or _get_network_range()

    print(f"[Scanner] 🌐 Your IP: {local_ip}")
    print(f"[Scanner] 🔍 Scanning: {network}")

    if speak:
        speak(
            "Scanning your network for smart home devices, sir. "
            "This will take about 30 seconds."
        )

    # Run scan in background thread
    devices    = []
    scan_done  = threading.Event()

    def run_scan():
        nonlocal devices
        devices = scan_network(
            network=network,
            player=player,
        )
        scan_done.set()

    scan_thread = threading.Thread(target=run_scan, daemon=True)
    scan_thread.start()
    scan_done.wait(timeout=60)

    if not devices:
        msg = "No devices found on network, sir."
        if speak:
            speak(msg)
        return msg

    smart_count = sum(
        1 for d in devices
        if d.get("device", {}) and
        d["device"].get("category") in ("hub", "lights", "plug", "switch", "smart")
    )

    if speak:
        speak(
            f"Scan complete, sir. Found {len(devices)} devices on your network, "
            f"including {smart_count} smart home devices. "
            "Opening the results window now."
        )

    # Show GUI
    show_scan_results(devices, speak=speak)

    return (
        f"Scan complete. Found {len(devices)} devices "
        f"({smart_count} smart home devices)."
    )