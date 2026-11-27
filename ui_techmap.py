"""
J.A.R.V.I.S  —  TECH MAP
Interactive multi-layer network/security/trading visualization
"""
from __future__ import annotations

import math
import random
import subprocess
import threading
import time
import json
import re
from pathlib import Path
from dataclasses import dataclass, field

from PyQt6.QtCore import (
    Qt, QTimer, QPointF, QRectF, pyqtSignal, QObject, QThread,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient, QLinearGradient, QConicalGradient,
    QWheelEvent, QMouseEvent, QCursor,
)
from PyQt6.QtWidgets import QWidget, QApplication


# ── Import shared palette & helpers from main UI ──────────────────────────
from ui import C, qc, qcol, _HexGrid, _ArcReactor, _metrics


# ══════════════════════════════════════════════════════════════════════════
#  DATA MODELS
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class NetworkDevice:
    """A device discovered on the local network."""
    ip: str = ""
    mac: str = ""
    hostname: str = ""
    vendor: str = ""
    signal_strength: int = 0        # 0-100, 0 = unknown
    device_type: str = "unknown"    # router, phone, pc, iot, unknown
    is_self: bool = False
    is_gateway: bool = False
    is_unknown: bool = False        # flagged as suspicious
    ports: list[int] = field(default_factory=list)
    last_seen: float = 0.0

@dataclass
class BluetoothDevice:
    """A Bluetooth device in range."""
    mac: str = ""
    name: str = ""
    device_type: str = "unknown"    # audio, phone, keyboard, mouse, unknown
    rssi: int = -100                # signal strength in dBm
    connected: bool = False
    paired: bool = False
    last_seen: float = 0.0

@dataclass
class GeoConnection:
    """A geographic connection from netstat/ss."""
    local_ip: str = ""
    local_port: int = 0
    remote_ip: str = ""
    remote_port: int = 0
    state: str = ""
    process: str = ""
    country: str = ""
    city: str = ""
    lat: float = 0.0
    lon: float = 0.0
    is_vpn: bool = False

@dataclass 
class SecurityAlert:
    """A security finding."""
    level: str = "info"             # info, warning, critical
    source: str = ""
    message: str = ""
    device_ip: str = ""
    timestamp: float = 0.0

@dataclass
class TradingNode:
    """A trading infrastructure node."""
    name: str = ""
    host: str = ""
    ping_ms: float = -1.0
    country: str = ""
    status: str = "unknown"         # online, offline, slow
    node_type: str = "broker"       # broker, exchange, data_feed


# ══════════════════════════════════════════════════════════════════════════
#  DATA SCANNERS (Background Threads)
# ══════════════════════════════════════════════════════════════════════════

class NetworkScanner(QObject):
    """Scans local network for devices using arp-scan / nmap."""
    devices_updated = pyqtSignal(list)  # list[NetworkDevice]

    def __init__(self):
        super().__init__()
        self._devices: list[NetworkDevice] = []
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _scan_loop(self):
        while self._running:
            try:
                devices = self._do_scan()
                self._devices = devices
                self.devices_updated.emit(devices)
            except Exception as e:
                print(f"[TechMap] Network scan error: {e}")
            time.sleep(30)  # rescan every 30s

    def _do_scan(self) -> list[NetworkDevice]:
        """Perform actual network scan."""
        devices = []

        # Get gateway
        gateway_ip = self._get_gateway()
        my_ip = self._get_my_ip()

        # Try arp-scan first (fastest, needs root on Linux)
        try:
            r = subprocess.run(
                ["arp-scan", "--localnet", "--plain"],
                capture_output=True, text=True, timeout=15
            )
            if r.returncode == 0:
                for line in r.stdout.strip().splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        ip, mac = parts[0].strip(), parts[1].strip()
                        vendor = parts[2].strip() if len(parts) > 2 else ""
                        dev = NetworkDevice(
                            ip=ip, mac=mac, vendor=vendor,
                            last_seen=time.time(),
                            is_self=(ip == my_ip),
                            is_gateway=(ip == gateway_ip),
                            device_type=self._guess_type(vendor, ip == gateway_ip),
                        )
                        devices.append(dev)
        except FileNotFoundError:
            pass
        except Exception:
            pass

        # Fallback: parse ARP table
        if not devices:
            try:
                r = subprocess.run(
                    ["arp", "-a"],
                    capture_output=True, text=True, timeout=10
                )
                for line in r.stdout.splitlines():
                    # Parse different arp -a formats
                    ip_match = re.search(r'\((\d+\.\d+\.\d+\.\d+)\)', line)
                    mac_match = re.search(
                        r'([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}', line
                    )
                    if ip_match and mac_match:
                        ip = ip_match.group(1)
                        mac = mac_match.group(0)
                        dev = NetworkDevice(
                            ip=ip, mac=mac,
                            last_seen=time.time(),
                            is_self=(ip == my_ip),
                            is_gateway=(ip == gateway_ip),
                            device_type=self._guess_type("", ip == gateway_ip),
                        )
                        devices.append(dev)
            except Exception:
                pass

        # Add self if not found
        if my_ip and not any(d.ip == my_ip for d in devices):
            import socket
            devices.insert(0, NetworkDevice(
                ip=my_ip,
                mac=self._get_my_mac(),
                hostname=socket.gethostname(),
                is_self=True,
                device_type="pc",
                last_seen=time.time(),
            ))

        # Flag unknowns (no vendor, unusual MAC)
        for d in devices:
            if not d.vendor and not d.is_self and not d.is_gateway:
                d.is_unknown = True

        return devices

    def _get_gateway(self) -> str:
        try:
            r = subprocess.run(
                ["ip", "route", "show", "default"],
                capture_output=True, text=True, timeout=5
            )
            m = re.search(r'default via (\S+)', r.stdout)
            if m:
                return m.group(1)
        except Exception:
            pass
        try:
            r = subprocess.run(
                ["route", "-n", "get", "default"],
                capture_output=True, text=True, timeout=5
            )
            m = re.search(r'gateway:\s*(\S+)', r.stdout)
            if m:
                return m.group(1)
        except Exception:
            pass
        return ""

    def _get_my_ip(self) -> str:
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _get_my_mac(self) -> str:
        try:
            r = subprocess.run(
                ["ip", "link", "show"],
                capture_output=True, text=True, timeout=5
            )
            m = re.search(
                r'link/ether\s+([0-9a-fA-F:]{17})', r.stdout
            )
            if m:
                return m.group(1)
        except Exception:
            pass
        return "00:00:00:00:00:00"

    def _guess_type(self, vendor: str, is_gw: bool) -> str:
        if is_gw:
            return "router"
        v = vendor.lower()
        if any(k in v for k in ["apple", "iphone", "samsung", "huawei",
                                  "xiaomi", "oneplus", "pixel"]):
            return "phone"
        if any(k in v for k in ["intel", "dell", "hp", "lenovo", "asus",
                                  "acer", "microsoft"]):
            return "pc"
        if any(k in v for k in ["espressif", "tuya", "shelly", "sonoff",
                                  "tp-link", "tapo", "nest", "ring",
                                  "philips", "hue"]):
            return "iot"
        if any(k in v for k in ["sony", "lg", "vizio", "roku", "fire"]):
            return "tv"
        return "unknown"


class BluetoothScanner(QObject):
    """Scans for Bluetooth devices."""
    devices_updated = pyqtSignal(list)  # list[BluetoothDevice]

    def __init__(self):
        super().__init__()
        self._devices: list[BluetoothDevice] = []
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._scan_loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _scan_loop(self):
        while self._running:
            try:
                devices = self._do_scan()
                self._devices = devices
                self.devices_updated.emit(devices)
            except Exception as e:
                print(f"[TechMap] BT scan error: {e}")
            time.sleep(20)

    def _do_scan(self) -> list[BluetoothDevice]:
        devices = []

        # Get paired devices
        paired_macs = set()
        try:
            r = subprocess.run(
                ["bluetoothctl", "devices", "Paired"],
                capture_output=True, text=True, timeout=5
            )
            for line in r.stdout.splitlines():
                m = re.search(
                    r'Device\s+([0-9A-F:]{17})\s+(.*)', line
                )
                if m:
                    paired_macs.add(m.group(1))
        except Exception:
            pass

        # Get connected devices
        connected_macs = set()
        try:
            r = subprocess.run(
                ["bluetoothctl", "devices", "Connected"],
                capture_output=True, text=True, timeout=5
            )
            for line in r.stdout.splitlines():
                m = re.search(r'Device\s+([0-9A-F:]{17})', line)
                if m:
                    connected_macs.add(m.group(1))
        except Exception:
            pass

        # Scan for nearby devices
        try:
            # Start scan briefly
            subprocess.run(
                ["bluetoothctl", "scan", "on"],
                capture_output=True, timeout=2
            )
            time.sleep(8)
            subprocess.run(
                ["bluetoothctl", "scan", "off"],
                capture_output=True, timeout=2
            )

            # List all known devices
            r = subprocess.run(
                ["bluetoothctl", "devices"],
                capture_output=True, text=True, timeout=5
            )
            for line in r.stdout.splitlines():
                m = re.search(
                    r'Device\s+([0-9A-F:]{17})\s+(.*)', line
                )
                if m:
                    mac = m.group(1)
                    name = m.group(2).strip()
                    dev = BluetoothDevice(
                        mac=mac,
                        name=name if name != mac else "Unknown",
                        connected=mac in connected_macs,
                        paired=mac in paired_macs,
                        rssi=self._get_rssi(mac),
                        device_type=self._guess_bt_type(name),
                        last_seen=time.time(),
                    )
                    devices.append(dev)
        except Exception:
            pass

        return devices

    def _get_rssi(self, mac: str) -> int:
        try:
            r = subprocess.run(
                ["bluetoothctl", "info", mac],
                capture_output=True, text=True, timeout=3
            )
            m = re.search(r'RSSI:\s*(-?\d+)', r.stdout)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        return -80  # default

    def _guess_bt_type(self, name: str) -> str:
        n = name.lower()
        if any(k in n for k in ["airpod", "buds", "headphone", "speaker",
                                  "jbl", "sony", "bose", "earphone",
                                  "headset", "audio"]):
            return "audio"
        if any(k in n for k in ["keyboard", "keeb", "k380", "mx keys"]):
            return "keyboard"
        if any(k in n for k in ["mouse", "mx master", "trackpad"]):
            return "mouse"
        if any(k in n for k in ["phone", "iphone", "galaxy", "pixel"]):
            return "phone"
        if any(k in n for k in ["watch", "band", "fitbit", "garmin"]):
            return "watch"
        if any(k in n for k in ["controller", "gamepad", "xbox", "ps5",
                                  "dualsense"]):
            return "gamepad"
        return "unknown"


class GeoScanner(QObject):
    """Scans active connections and geolocates remote IPs."""
    connections_updated = pyqtSignal(list)  # list[GeoConnection]

    def __init__(self):
        super().__init__()
        self._connections: list[GeoConnection] = []
        self._running = False
        self._geo_cache: dict[str, dict] = {}

    def start(self):
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._scan_loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _scan_loop(self):
        while self._running:
            try:
                conns = self._do_scan()
                self._connections = conns
                self.connections_updated.emit(conns)
            except Exception as e:
                print(f"[TechMap] Geo scan error: {e}")
            time.sleep(15)

    def _do_scan(self) -> list[GeoConnection]:
        connections = []

        try:
            r = subprocess.run(
                ["ss", "-tunp"],
                capture_output=True, text=True, timeout=10
            )
            for line in r.stdout.splitlines()[1:]:  # skip header
                parts = line.split()
                if len(parts) < 5:
                    continue

                state = parts[1]
                local = parts[4]
                remote = parts[5] if len(parts) > 5 else ""
                process = parts[-1] if "users:" in line else ""

                # Parse remote IP:port
                if remote and ":" in remote:
                    # Handle IPv6
                    if remote.startswith("["):
                        m = re.match(
                            r'\[([^\]]+)\]:(\d+)', remote
                        )
                        if m:
                            rip, rport = m.group(1), int(m.group(2))
                        else:
                            continue
                    else:
                        rparts = remote.rsplit(":", 1)
                        rip = rparts[0]
                        rport = int(rparts[1]) if len(rparts) > 1 else 0

                    # Skip local/private IPs
                    if rip.startswith(("127.", "10.", "192.168.",
                                       "172.16.", "172.17.", "172.18.",
                                       "0.0.0", "::", "fe80")):
                        continue

                    # Geolocate
                    geo = self._geolocate(rip)

                    # Parse process name
                    proc_name = ""
                    pm = re.search(r'"([^"]+)"', process)
                    if pm:
                        proc_name = pm.group(1)

                    conn = GeoConnection(
                        local_ip=local.rsplit(":", 1)[0],
                        local_port=int(
                            local.rsplit(":", 1)[1]
                        ) if ":" in local else 0,
                        remote_ip=rip,
                        remote_port=rport,
                        state=state,
                        process=proc_name,
                        country=geo.get("country", ""),
                        city=geo.get("city", ""),
                        lat=geo.get("lat", 0.0),
                        lon=geo.get("lon", 0.0),
                        is_vpn=geo.get("is_vpn", False),
                    )
                    connections.append(conn)

        except Exception:
            pass

        return connections

    def _geolocate(self, ip: str) -> dict:
        """Geolocate an IP using ip-api.com (free, no key needed)."""
        if ip in self._geo_cache:
            return self._geo_cache[ip]

        try:
            import urllib.request
            url = f"http://ip-api.com/json/{ip}?fields=status,country,city,lat,lon,proxy,hosting"
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "JARVIS/3.0")

            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())

            if data.get("status") == "success":
                result = {
                    "country": data.get("country", ""),
                    "city": data.get("city", ""),
                    "lat": data.get("lat", 0.0),
                    "lon": data.get("lon", 0.0),
                    "is_vpn": data.get("proxy", False)
                               or data.get("hosting", False),
                }
                self._geo_cache[ip] = result
                return result
        except Exception:
            pass

        return {"country": "", "city": "", "lat": 0, "lon": 0,
                "is_vpn": False}


# ══════════════════════════════════════════════════════════════════════════
#  TECH MAP WIDGET (The Main Canvas)
# ══════════════════════════════════════════════════════════════════════════

class TechMapWidget(QWidget):
    """
    Multi-layer interactive tech map with Iron Man HUD aesthetics.
    Renders all 5 layers with animations, zoom, and pan.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(800, 600)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

        # ── View transform ─────────────────────────
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._dragging = False
        self._drag_start = QPointF()
        self._pan_start_x = 0.0
        self._pan_start_y = 0.0

        # ── Animation state ────────────────────────
        self._tick = 0
        self._pulse = 0.0
        self._scan_angle = 0.0
        self._reactor = _ArcReactor()
        self._particles: list[list] = []

        # ── Layer visibility ───────────────────────
        self._layers = {
            "network":   True,
            "bluetooth":  True,
            "geographic": True,
            "security":   True,
            "trading":    False,
        }

        # ── Layer data ─────────────────────────────
        self._net_devices: list[NetworkDevice] = []
        self._bt_devices: list[BluetoothDevice] = []
        self._geo_connections: list[GeoConnection] = []
        self._security_alerts: list[SecurityAlert] = []
        self._trading_nodes: list[TradingNode] = []

        # ── Hover / selection ──────────────────────
        self._hover_device: NetworkDevice | BluetoothDevice | None = None
        self._selected_device: NetworkDevice | BluetoothDevice | None = None
        self._hover_pos = QPointF()
        self._device_positions: list[tuple[QPointF, object]] = []

        # ── Hex grid ───────────────────────────────
        self._grid = _HexGrid(2000, 2000, 38)

        # ── Scanners ──────────────────────────────
        self._net_scanner = NetworkScanner()
        self._bt_scanner = BluetoothScanner()
        self._geo_scanner = GeoScanner()

        self._net_scanner.devices_updated.connect(self._on_net_update)
        self._bt_scanner.devices_updated.connect(self._on_bt_update)
        self._geo_scanner.connections_updated.connect(self._on_geo_update)

        # ── Animation timer ────────────────────────
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(16)

        # ── Start scanning ─────────────────────────
        self._net_scanner.start()
        self._bt_scanner.start()
        self._geo_scanner.start()

    # ── Scanner callbacks ──────────────────────────────────────────────────

    def _on_net_update(self, devices: list):
        self._net_devices = devices
        self.update()

    def _on_bt_update(self, devices: list):
        self._bt_devices = devices
        self.update()

    def _on_geo_update(self, connections: list):
        self._geo_connections = connections
        self.update()

    def toggle_layer(self, layer: str):
        if layer in self._layers:
            self._layers[layer] = not self._layers[layer]
            self.update()

    # ── Animation ──────────────────────────────────────────────────────────

    def _animate(self):
        self._tick += 1
        self._pulse = (self._pulse + 0.03) % (2 * math.pi)
        self._scan_angle = (self._scan_angle + 0.8) % 360
        self._reactor.step()

        # Spawn particles from center
        if random.random() < 0.08:
            W, H = self.width(), self.height()
            cx = W / 2 + self._pan_x
            cy = H / 2 + self._pan_y
            ang = random.uniform(0, 2 * math.pi)
            spd = random.uniform(0.5, 2.5)
            self._particles.append([
                cx, cy,
                math.cos(ang) * spd,
                math.sin(ang) * spd,
                1.0,
                random.choice([C.PRI, C.TEAL, C.GREEN]),
            ])

        self._particles = [
            [p[0]+p[2], p[1]+p[3], p[2]*0.97, p[3]*0.97,
             p[4]-0.01, p[5]]
            for p in self._particles if p[4] > 0
        ]

        self.update()

    # ── Input handling ─────────────────────────────────────────────────────

    def wheelEvent(self, e: QWheelEvent):
        delta = e.angleDelta().y()
        factor = 1.1 if delta > 0 else 0.9
        self._zoom = max(0.3, min(5.0, self._zoom * factor))
        self.update()

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            # Check if clicking on a device
            click_pos = e.position()
            for pos, device in self._device_positions:
                dist = math.hypot(
                    click_pos.x() - pos.x(),
                    click_pos.y() - pos.y()
                )
                if dist < 20 * self._zoom:
                    self._selected_device = device
                    self.update()
                    return

            self._selected_device = None
            self._dragging = True
            self._drag_start = e.position()
            self._pan_start_x = self._pan_x
            self._pan_start_y = self._pan_y

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._dragging:
            dx = e.position().x() - self._drag_start.x()
            dy = e.position().y() - self._drag_start.y()
            self._pan_x = self._pan_start_x + dx
            self._pan_y = self._pan_start_y + dy
            self.update()
        else:
            # Check hover
            mouse_pos = e.position()
            self._hover_device = None
            for pos, device in self._device_positions:
                dist = math.hypot(
                    mouse_pos.x() - pos.x(),
                    mouse_pos.y() - pos.y()
                )
                if dist < 20 * self._zoom:
                    self._hover_device = device
                    self._hover_pos = pos
                    break
            self.update()

    def mouseReleaseEvent(self, e: QMouseEvent):
        self._dragging = False

    # ── PAINTING ───────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        W, H = self.width(), self.height()
        cx = W / 2 + self._pan_x
        cy = H / 2 + self._pan_y

        # ── Background ─────────────────────────────
        p.fillRect(self.rect(), qc(C.BG))

        # Hex grid
        self._grid.draw(p, 14)

        # Scan sweep (rotating radar line)
        sweep_ang = math.radians(self._scan_angle)
        sweep_len = min(W, H) * 0.45 * self._zoom
        sx = cx + math.cos(sweep_ang) * sweep_len
        sy = cy + math.sin(sweep_ang) * sweep_len

        grad = QConicalGradient(QPointF(cx, cy), -self._scan_angle)
        grad.setColorAt(0.0, qc(C.PRI, 60))
        grad.setColorAt(0.05, qc(C.PRI, 30))
        grad.setColorAt(0.1, qc(C.PRI, 0))
        grad.setColorAt(1.0, qc(C.PRI, 0))

        sweep_path = QPainterPath()
        sweep_path.moveTo(QPointF(cx, cy))
        sweep_r = sweep_len
        for i in range(37):  # ~36 degrees of sweep
            a = sweep_ang - math.radians(i)
            sweep_path.lineTo(QPointF(
                cx + math.cos(a) * sweep_r,
                cy + math.sin(a) * sweep_r,
            ))
        sweep_path.closeSubpath()
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(sweep_path)

        # Sweep line
        p.setPen(QPen(qc(C.PRI, 120), 1.5))
        p.drawLine(QPointF(cx, cy), QPointF(sx, sy))

        # ── Range rings ────────────────────────────
        ring_radii = [80, 160, 260, 380, 520]
        ring_labels = ["CORE", "LOCAL", "BLUETOOTH", "NETWORK", "GLOBAL"]

        for i, (r, label) in enumerate(zip(ring_radii, ring_labels)):
            r_scaled = r * self._zoom
            alpha = 40 - i * 5
            p.setPen(QPen(qc(C.PRI, alpha), 0.8,
                          Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(
                cx - r_scaled, cy - r_scaled,
                r_scaled * 2, r_scaled * 2
            ))

            # Ring label
            p.setFont(QFont("Courier New", 6))
            p.setPen(QPen(qc(C.TEXT_DIM, alpha + 20), 1))
            p.drawText(QPointF(cx + r_scaled + 5, cy - 3), label)

        # ── Particles ──────────────────────────────
        for pt in self._particles:
            px, py, _, _, life, col = pt
            p.setBrush(QBrush(qc(col, int(150 * life))))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(px, py), 2, 2)

        # ── Central node (this machine) ────────────
        self._reactor.draw(p, cx, cy, 35 * self._zoom, 1.0)

        # Machine label
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qc(C.PRI), 1))
        p.drawText(
            QRectF(cx - 60, cy + 40 * self._zoom, 120, 16),
            Qt.AlignmentFlag.AlignCenter,
            "◈ JARVIS NODE"
        )

        # ── Clear device positions for hit testing ─
        self._device_positions = []

        # ── Layer 1: Network devices ───────────────
        if self._layers["network"] and self._net_devices:
            self._draw_network_layer(p, cx, cy)

        # ── Layer 2: Bluetooth devices ─────────────
        if self._layers["bluetooth"] and self._bt_devices:
            self._draw_bluetooth_layer(p, cx, cy)

        # ── Layer 3: Geographic connections ────────
        if self._layers["geographic"] and self._geo_connections:
            self._draw_geo_layer(p, cx, cy)

        # ── Layer 4: Security alerts ───────────────
        if self._layers["security"] and self._security_alerts:
            self._draw_security_layer(p, cx, cy)

        # ── Layer 5: Trading nodes ─────────────────
        if self._layers["trading"] and self._trading_nodes:
            self._draw_trading_layer(p, cx, cy)

        # ── Hover tooltip ──────────────────────────
        if self._hover_device:
            self._draw_tooltip(p, self._hover_pos, self._hover_device)

        # ── Selected device detail panel ───────────
        if self._selected_device:
            self._draw_detail_panel(p, self._selected_device)

        # ── HUD overlay (layer toggles + stats) ────
        self._draw_hud_overlay(p, W, H)

        p.end()

    # ── LAYER RENDERERS ────────────────────────────────────────────────────

    def _draw_network_layer(self, p: QPainter,
                            cx: float, cy: float):
        """Draw WiFi/LAN devices as nodes around center."""
        devices = [d for d in self._net_devices if not d.is_self]
        if not devices:
            return

        base_radius = 180 * self._zoom
        angle_step = 360 / max(len(devices), 1)

        for i, dev in enumerate(devices):
            angle = math.radians(i * angle_step + self._tick * 0.1)

            # Gateway closer, unknown further
            if dev.is_gateway:
                r = base_radius * 0.5
            elif dev.is_unknown:
                r = base_radius * 1.3
            else:
                r = base_radius * (0.7 + random.Random(
                    hash(dev.mac)
                ).random() * 0.5)

            dx = cx + math.cos(angle) * r
            dy = cy + math.sin(angle) * r

            self._device_positions.append((QPointF(dx, dy), dev))

            # Connection line to center
            line_alpha = 80 if not dev.is_unknown else 40
            line_color = C.RED if dev.is_unknown else C.PRI
            p.setPen(QPen(qc(line_color, line_alpha), 0.8))
            p.drawLine(QPointF(cx, cy), QPointF(dx, dy))

            # Animated data flow dots on the line
            if self._tick % 30 < 15:
                t = (self._tick % 30) / 30.0
                fx = cx + (dx - cx) * t
                fy = cy + (dy - cy) * t
                p.setBrush(QBrush(qc(line_color, 180)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QPointF(fx, fy), 2, 2)

            # Device node
            node_r = 12 * self._zoom
            if dev.is_unknown:
                # Red pulsing for unknown
                pulse_a = int(
                    180 + 75 * math.sin(self._pulse * 3 + i)
                )
                p.setBrush(QBrush(qc(C.RED, int(pulse_a * 0.3))))
                p.setPen(QPen(qc(C.RED, pulse_a), 2))
            elif dev.is_gateway:
                p.setBrush(QBrush(qc(C.ACC2, 80)))
                p.setPen(QPen(qc(C.ACC2, 200), 2))
            else:
                p.setBrush(QBrush(qc(C.PRI, 60)))
                p.setPen(QPen(qc(C.PRI, 160), 1.5))

            p.drawEllipse(QPointF(dx, dy), node_r, node_r)

            # Device type icon
            icons = {
                "router": "📡", "phone": "📱", "pc": "💻",
                "iot": "🔌", "tv": "📺", "unknown": "❓",
            }
            icon = icons.get(dev.device_type, "●")
            p.setFont(QFont("Segoe UI Emoji", int(10 * self._zoom)))
            p.setPen(QPen(qc(C.WHITE), 1))
            p.drawText(
                QRectF(dx - node_r, dy - node_r,
                       node_r * 2, node_r * 2),
                Qt.AlignmentFlag.AlignCenter, icon
            )

            # IP label
            p.setFont(QFont("Courier New", max(5, int(6 * self._zoom))))
            label_color = C.RED if dev.is_unknown else C.TEXT_DIM
            p.setPen(QPen(qc(label_color), 1))
            p.drawText(
                QRectF(dx - 50, dy + node_r + 2, 100, 12),
                Qt.AlignmentFlag.AlignCenter, dev.ip
            )

    def _draw_bluetooth_layer(self, p: QPainter,
                              cx: float, cy: float):
        """Draw Bluetooth devices on the BT ring."""
        devices = self._bt_devices
        if not devices:
            return

        angle_step = 360 / max(len(devices), 1)

        for i, dev in enumerate(devices):
            # Distance based on RSSI (-30 = very close, -100 = far)
            rssi_norm = max(0, min(1, (dev.rssi + 100) / 70))
            base_r = 260 * self._zoom
            r = base_r * (0.6 + (1 - rssi_norm) * 0.6)

            angle = math.radians(
                i * angle_step + 180 + self._tick * 0.05
            )
            dx = cx + math.cos(angle) * r
            dy = cy + math.sin(angle) * r

            self._device_positions.append((QPointF(dx, dy), dev))

            # BT connection line (dashed for available, solid
            # for connected)
            style = (Qt.PenStyle.SolidLine if dev.connected
                     else Qt.PenStyle.DashDotLine)
            color = C.PURPLE if dev.connected else C.PURPLE
            alpha = 120 if dev.connected else 50
            p.setPen(QPen(qc(color, alpha), 0.8, style))
            p.drawLine(QPointF(cx, cy), QPointF(dx, dy))

            # Node
            node_r = 10 * self._zoom
            if dev.connected:
                p.setBrush(QBrush(qc(C.PURPLE, 100)))
                p.setPen(QPen(qc(C.PURPLE, 220), 2))
            else:
                p.setBrush(QBrush(qc(C.PURPLE, 40)))
                p.setPen(QPen(qc(C.PURPLE, 100), 1))

            p.drawEllipse(QPointF(dx, dy), node_r, node_r)

            # BT type icon
            bt_icons = {
                "audio": "🎧", "keyboard": "⌨", "mouse": "🖱",
                "phone": "📱", "watch": "⌚", "gamepad": "🎮",
                "unknown": "⚡",
            }
            icon = bt_icons.get(dev.device_type, "⚡")
            p.setFont(QFont("Segoe UI Emoji", int(8 * self._zoom)))
            p.setPen(QPen(qc(C.WHITE), 1))
            p.drawText(
                QRectF(dx - node_r, dy - node_r,
                       node_r * 2, node_r * 2),
                Qt.AlignmentFlag.AlignCenter, icon
            )

            # Name label
            p.setFont(QFont(
                "Courier New", max(5, int(6 * self._zoom))
            ))
            p.setPen(QPen(qc(C.PURPLE, 150), 1))
            name = dev.name[:16] if len(dev.name) > 16 else dev.name
            p.drawText(
                QRectF(dx - 60, dy + node_r + 2, 120, 12),
                Qt.AlignmentFlag.AlignCenter, name
            )

    def _draw_geo_layer(self, p: QPainter,
                        cx: float, cy: float):
        """Draw geographic connections as arcing lines to
        country clusters."""
        connections = self._geo_connections
        if not connections:
            return

        # Group by country
        countries: dict[str, list[GeoConnection]] = {}
        for conn in connections:
            key = conn.country or conn.remote_ip
            countries.setdefault(key, []).append(conn)

        base_r = 420 * self._zoom
        angle_step = 360 / max(len(countries), 1)

        for i, (country, conns) in enumerate(countries.items()):
            angle = math.radians(i * angle_step + 90)
            dx = cx + math.cos(angle) * base_r
            dy = cy + math.sin(angle) * base_r

            # Draw arc from center to country node
            mid_x = (cx + dx) / 2
            mid_y = (cy + dy) / 2 - 40 * self._zoom

            path = QPainterPath()
            path.moveTo(QPointF(cx, cy))
            path.quadTo(QPointF(mid_x, mid_y), QPointF(dx, dy))

            has_vpn = any(c.is_vpn for c in conns)
            color = C.ACC2 if has_vpn else C.TEAL
            alpha = 80

            p.setPen(QPen(qc(color, alpha), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

            # Animated flow
            t = (self._tick % 60) / 60.0
            point = path.pointAtPercent(t)
            p.setBrush(QBrush(qc(color, 200)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(point, 3, 3)

            # Country node
            node_r = (8 + len(conns) * 2) * self._zoom
            node_r = min(node_r, 25 * self._zoom)

            p.setBrush(QBrush(qc(color, 50)))
            p.setPen(QPen(qc(color, 150), 1.5))
            p.drawEllipse(QPointF(dx, dy), node_r, node_r)

            # Country label
            p.setFont(QFont(
                "Courier New", max(6, int(7 * self._zoom)),
                QFont.Weight.Bold
            ))
            p.setPen(QPen(qc(color), 1))
            label = f"{country} ({len(conns)})"
            p.drawText(
                QRectF(dx - 60, dy + node_r + 2, 120, 14),
                Qt.AlignmentFlag.AlignCenter, label
            )

            # VPN indicator
            if has_vpn:
                p.setFont(QFont("Courier New", 6))
                p.setPen(QPen(qc(C.ACC2), 1))
                p.drawText(
                    QRectF(dx - 30, dy - node_r - 12, 60, 10),
                    Qt.AlignmentFlag.AlignCenter, "🔒 VPN"
                )

    def _draw_security_layer(self, p: QPainter,
                             cx: float, cy: float):
        """Draw security alerts as pulsing indicators."""
        for alert in self._security_alerts:
            # Position based on associated device or random
            if alert.device_ip:
                # Find device position
                for pos, dev in self._device_positions:
                    if (isinstance(dev, NetworkDevice)
                            and dev.ip == alert.device_ip):
                        ax, ay = pos.x(), pos.y()
                        break
                else:
                    continue
            else:
                continue

            # Alert indicator
            color_map = {
                "info": C.PRI,
                "warning": C.ACC2,
                "critical": C.RED,
            }
            color = color_map.get(alert.level, C.PRI)

            # Pulsing ring
            pulse = abs(math.sin(self._pulse * 2))
            ring_r = (20 + pulse * 10) * self._zoom

            p.setPen(QPen(qc(color, int(200 * pulse)), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(ax, ay), ring_r, ring_r)

            # Alert icon
            icons = {"info": "ℹ", "warning": "⚠", "critical": "🚨"}
            p.setFont(QFont("Segoe UI Emoji", int(8 * self._zoom)))
            p.setPen(QPen(qc(color), 1))
            p.drawText(
                QPointF(ax + 15 * self._zoom, ay - 15 * self._zoom),
                icons.get(alert.level, "⚠")
            )

    def _draw_trading_layer(self, p: QPainter,
                            cx: float, cy: float):
        """Draw trading infrastructure nodes."""
        if not self._trading_nodes:
            return

        base_r = 350 * self._zoom
        angle_step = 360 / max(len(self._trading_nodes), 1)

        for i, node in enumerate(self._trading_nodes):
            angle = math.radians(i * angle_step + 45)
            dx = cx + math.cos(angle) * base_r
            dy = cy + math.sin(angle) * base_r

            # Color based on status
            if node.status == "online":
                color = C.GREEN
            elif node.status == "slow":
                color = C.ACC2
            else:
                color = C.RED

            # Connection line
            p.setPen(QPen(qc(color, 60), 1))
            p.drawLine(QPointF(cx, cy), QPointF(dx, dy))

            # Node
            node_r = 14 * self._zoom
            p.setBrush(QBrush(qc(color, 50)))
            p.setPen(QPen(qc(color, 180), 1.5))
            p.drawEllipse(QPointF(dx, dy), node_r, node_r)

            # Icon
            p.setFont(QFont("Segoe UI Emoji", int(10 * self._zoom)))
            p.setPen(QPen(qc(C.WHITE), 1))
            p.drawText(
                QRectF(dx - node_r, dy - node_r,
                       node_r * 2, node_r * 2),
                Qt.AlignmentFlag.AlignCenter, "📊"
            )

            # Label + ping
            p.setFont(QFont(
                "Courier New", max(5, int(6 * self._zoom))
            ))
            p.setPen(QPen(qc(color), 1))
            ping_str = (f"{node.ping_ms:.0f}ms"
                        if node.ping_ms > 0 else "N/A")
            p.drawText(
                QRectF(dx - 50, dy + node_r + 2, 100, 12),
                Qt.AlignmentFlag.AlignCenter,
                f"{node.name} ({ping_str})"
            )

    # ── TOOLTIP & DETAIL PANEL ─────────────────────────────────────────────

    def _draw_tooltip(self, p: QPainter,
                      pos: QPointF, device: object):
        """Draw hover tooltip for a device."""
        tx = pos.x() + 20
        ty = pos.y() - 10
        tw, th = 220, 0

        lines = []
        if isinstance(device, NetworkDevice):
            lines = [
                ("IP", device.ip),
                ("MAC", device.mac),
                ("TYPE", device.device_type.upper()),
                ("VENDOR", device.vendor or "Unknown"),
            ]
            if device.is_gateway:
                lines.append(("ROLE", "GATEWAY"))
            if device.is_unknown:
                lines.append(("⚠ STATUS", "UNKNOWN DEVICE"))
            if device.ports:
                lines.append((
                    "PORTS",
                    ", ".join(str(p) for p in device.ports[:5])
                ))
        elif isinstance(device, BluetoothDevice):
            lines = [
                ("NAME", device.name),
                ("MAC", device.mac),
                ("TYPE", device.device_type.upper()),
                ("RSSI", f"{device.rssi} dBm"),
                ("STATUS",
                 "CONNECTED" if device.connected else "AVAILABLE"),
            ]

        th = len(lines) * 18 + 20

        # Keep tooltip on screen
        if tx + tw > self.width():
            tx = pos.x() - tw - 20
        if ty + th > self.height():
            ty = self.height() - th - 10

        # Background
        p.setBrush(QBrush(qc("#001018", 230)))
        p.setPen(QPen(qc(C.PRI, 180), 1.5))
        p.drawRoundedRect(QRectF(tx, ty, tw, th), 4, 4)

        # Content
        y = ty + 10
        for label, value in lines:
            p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))

            if "⚠" in label:
                p.setPen(QPen(qc(C.RED), 1))
            else:
                p.setPen(QPen(qc(C.TEXT_DIM), 1))

            p.drawText(QRectF(tx + 8, y, 70, 14),
                       Qt.AlignmentFlag.AlignLeft, label)

            p.setFont(QFont("Courier New", 7))
            if "UNKNOWN" in str(value):
                p.setPen(QPen(qc(C.RED), 1))
            elif value in ("CONNECTED", "GATEWAY"):
                p.setPen(QPen(qc(C.GREEN), 1))
            else:
                p.setPen(QPen(qc(C.TEXT), 1))

            p.drawText(QRectF(tx + 80, y, tw - 90, 14),
                       Qt.AlignmentFlag.AlignLeft, str(value))
            y += 18

    def _draw_detail_panel(self, p: QPainter, device: object):
        """Draw selected device detail panel on the right."""
        W, H = self.width(), self.height()
        pw, ph = 280, 350
        px = W - pw - 20
        py = 80

        # Panel background
        p.setBrush(QBrush(qc("#000d14", 220)))
        p.setPen(QPen(qc(C.BORDER_B, 180), 1.5))
        p.drawRoundedRect(QRectF(px, py, pw, ph), 6, 6)

        # Title
        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qc(C.PRI), 1))

        if isinstance(device, NetworkDevice):
            title = "◈ NETWORK DEVICE"
            details = [
                ("IP ADDRESS", device.ip),
                ("MAC", device.mac),
                ("HOSTNAME", device.hostname or "—"),
                ("VENDOR", device.vendor or "Unknown"),
                ("TYPE", device.device_type.upper()),
                ("GATEWAY", "YES" if device.is_gateway else "NO"),
                ("STATUS",
                 "⚠ UNKNOWN" if device.is_unknown else "KNOWN"),
            ]
            if device.ports:
                details.append((
                    "OPEN PORTS",
                    ", ".join(str(port) for port in device.ports)
                ))
        elif isinstance(device, BluetoothDevice):
            title = "◈ BLUETOOTH DEVICE"
            details = [
                ("NAME", device.name),
                ("MAC", device.mac),
                ("TYPE", device.device_type.upper()),
                ("RSSI", f"{device.rssi} dBm"),
                ("PAIRED", "YES" if device.paired else "NO"),
                ("CONNECTED",
                 "YES" if device.connected else "NO"),
            ]
        else:
            return

        p.drawText(QRectF(px + 12, py + 10, pw - 24, 16),
                    Qt.AlignmentFlag.AlignLeft, title)

        # Separator
        p.setPen(QPen(qc(C.BORDER_B, 120), 1))
        p.drawLine(QPointF(px + 12, py + 30),
                   QPointF(px + pw - 12, py + 30))

        # Details
        y = py + 40
        for label, value in details:
            p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            p.setPen(QPen(qc(C.TEXT_DIM), 1))
            p.drawText(
                QRectF(px + 12, y, pw - 24, 14),
                Qt.AlignmentFlag.AlignLeft, label
            )

            p.setFont(QFont("Courier New", 8))
            if "UNKNOWN" in str(value):
                p.setPen(QPen(qc(C.RED), 1))
            elif value in ("YES", "CONNECTED", "ONLINE"):
                p.setPen(QPen(qc(C.GREEN), 1))
            elif value in ("NO", "OFFLINE"):
                p.setPen(QPen(qc(C.RED, 150), 1))
            else:
                p.setPen(QPen(qc(C.TEXT), 1))

            p.drawText(
                QRectF(px + 12, y + 14, pw - 24, 14),
                Qt.AlignmentFlag.AlignLeft, str(value)
            )
            y += 34

    # ── HUD OVERLAY ────────────────────────────────────────────────────────

    def _draw_hud_overlay(self, p: QPainter, W: int, H: int):
        """Draw layer toggles, stats, and compass on the HUD."""

        # ── Top-left: Layer toggles ────────────────
        panel_x, panel_y = 15, 60
        panel_w, panel_h = 200, 160

        p.setBrush(QBrush(qc("#000d14", 200)))
        p.setPen(QPen(qc(C.BORDER_B, 120), 1))
        p.drawRoundedRect(
            QRectF(panel_x, panel_y, panel_w, panel_h), 4, 4
        )

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qc(C.PRI_DIM), 1))
        p.drawText(QRectF(panel_x + 8, panel_y + 6, panel_w, 14),
                    Qt.AlignmentFlag.AlignLeft, "◈ LAYERS")

        p.setPen(QPen(qc(C.BORDER_B, 80), 1))
        p.drawLine(QPointF(panel_x + 8, panel_y + 22),
                   QPointF(panel_x + panel_w - 8, panel_y + 22))

        layer_defs = [
            ("network",   "NETWORK",   C.PRI,    "F1"),
            ("bluetooth", "BLUETOOTH", C.PURPLE, "F2"),
            ("geographic","GEOGRAPHIC",C.TEAL,   "F3"),
            ("security",  "SECURITY",  C.RED,    "F5"),
            ("trading",   "TRADING",   C.ACC2,   "F6"),
        ]

        y = panel_y + 28
        for key, label, color, hotkey in layer_defs:
            active = self._layers.get(key, False)
            indicator = "●" if active else "○"
            alpha = 200 if active else 80

            p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            p.setPen(QPen(qc(color, alpha), 1))
            p.drawText(
                QRectF(panel_x + 10, y, panel_w - 50, 14),
                Qt.AlignmentFlag.AlignLeft,
                f"{indicator}  {label}"
            )

            p.setFont(QFont("Courier New", 6))
            p.setPen(QPen(qc(C.TEXT_DIM, 120), 1))
            p.drawText(
                QRectF(panel_x + panel_w - 35, y + 1, 28, 12),
                Qt.AlignmentFlag.AlignRight, hotkey
            )
            y += 22

        # ── Top-right: Stats ───────────────────────
        stats_w, stats_h = 180, 100
        stats_x = W - stats_w - 15
        stats_y = 60

        p.setBrush(QBrush(qc("#000d14", 200)))
        p.setPen(QPen(qc(C.BORDER_B, 120), 1))
        p.drawRoundedRect(
            QRectF(stats_x, stats_y, stats_w, stats_h), 4, 4
        )

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qc(C.PRI_DIM), 1))
        p.drawText(
            QRectF(stats_x + 8, stats_y + 6, stats_w, 14),
            Qt.AlignmentFlag.AlignLeft, "◈ SCAN STATUS"
        )

        p.setPen(QPen(qc(C.BORDER_B, 80), 1))
        p.drawLine(QPointF(stats_x + 8, stats_y + 22),
                   QPointF(stats_x + stats_w - 8, stats_y + 22))

        stats = [
            ("DEVICES", str(len(self._net_devices)), C.PRI),
            ("BLUETOOTH", str(len(self._bt_devices)), C.PURPLE),
            ("CONNECTIONS", str(len(self._geo_connections)), C.TEAL),
        ]

        sy = stats_y + 28
        for label, value, color in stats:
            p.setFont(QFont("Courier New", 7))
            p.setPen(QPen(qc(C.TEXT_DIM), 1))
            p.drawText(
                QRectF(stats_x + 10, sy, 100, 14),
                Qt.AlignmentFlag.AlignLeft, label
            )

            p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            p.setPen(QPen(qc(color), 1))
            p.drawText(
                QRectF(stats_x + 110, sy, 60, 14),
                Qt.AlignmentFlag.AlignRight, value
            )
            sy += 20

        # ── Bottom: Controls hint ──────────────────
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qc(C.TEXT_DIM, 100), 1))
        p.drawText(
            QRectF(0, H - 30, W, 20),
            Qt.AlignmentFlag.AlignCenter,
            "SCROLL=ZOOM  ·  DRAG=PAN  ·  "
            "CLICK=SELECT  ·  F1-F6=LAYERS  ·  "
            "ESC=CLOSE"
        )

    # ── Cleanup ────────────────────────────────────────────────────────────

    def cleanup(self):
        """Stop all scanners."""
        self._net_scanner.stop()
        self._bt_scanner.stop()
        self._geo_scanner.stop()
        self._timer.stop()