"""
J.A.R.V.I.S  —  VINCEVISION ASSISTANT
Full-screen borderless HUD  ·  Drop-in replacement for ui.py
Compatible with the existing main.py  (set_state / write_log / muted / current_file / on_text_command)
LAUNCH SCREEN STYLE MAIN INTERFACE with EMBEDDED TECH MAP!
"""
from __future__ import annotations

import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from PyQt6.QtCore import (
    QEasingCurve, QMimeData, QObject, QPointF, QRectF, QSize, Qt,
    QTimer, QUrl, pyqtSignal, QThread,
)
from PyQt6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QFontDatabase,
    QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient, QShortcut, QCursor, QConicalGradient,
)
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QTextEdit,
    QVBoxLayout, QWidget, QGridLayout, QStackedWidget,
)

# ── Tech Map (lazy import to avoid circular) ──────────────────────────────
_techmap_widget_class = None

def _get_techmap_class():
    global _techmap_widget_class
    if _techmap_widget_class is None:
        from ui_techmap import TechMapWidget
        _techmap_widget_class = TechMapWidget
    return _techmap_widget_class

# ── HoloGlobe (lazy import) ──────────────────────────────────────────────
_hologlobe_widget_class = None

def _get_hologlobe_class():
    global _hologlobe_widget_class
    if _hologlobe_widget_class is None:
        from ui_hologlobe import HoloGlobeWidget
        _hologlobe_widget_class = HoloGlobeWidget
    return _hologlobe_widget_class


# ── Paths ──────────────────────────────────────────────────────────────────
def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"
_OS = platform.system()

# ── Colour Palette ─────────────────────────────────────────────────────────
class C:
    BG         = "#00060a"
    PANEL      = "#010d14"
    PANEL2     = "#010f18"
    PANEL3     = "#011520"
    BORDER     = "#0a2535"
    BORDER_B   = "#1a5c7a"
    BORDER_A   = "#0f4060"
    BORDER_HOT = "#00d4ff"
    PRI        = "#00d4ff"
    PRI_DIM    = "#007a99"
    PRI_GHO    = "#001f2e"
    PRI_GLOW   = "#003344"
    ACC        = "#ff6b00"
    ACC2       = "#ffcc00"
    GREEN      = "#00ff88"
    GREEN_D    = "#00aa55"
    RED        = "#ff3355"
    MUTED_C    = "#ff3366"
    TEXT       = "#8ffcff"
    TEXT_DIM   = "#2a6a7a"
    TEXT_MED   = "#5ab8cc"
    WHITE      = "#d8f8ff"
    DARK       = "#000d14"
    BAR_BG     = "#011520"
    PURPLE     = "#9944ff"
    TEAL       = "#00ffcc"

def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c

def qc(h: str, a: int = 255) -> QColor:
    return qcol(h, a)

# ── System Metrics ─────────────────────────────────────────────────────────
class _SysMetrics:
    def __init__(self):
        self.cpu = 0.0; self.mem = 0.0; self.net = 0.0
        self.gpu = -1.0; self.tmp = -1.0
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._cpu_hist: list[float] = [0.0] * 60
        self._net_hist: list[float] = [0.0] * 60
        self._mem_hist: list[float] = [0.0] * 60
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try: self._update()
            except: pass
            time.sleep(1.5)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        nc  = psutil.net_io_counters()
        now = time.time(); dt = now - self._last_net_t
        net = ((nc.bytes_sent - self._last_net.bytes_sent) +
               (nc.bytes_recv - self._last_net.bytes_recv)) / max(dt, 0.001) / (1024*1024)
        self._last_net = nc; self._last_net_t = now
        gpu = self._get_gpu(); tmp = self._get_temp()
        with self._lock:
            self.cpu = cpu; self.mem = mem; self.net = net
            self.gpu = gpu; self.tmp = tmp
            self._cpu_hist = self._cpu_hist[1:] + [cpu]
            self._net_hist = self._net_hist[1:] + [min(net * 10, 100)]
            self._mem_hist = self._mem_hist[1:] + [mem]

    def _get_gpu(self) -> float:
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2
            )
            if r.returncode == 0:
                vals = [
                    float(v.strip())
                    for v in r.stdout.strip().split("\n") if v.strip()
                ]
                if vals: return sum(vals) / len(vals)
        except: pass
        return -1.0

    def _get_temp(self) -> float:
        try:
            temps = psutil.sensors_temperatures()
            for name in ["coretemp", "k10temp", "cpu_thermal",
                         "acpitz", "cpu-thermal"]:
                if name in temps and temps[name]:
                    return temps[name][0].current
            for entries in temps.values():
                if entries: return entries[0].current
        except: pass
        return -1.0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu, "mem": self.mem, "net": self.net,
                "gpu": self.gpu, "tmp": self.tmp,
                "cpu_hist": list(self._cpu_hist),
                "net_hist": list(self._net_hist),
                "mem_hist": list(self._mem_hist),
            }

_metrics = _SysMetrics()

# ── Helpers ────────────────────────────────────────────────────────────────
_FILE_ICONS = {
    "image":  ("🖼",  "#00d4ff"), "video":  ("🎬", "#ff6b00"),
    "audio":  ("🎵",  "#cc44ff"), "pdf":    ("📄", "#ff4444"),
    "word":   ("📝",  "#4488ff"), "excel":  ("📊", "#44bb44"),
    "code":   ("💻",  "#ffcc00"), "archive":("📦", "#ff8844"),
    "pptx":   ("📊",  "#ff6622"), "text":   ("📃", "#aaaaaa"),
    "data":   ("🔧",  "#88ddff"), "unknown":("📎", "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp",
                     "tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv",
                     "webm","m4v"], "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac",
                     "wma","opus"], "audio"),
    **dict.fromkeys(["pdf"], "pdf"),
    **dict.fromkeys(["doc","docx"], "word"),
    **dict.fromkeys(["xls","xlsx","ods"], "excel"),
    **dict.fromkeys(["ppt","pptx"], "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css",
                     "java","c","cpp","cs","go","rs","rb","php",
                     "swift","kt","sh","sql","lua"], "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],
                    "archive"),
    **dict.fromkeys(["txt","md","rst","log"], "text"),
    **dict.fromkeys(["csv","tsv","json","xml"], "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if size < 1024:       return f"{size} B"
    elif size < 1024**2:  return f"{size/1024:.1f} KB"
    elif size < 1024**3:  return f"{size/1024**2:.1f} MB"
    else:                 return f"{size/1024**3:.1f} GB"


# ══════════════════════════════════════════════════════════════════════════
#  IRON MAN LAUNCH SCREEN
# ══════════════════════════════════════════════════════════════════════════

def _get_boot_messages() -> list[tuple[str, str]]:
    os_name  = platform.system()
    cpu_name = "UNKNOWN PROCESSOR"
    try:
        if os_name == "Linux":
            r = subprocess.run(["cat", "/proc/cpuinfo"],
                               capture_output=True, text=True)
            for line in r.stdout.splitlines():
                if "model name" in line:
                    cpu_name = line.split(":")[1].strip()[:42]
                    break
        elif os_name == "Windows":
            r = subprocess.run(["wmic", "cpu", "get", "name"],
                               capture_output=True, text=True)
            lines = [l.strip() for l in r.stdout.splitlines()
                     if l.strip()]
            if len(lines) > 1: cpu_name = lines[1][:42]
        elif os_name == "Darwin":
            r = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True
            )
            cpu_name = r.stdout.strip()[:42]
    except Exception:
        pass

    try:
        ram_gb  = round(psutil.virtual_memory().total / (1024**3), 1)
        ram_str = f"{ram_gb} GB"
    except Exception:
        ram_str = "UNKNOWN"

    try:
        disk     = psutil.disk_usage("/")
        disk_str = f"{round(disk.total / (1024**3), 0):.0f} GB"
    except Exception:
        disk_str = "UNKNOWN"

    return [
        ("━━━  VINCEVISION INDUSTRIES  ━━━━━━━━━━━━━━━━━━━━━━━━", "acc2"),
        ("INITIALISING J.A.R.V.I.S CORE SYSTEMS...",              "pri"),
        (f"PLATFORM    : {os_name.upper()}",                       "dim"),
        (f"PROCESSOR   : {cpu_name}",                              "dim"),
        (f"MEMORY      : {ram_str}",                               "dim"),
        (f"STORAGE     : {disk_str}",                              "dim"),
        ("HARDWARE SCAN ········ COMPLETE",                        "green"),
        ("",                                                       "dim"),
        ("LOADING NEURAL NETWORK LAYERS...",                       "pri"),
        ("  LAYER 01  PERCEPTION MODULE        ████████  OK",      "dim"),
        ("  LAYER 02  LANGUAGE CORE            ████████  OK",      "dim"),
        ("  LAYER 03  REASONING ENGINE         ████████  OK",      "dim"),
        ("  LAYER 04  MEMORY INTERFACE         ████████  OK",      "dim"),
        ("  LAYER 05  TOOL ORCHESTRATION       ████████  OK",      "dim"),
        ("  LAYER 06  VOICE SYNTHESIS          ████████  OK",      "dim"),
        ("NEURAL NETWORK ········ ONLINE",                         "green"),
        ("",                                                       "dim"),
        ("LOADING AGENT REGISTRY...",                              "pri"),
        ("  ✓  BLUETOOTH AGENT",                                   "teal"),
        ("  ✓  DEV FORGE AGENT",                                   "teal"),
        ("  ✓  SECURITY AGENT",                                    "teal"),
        ("  ✓  NETWORK AGENT",                                     "teal"),
        ("  ✓  TRACER AGENT",                                      "teal"),
        ("  ✓  BROWSER AGENT",                                     "teal"),
        ("ALL AGENTS ········ LOADED",                             "green"),
        ("",                                                       "dim"),
        ("RUNNING SECURITY PROTOCOLS...",                          "pri"),
        ("  FIREWALL STATUS      : ACTIVE",                        "dim"),
        ("  ENCRYPTION           : AES-256",                       "dim"),
        ("  VOICE AUTHENTICATION : ENABLED",                       "dim"),
        ("  THREAT LEVEL         : NOMINAL",                       "dim"),
        ("SECURITY CLEARANCE ········ GRANTED",                    "green"),
        ("",                                                       "dim"),
        ("ALL SYSTEMS NOMINAL",                                    "acc2"),
        ("WELCOME BACK, SIR.",                                     "white"),
        ("J.A.R.V.I.S IS NOW ONLINE",                             "pri"),
    ]


class _HexGrid:
    """Pre-computes hex cell centres for the background grid."""
    def __init__(self, w: int, h: int, size: int = 38):
        self._size = size
        self.cells: list[tuple[float, float]] = []
        self._recompute(w, h)

    def _recompute(self, w: int, h: int):
        s  = self._size
        dx = s * math.sqrt(3)
        dy = s * 1.5
        self.cells = []
        cols = int(w / dx) + 3
        rows = int(h / dy) + 3
        for row in range(-1, rows):
            for col in range(-1, cols):
                x = col * dx + (dx / 2 if row % 2 else 0)
                y = row * dy
                self.cells.append((x, y))

    def draw(self, p: QPainter, alpha: int):
        s = self._size
        p.setBrush(Qt.BrushStyle.NoBrush)
        for cx, cy in self.cells:
            pts = []
            for i in range(6):
                ang = math.radians(60 * i - 30)
                pts.append(QPointF(cx + s * math.cos(ang),
                                   cy + s * math.sin(ang)))
            path = QPainterPath()
            path.moveTo(pts[0])
            for pt in pts[1:]: path.lineTo(pt)
            path.closeSubpath()
            p.setPen(QPen(qc(C.PRI, alpha), 0.6))
            p.drawPath(path)


class _ArcReactor:
    """Draws the animated arc reactor."""
    def __init__(self):
        self._angle   = 0.0
        self._angle2  = 0.0
        self._pulse   = 0.0
        self._pulse_d = 1.0

    def step(self):
        self._angle  = (self._angle  + 1.8)  % 360
        self._angle2 = (self._angle2 - 1.12) % 360
        self._pulse += 0.04 * self._pulse_d
        if self._pulse > 1.0 or self._pulse < 0.0:
            self._pulse_d *= -1

    def draw(self, p: QPainter, cx: float, cy: float,
             radius: float, alpha_frac: float = 1.0):
        a = int(255 * alpha_frac)

        for i in range(12):
            r   = radius * (1.6 - i * 0.05)
            frc = 1.0 - i / 12
            ga  = int(a * 0.18 * frc * (0.7 + 0.3 * self._pulse))
            p.setPen(QPen(qc(C.PRI, ga), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx-r, cy-r, r*2, r*2))

        ring_defs = [
            (1.00, 2.5, 120, 85, C.PRI),
            (0.82, 1.8,  90, 65, C.TEAL),
            (0.65, 1.2,  60, 48, C.PRI_DIM),
            (0.48, 0.8,  40, 30, C.GREEN),
        ]
        for r_frac, lw, arc_l, gap, col in ring_defs:
            r    = radius * r_frac
            rect = QRectF(cx-r, cy-r, r*2, r*2)
            base = self._angle if col != C.TEAL else self._angle2
            ang  = base
            while ang < base + 360:
                p.setPen(QPen(qc(col, a), lw))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawArc(rect, int(ang*16), int(arc_l*16))
                ang += arc_l + gap

        inner_r = radius * 0.30
        grad    = QRadialGradient(QPointF(cx, cy), inner_r)
        glow_a  = int(a * (0.5 + 0.5 * self._pulse))
        grad.setColorAt(0.0, qc(C.PRI, glow_a))
        grad.setColorAt(0.5, qc(C.PRI, int(glow_a * 0.4)))
        grad.setColorAt(1.0, qc(C.PRI, 0))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(cx-inner_r, cy-inner_r,
                             inner_r*2, inner_r*2))

        for i in range(6):
            ang = math.radians(self._angle + i * 60)
            x1  = cx + math.cos(ang) * inner_r * 0.8
            y1  = cy + math.sin(ang) * inner_r * 0.8
            x2  = cx + math.cos(ang) * radius  * 0.62
            y2  = cy + math.sin(ang) * radius  * 0.62
            p.setPen(QPen(qc(C.PRI, int(a * 0.5)), 0.8))
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        p.setBrush(QBrush(qc(C.WHITE, a)))
        p.setPen(Qt.PenStyle.NoPen)
        cr = radius * 0.08
        p.drawEllipse(QRectF(cx-cr, cy-cr, cr*2, cr*2))


class _LaunchWaveform:
    def __init__(self, bars: int = 64):
        self._bars    = bars
        self._vals    = [0.0] * bars
        self._targets = [0.0] * bars
        self._active  = False
        self._tick    = 0

    def activate(self):   self._active = True
    def deactivate(self): self._active = False

    def step(self):
        self._tick += 1
        if self._active:
            for i in range(self._bars):
                self._targets[i] = random.uniform(0.1, 1.0)
        else:
            for i in range(self._bars):
                self._targets[i] = (
                    0.12 + 0.08 * math.sin(
                        self._tick * 0.07 + i * 0.42
                    )
                )
        for i in range(self._bars):
            self._vals[i] += (
                (self._targets[i] - self._vals[i]) * 0.25
            )

    def draw(self, p: QPainter, x: float, y: float,
             w: float, h: float, alpha: int):
        bw  = w / self._bars
        col = C.GREEN if self._active else C.PRI_DIM
        for i, v in enumerate(self._vals):
            bh = max(2, v * h)
            bx = x + i * bw
            by = y + h - bh
            aa = int(alpha * (0.5 + 0.5 * v))
            p.setBrush(QBrush(qc(col, aa)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(
                QRectF(bx+1, by, max(1, bw-2), bh), 1, 1
            )


class LaunchScreen(QWidget):
    finished = pyqtSignal()

    _PH_BLACKOUT = 0
    _PH_GRID     = 1
    _PH_REACTOR  = 2
    _PH_DIAG     = 3
    _PH_VOICE    = 4
    _PH_TITLE    = 5
    _PH_FADEOUT  = 6
    _PH_DONE     = 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        self._phase       = self._PH_BLACKOUT
        self._tick        = 0
        self._alpha       = 0.0
        self._grid_a      = 0.0
        self._reactor_a   = 0.0
        self._diag_a      = 0.0
        self._voice_a     = 0.0
        self._title_a     = 0.0
        self._fadeout     = 0.0

        self._grid     = _HexGrid(screen.width(), screen.height(), 38)
        self._reactor  = _ArcReactor()
        self._waveform = _LaunchWaveform(64)

        self._boot_msgs  = _get_boot_messages()
        self._diag_lines: list[tuple[str, str, float]] = []
        self._diag_idx   = 0
        self._diag_timer = 0

        self._title_full  = "J . A . R . V . I . S"
        self._title_chars = 0
        self._title_timer = 0
        self._subtitle    = (
            "VINCEVISION INDUSTRIES  ·  AI CORE  ·  ALL SYSTEMS ONLINE"
        )
        self._sub_a      = 0.0
        self._voice_done = False

        self._particles: list[list] = []
        self._scan_y    = 0.0

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(16)

    def _step(self):
        self._tick += 1
        self._reactor.step()
        self._waveform.step()
        self._scan_y = (self._scan_y + 2.5) % self.height()

        if (self._phase >= self._PH_REACTOR
                and random.random() < 0.07):
            cx  = self.width()  / 2
            cy  = self.height() / 2
            ang = random.uniform(0, 2 * math.pi)
            spd = random.uniform(0.3, 2.0)
            self._particles.append([
                cx, cy,
                math.cos(ang) * spd, math.sin(ang) * spd,
                1.0,
                random.choice([C.PRI, C.TEAL, C.GREEN, C.ACC2]),
            ])
        self._particles = [
            [p[0]+p[2], p[1]+p[3], p[2]*0.97, p[3]*0.97,
             p[4]-0.013, p[5]]
            for p in self._particles if p[4] > 0
        ]

        if self._phase == self._PH_BLACKOUT:
            self._alpha = min(1.0, self._alpha + 0.025)
            if self._tick > 30:
                self._phase = self._PH_GRID

        elif self._phase == self._PH_GRID:
            self._grid_a = min(1.0, self._grid_a + 0.018)
            if self._grid_a >= 0.95:
                self._phase = self._PH_REACTOR

        elif self._phase == self._PH_REACTOR:
            self._reactor_a = min(1.0, self._reactor_a + 0.022)
            if self._reactor_a >= 0.95:
                self._phase = self._PH_DIAG

        elif self._phase == self._PH_DIAG:
            self._diag_a    = min(1.0, self._diag_a + 0.04)
            self._diag_timer += 1
            if (self._diag_timer % 8 == 0
                    and self._diag_idx < len(self._boot_msgs)):
                txt, col = self._boot_msgs[self._diag_idx]
                self._diag_lines.append((txt, col, 0.0))
                self._diag_idx += 1
            self._diag_lines = [
                (t, c, min(1.0, a + 0.08))
                for t, c, a in self._diag_lines
            ]
            if len(self._diag_lines) > 22:
                self._diag_lines = self._diag_lines[-22:]
            if (self._diag_idx >= len(self._boot_msgs)
                    and self._diag_timer >
                    len(self._boot_msgs) * 8 + 40):
                self._phase = self._PH_VOICE

        elif self._phase == self._PH_VOICE:
            self._voice_a = min(1.0, self._voice_a + 0.03)
            self._waveform.activate()
            if (self._voice_a >= 0.99
                    and self._tick % 200 > 120):
                self._voice_done = True
                self._waveform.deactivate()
                self._phase = self._PH_TITLE

        elif self._phase == self._PH_TITLE:
            self._title_a     = min(1.0, self._title_a + 0.04)
            self._title_timer += 1
            if (self._title_timer % 5 == 0
                    and self._title_chars < len(self._title_full)):
                self._title_chars += 1
            if self._title_chars >= len(self._title_full):
                self._sub_a = min(1.0, self._sub_a + 0.025)
            if (self._title_chars >= len(self._title_full)
                    and self._sub_a >= 0.99
                    and self._title_timer > 120):
                self._phase = self._PH_FADEOUT

        elif self._phase == self._PH_FADEOUT:
            self._fadeout = min(1.0, self._fadeout + 0.022)
            if self._fadeout >= 1.0:
                self._phase = self._PH_DONE
                self._tmr.stop()
                self.finished.emit()

        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H  = self.width(), self.height()
        cx, cy = W / 2, H / 2

        p.fillRect(self.rect(), qc(C.BG))
        if self._alpha < 1.0:
            p.fillRect(self.rect(),
                       qc("#000000", int(255*(1.0-self._alpha))))

        if self._phase >= self._PH_GRID:
            grad = QLinearGradient(
                0, self._scan_y-40, 0, self._scan_y+40
            )
            grad.setColorAt(0.0, qc(C.PRI, 0))
            grad.setColorAt(0.5, qc(C.PRI, int(18*self._grid_a)))
            grad.setColorAt(1.0, qc(C.PRI, 0))
            p.fillRect(
                QRectF(0, self._scan_y-40, W, 80), QBrush(grad)
            )

        if self._phase >= self._PH_GRID:
            self._grid.draw(p, int(22 * self._grid_a))

        for pt in self._particles:
            px, py, _, _, life, col = pt
            p.setBrush(QBrush(qc(col, int(180*life))))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(px, py), 2, 2)

        if self._phase >= self._PH_REACTOR:
            self._reactor.draw(
                p, cx, cy, min(W,H)*0.18, self._reactor_a
            )

        if self._phase >= self._PH_DIAG and self._diag_lines:
            panel_x = W * 0.55
            panel_y = H * 0.18
            panel_w = W * 0.40
            line_h  = 18.0
            pa      = int(180 * self._diag_a)

            p.setBrush(QBrush(qc("#000d14", pa)))
            p.setPen(QPen(qc(C.BORDER_B, pa), 1))
            p.drawRoundedRect(
                QRectF(panel_x-12, panel_y-8,
                       panel_w+24,
                       len(self._diag_lines)*line_h+24),
                4, 4
            )
            p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            p.setPen(QPen(qc(C.PRI_DIM, pa), 1))
            p.drawText(
                QRectF(panel_x-8, panel_y-6, panel_w, 12),
                Qt.AlignmentFlag.AlignLeft, "▸ SYSTEM BOOT LOG"
            )
            p.setPen(QPen(qc(C.BORDER_B, int(pa*0.5)), 1))
            p.drawLine(
                QPointF(panel_x-8,        panel_y+8),
                QPointF(panel_x+panel_w+8, panel_y+8)
            )

            color_map = {
                "pri":   C.PRI,   "green": C.GREEN,
                "dim":   C.TEXT_DIM, "acc2": C.ACC2,
                "teal":  C.TEAL,  "white": C.WHITE,
                "red":   C.RED,
            }
            p.setFont(QFont("Courier New", 8))
            for i, (txt, col_key, la) in enumerate(self._diag_lines):
                col    = color_map.get(col_key, C.TEXT)
                line_a = int(255 * la * self._diag_a)
                p.setPen(QPen(qc(col, line_a), 1))
                p.drawText(
                    QRectF(panel_x, panel_y+14+i*line_h,
                           panel_w, line_h),
                    Qt.AlignmentFlag.AlignLeft |
                    Qt.AlignmentFlag.AlignVCenter,
                    txt
                )
            if (self._diag_idx < len(self._boot_msgs)
                    and self._tick % 20 < 12):
                last_y = panel_y + 14 + len(self._diag_lines)*line_h
                p.setBrush(QBrush(qc(C.PRI, pa)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRect(QRectF(panel_x, last_y+3, 7, 11))

        if self._phase >= self._PH_VOICE:
            va    = int(255 * self._voice_a)
            vox_x = W * 0.08
            vox_y = H * 0.72
            vox_w = W * 0.36
            vox_h = 60.0

            p.setBrush(QBrush(qc("#000d14", int(va*0.85))))
            col_v = C.ACC2 if self._voice_done else C.GREEN
            p.setPen(QPen(qc(col_v, va), 1))
            p.drawRoundedRect(
                QRectF(vox_x-10, vox_y-30, vox_w+20, vox_h+50), 4, 4
            )
            label = (
                "VOICE PRINT CONFIRMED  ·  IDENTITY VERIFIED"
                if self._voice_done else
                "VOICE AUTHENTICATION  ·  SCANNING..."
            )
            p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            p.setPen(QPen(qc(col_v, va), 1))
            p.drawText(
                QRectF(vox_x, vox_y-22, vox_w, 16),
                Qt.AlignmentFlag.AlignCenter, label
            )
            self._waveform.draw(p, vox_x, vox_y, vox_w, vox_h, va)

            mid_x = vox_x + vox_w / 2
            mid_y = vox_y + vox_h / 2
            p.setPen(QPen(qc(col_v, int(va*0.5)), 0.8))
            p.drawLine(
                QPointF(mid_x-20, mid_y), QPointF(mid_x+20, mid_y)
            )
            p.drawLine(
                QPointF(mid_x, mid_y-10), QPointF(mid_x, mid_y+10)
            )

        if self._phase >= self._PH_TITLE:
            ta   = int(255 * self._title_a)
            disp = self._title_full[:self._title_chars]

            for i in range(8):
                ga = int(ta * 0.12 * (1 - i/8))
                p.setFont(QFont("Courier New", 56, QFont.Weight.Bold))
                p.setPen(QPen(qc(C.PRI, ga), (5 - i*0.4)*2))
                p.drawText(
                    QRectF(0, H*0.34, W, 90),
                    Qt.AlignmentFlag.AlignCenter, disp
                )

            p.setFont(QFont("Courier New", 52, QFont.Weight.Bold))
            p.setPen(QPen(qc(C.PRI, ta), 1))
            p.drawText(
                QRectF(0, H*0.34, W, 90),
                Qt.AlignmentFlag.AlignCenter, disp
            )

            if (self._title_chars < len(self._title_full)
                    and self._tick % 18 < 10):
                fm = p.fontMetrics()
                tw = fm.horizontalAdvance(disp)
                tx = (W - tw) / 2 + tw + 4
                ty = H * 0.34 + 16
                p.setBrush(QBrush(qc(C.PRI, ta)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRect(QRectF(tx, ty, 6, 48))

            if self._sub_a > 0:
                sa = int(255 * self._sub_a)
                p.setFont(QFont("Courier New", 10))
                p.setPen(QPen(qc(C.TEXT_DIM, sa), 1))
                p.drawText(
                    QRectF(0, H*0.34+100, W, 22),
                    Qt.AlignmentFlag.AlignCenter, self._subtitle
                )
                sub_fm = p.fontMetrics()
                sub_w  = sub_fm.horizontalAdvance(self._subtitle)
                sub_cx = W / 2
                line_y = H * 0.34 + 111
                margin = 20
                p.setPen(QPen(qc(C.BORDER_B, sa), 1))
                p.drawLine(
                    QPointF(sub_cx - sub_w/2 - margin - 60, line_y),
                    QPointF(sub_cx - sub_w/2 - margin, line_y)
                )
                p.drawLine(
                    QPointF(sub_cx + sub_w/2 + margin, line_y),
                    QPointF(sub_cx + sub_w/2 + margin + 60, line_y)
                )

            p.setFont(QFont("Courier New", 7))
            p.setPen(QPen(qc(C.TEXT_DIM, int(ta*0.6)), 1))
            p.drawText(
                QRectF(0, H-30, W, 20),
                Qt.AlignmentFlag.AlignCenter,
                "JARVIS  v3.0  ·  VINCEVISION INDUSTRIES  ·  CLASSIFIED"
            )

        if self._phase == self._PH_FADEOUT:
            p.fillRect(
                self.rect(), qc(C.BG, int(255*self._fadeout))
            )

        p.end()

    def keyPressEvent(self, e):  self._skip()
    def mousePressEvent(self, e): self._skip()

    def _skip(self):
        if self._phase < self._PH_FADEOUT:
            self._phase = self._PH_FADEOUT


# ══════════════════════════════════════════════════════════════════════════
#  TOOL EXECUTION HUD
# ══════════════════════════════════════════════════════════════════════════

class ToolExecutionHUD(QWidget):
    finished = pyqtSignal()

    def __init__(self, tool_name: str, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._tool_name  = tool_name
        self._status     = "INITIALIZING"
        self._progress   = 0.0
        self._logs: list[tuple[str, str]] = []
        self._alpha      = 0.0
        self._target_alpha = 1.0
        self._particles: list[list] = []
        self._tick       = 0
        self._pulse      = 0.0
        self._scan_angle = 0.0

        self.setFixedSize(600, 400)
        self._center_on_screen()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(16)

    def _center_on_screen(self):
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width()  - self.width())  // 2,
            (screen.height() - self.height()) // 2,
        )

    def _animate(self):
        self._tick += 1
        self._pulse      = (self._pulse      + 0.05) % (2 * math.pi)
        self._scan_angle = (self._scan_angle + 2)    % 360
        self._alpha     += (self._target_alpha - self._alpha) * 0.1

        if random.random() < 0.15:
            w, h = self.width(), self.height()
            self._particles.append([
                random.uniform(50, w-50), h + 10,
                random.uniform(-0.5, 0.5),
                random.uniform(-2, -4),
                1.0,
                random.choice([C.PRI, C.TEAL, C.GREEN, C.ACC2]),
            ])
        self._particles = [
            [p[0]+p[2], p[1]+p[3], p[2]*0.98, p[3]*0.98,
             p[4]-0.02, p[5]]
            for p in self._particles
            if p[4] > 0 and p[1] > -10
        ]
        self.update()

    def set_status(self, status: str):
        self._status = status
        self.update()

    def set_progress(self, progress: float):
        self._progress = max(0.0, min(1.0, progress))
        self.update()

    def add_log(self, text: str, color: str = C.TEXT):
        self._logs.append((text, color))
        if len(self._logs) > 8:
            self._logs.pop(0)
        self.update()

    def close_animated(self):
        self._target_alpha = 0.0
        QTimer.singleShot(500, self.close)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._alpha)

        W, H = self.width(), self.height()

        bg_grad = QLinearGradient(0, 0, 0, H)
        bg_grad.setColorAt(0.0, qc("#001018", 240))
        bg_grad.setColorAt(1.0, qc("#000d14", 240))
        p.setBrush(QBrush(bg_grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, 0, W, H), 8, 8)

        border_alpha = int(150 + 80 * math.sin(self._pulse))
        p.setPen(QPen(qc(C.PRI, border_alpha), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(1, 1, W-2, H-2), 8, 8)

        bracket_len = 25
        corners = [
            (8, 8, 1, 1), (W-8, 8, -1, 1),
            (8, H-8, 1, -1), (W-8, H-8, -1, -1),
        ]
        p.setPen(QPen(qc(C.PRI, 220), 2.5))
        for x, y, dx, dy in corners:
            p.drawLine(QPointF(x, y), QPointF(x + dx*bracket_len, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy*bracket_len))
            p.setBrush(QBrush(qc(C.PRI, 200)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x + dx*5, y + dy*5), 2.5, 2.5)
            p.setPen(QPen(qc(C.PRI, 220), 2.5))

        for pt in self._particles:
            p.setBrush(QBrush(qc(pt[5], int(pt[4]*180))))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(pt[0], pt[1]), 2, 2)

        scan_y = 60 + (H-120) * (math.sin(self._pulse)*0.5 + 0.5)
        grad   = QLinearGradient(0, scan_y-30, 0, scan_y+30)
        grad.setColorAt(0.0, qc(C.PRI, 0))
        grad.setColorAt(0.5, qc(C.PRI, 40))
        grad.setColorAt(1.0, qc(C.PRI, 0))
        p.fillRect(QRectF(0, scan_y-30, W, 60), QBrush(grad))

        p.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        p.setPen(QPen(qc(C.PRI_DIM, 180), 1))
        p.drawText(QRectF(20, 15, W-40, 20),
                   Qt.AlignmentFlag.AlignLeft, "◈ TOOL EXECUTION")

        p.setPen(QPen(qc(C.BORDER_B, 120), 1))
        p.drawLine(QPointF(20, 40), QPointF(W-20, 40))

        p.setFont(QFont("Courier New", 14, QFont.Weight.Bold))
        p.setPen(QPen(qc(C.PRI), 1))
        p.drawText(
            QRectF(20, 50, W-40, 30),
            Qt.AlignmentFlag.AlignCenter,
            self._tool_name.upper().replace("_", " ")
        )

        if self._tick % 60 < 30:
            sc = C.GREEN if self._status == "COMPLETE" else C.ACC2
            st = f"●  {self._status}"
        else:
            sc = C.GREEN_D if self._status == "COMPLETE" else C.ACC
            st = f"○  {self._status}"

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qc(sc), 1))
        p.drawText(QRectF(20, 90, W-40, 20),
                   Qt.AlignmentFlag.AlignCenter, st)

        bar_x, bar_y, bar_w, bar_h = 40, 120, W-80, 8
        p.setBrush(QBrush(qc(C.BAR_BG, 200)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 4, 4)

        if self._progress > 0:
            fw   = bar_w * self._progress
            grad = QLinearGradient(bar_x, bar_y, bar_x+fw, bar_y)
            grad.setColorAt(0.0, qc(C.PRI,  200))
            grad.setColorAt(0.5, qc(C.TEAL, 220))
            grad.setColorAt(1.0, qc(C.PRI,  200))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fw, bar_h), 4, 4)

            gg = QLinearGradient(bar_x, bar_y-3, bar_x, bar_y+bar_h+3)
            gg.setColorAt(0.0, qc(C.PRI, 0))
            gg.setColorAt(0.5, qc(C.PRI, 60))
            gg.setColorAt(1.0, qc(C.PRI, 0))
            p.setBrush(QBrush(gg))
            p.drawRoundedRect(
                QRectF(bar_x, bar_y-3, fw, bar_h+6), 4, 4
            )

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qc(C.PRI), 1))
        p.drawText(
            QRectF(bar_x, bar_y+12, bar_w, 16),
            Qt.AlignmentFlag.AlignCenter,
            f"{int(self._progress*100)}%"
        )

        log_y = 150
        log_h = H - log_y - 30
        p.setPen(QPen(qc(C.BORDER_B, 100), 1))
        p.setBrush(QBrush(qc(C.PANEL3, 150)))
        p.drawRoundedRect(QRectF(20, log_y, W-40, log_h), 4, 4)

        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qc(C.TEXT_DIM), 1))
        p.drawText(
            QRectF(28, log_y+4, W-56, 12),
            Qt.AlignmentFlag.AlignLeft, "▸ ACTIVITY"
        )
        p.setPen(QPen(qc(C.BORDER_B, 80), 1))
        p.drawLine(QPointF(28, log_y+18), QPointF(W-28, log_y+18))

        p.setFont(QFont("Courier New", 7))
        for i, (text, color) in enumerate(self._logs):
            alpha = int(200 * (1 - i * 0.1))
            p.setPen(QPen(qc(color, alpha), 1))
            if len(text) > 65:
                text = text[:62] + "..."
            p.drawText(
                QRectF(28, log_y+24+i*14, W-56, 14),
                Qt.AlignmentFlag.AlignLeft |
                Qt.AlignmentFlag.AlignVCenter,
                f"• {text}"
            )

        cr   = 12
        cx_c = W - 35
        cy_c = H - 35
        p.setPen(QPen(qc(C.PRI, 180), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(
            QRectF(cx_c-cr, cy_c-cr, cr*2, cr*2),
            int(self._scan_angle * 16), int(120 * 16)
        )
        p.end()


class ToolExecutionManager:
    def __init__(self, parent: QMainWindow):
        self._parent = parent
        self._current_hud: ToolExecutionHUD | None = None

    def start_tool(self, tool_name: str) -> ToolExecutionHUD:
        if self._current_hud:
            self._current_hud.close()
        self._current_hud = ToolExecutionHUD(tool_name, self._parent)
        self._current_hud.show()
        return self._current_hud

    def update_status(self, status: str):
        if self._current_hud:
            self._current_hud.set_status(status)

    def update_progress(self, progress: float):
        if self._current_hud:
            self._current_hud.set_progress(progress)

    def add_log(self, text: str, color: str = C.TEXT):
        if self._current_hud:
            self._current_hud.add_log(text, color)

    def finish_tool(self, success: bool = True):
        if self._current_hud:
            if success:
                self._current_hud.set_status("COMPLETE")
                self._current_hud.set_progress(1.0)
                self._current_hud.add_log(
                    "✓ Task completed successfully", C.GREEN
                )
            else:
                self._current_hud.set_status("FAILED")
                self._current_hud.add_log("✗ Task failed", C.RED)
            QTimer.singleShot(2000, self._current_hud.close_animated)
            self._current_hud = None


# ══════════════════════════════════════════════════════════════════════════
#  SETUP OVERLAY
# ══════════════════════════════════════════════════════════════════════════

class SetupOverlay(QWidget):
    done = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(0,6,10,248);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        detected    = {"darwin": "mac", "windows": "windows"}.get(
            _OS.lower(), "linux"
        )
        self._sel_os = detected
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 22, 30, 22)
        lay.setSpacing(8)

        def _lbl(txt, fs=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont(
                "Courier New", fs,
                QFont.Weight.Bold if bold else QFont.Weight.Normal
            ))
            w.setStyleSheet(
                f"color:{color};background:transparent;"
            )
            return w

        lay.addWidget(_lbl("◈  INITIALISATION REQUIRED", 13, True))
        lay.addWidget(_lbl(
            "Configure J.A.R.V.I.S. before first boot.", 9,
            color=C.PRI_DIM
        ))
        lay.addSpacing(6)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{C.BORDER};")
        lay.addWidget(sep)

        lay.addWidget(_lbl(
            "GEMINI API KEY", 8, color=C.TEXT_DIM,
            align=Qt.AlignmentFlag.AlignLeft
        ))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza…")
        self._key_input.setFont(QFont("Courier New", 10))
        self._key_input.setFixedHeight(32)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background:#000d12; color:{C.TEXT};
                border:1px solid {C.BORDER};
                border-radius:3px; padding:4px 8px;
            }}
            QLineEdit:focus {{ border:1px solid {C.PRI}; }}
        """)
        lay.addWidget(self._key_input)
        lay.addSpacing(10)

        lay.addWidget(_lbl(
            "OPERATING SYSTEM", 8, color=C.TEXT_DIM,
            align=Qt.AlignmentFlag.AlignLeft
        ))
        det_name = {"windows": "Windows", "mac": "macOS",
                    "linux": "Linux"}[detected]
        lay.addWidget(_lbl(
            f"Auto-detected: {det_name}", 8, color=C.ACC2,
            align=Qt.AlignmentFlag.AlignLeft
        ))

        os_row = QHBoxLayout()
        os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [
            ("windows", "⊞  Windows"),
            ("mac",     "  macOS"),
            ("linux",   "🐧  Linux"),
        ]:
            btn = QPushButton(label)
            btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        lay.addLayout(os_row)
        self._sel(detected)
        lay.addSpacing(12)

        init_btn = QPushButton("▸  INITIALISE SYSTEMS")
        init_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        init_btn.setFixedHeight(36)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background:transparent; color:{C.PRI};
                border:1px solid {C.PRI_DIM}; border-radius:3px;
            }}
            QPushButton:hover {{
                background:{C.PRI_GHO}; border:1px solid {C.PRI};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        lay.addWidget(init_btn)

    def _sel(self, key):
        self._sel_os = key
        pal = {
            "windows": (C.PRI,   "#001a22"),
            "mac":     (C.ACC2,  "#1a1400"),
            "linux":   (C.GREEN, "#001a0d"),
        }
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background:{fg}; color:{bg};
                        border:none; border-radius:3px;
                        font-weight:bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background:#000d12; color:{C.TEXT_DIM};
                        border:1px solid {C.BORDER};
                        border-radius:3px;
                    }}
                    QPushButton:hover {{
                        color:{C.TEXT};
                        border:1px solid {C.BORDER_B};
                    }}
                """)

    def _submit(self):
        key = self._key_input.text().strip()
        if not key:
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() +
                f" QLineEdit {{ border:1px solid {C.RED}; }}"
            )
            return
        self.done.emit(key, self._sel_os)


# ══════════════════════════════════════════════════════════════════════════
#  TECH MAP PANEL WRAPPER
# ══════════════════════════════════════════════════════════════════════════

class TechMapPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(380)
        self.setMinimumHeight(300)
        self.setStyleSheet(f"""
            TechMapPanel {{
                background: rgba(0,13,20,180);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(36)
        header.setStyleSheet(f"""
            QWidget {{
                background: rgba(0,13,20,200);
                border-bottom: 1px solid {C.BORDER_B};
                border-radius: 0px;
            }}
        """)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(10, 0, 10, 0)
        h_lay.setSpacing(6)

        title_lbl = QLabel("⬡  TECH MAP")
        title_lbl.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        title_lbl.setStyleSheet(
            f"color: {C.PRI}; background: transparent;"
        )
        h_lay.addWidget(title_lbl)
        h_lay.addStretch()

        self._layer_btns: dict[str, QPushButton] = {}
        layer_defs = [
            ("N", "network",    C.PRI),
            ("B", "bluetooth",  C.PURPLE),
            ("G", "geographic", C.TEAL),
            ("S", "security",   C.RED),
            ("T", "trading",    C.ACC2),
        ]
        for label, key, color in layer_defs:
            btn = QPushButton(label)
            btn.setFixedSize(22, 22)
            btn.setCheckable(True)
            btn.setChecked(key not in ("trading",))
            btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"Toggle {key.capitalize()} layer")
            self._style_layer_btn(btn, color, btn.isChecked())
            btn.clicked.connect(
                lambda checked, k=key, c=color, b=btn:
                    self._on_layer_toggle(k, c, b, checked)
            )
            h_lay.addWidget(btn)
            self._layer_btns[key] = btn

        outer.addWidget(header)

        TechMapWidget = _get_techmap_class()
        self._map = TechMapWidget()
        for key, btn in self._layer_btns.items():
            self._map._layers[key] = btn.isChecked()

        outer.addWidget(self._map, stretch=1)

    def _style_layer_btn(self, btn: QPushButton,
                         color: str, active: bool):
        if active:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {color};
                    color: #000d14;
                    border: none;
                    border-radius: 3px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background: {color};
                    opacity: 0.8;
                }}
            """)
        else:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {color};
                    border: 1px solid {color};
                    border-radius: 3px;
                }}
                QPushButton:hover {{
                    background: rgba(0,212,255,0.1);
                }}
            """)

    def _on_layer_toggle(self, key: str, color: str,
                         btn: QPushButton, checked: bool):
        self._style_layer_btn(btn, color, checked)
        self._map.toggle_layer(key)

    def cleanup(self):
        self._map.cleanup()


class HoloGlobePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(350)
        self.setMinimumHeight(300)
        self.setStyleSheet(f"""
            HoloGlobePanel {{
                background: rgba(0,13,20,180);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(30)
        header.setStyleSheet(f"""
            QWidget {{
                background: rgba(0,13,20,200);
                border-bottom: 1px solid {C.BORDER_B};
                border-radius: 0px;
            }}
        """)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(10, 0, 10, 0)
        h_lay.setSpacing(6)

        title_lbl = QLabel("🌐  HOLOGLOBE")
        title_lbl.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        title_lbl.setStyleSheet(
            f"color: {C.TEAL}; background: transparent;"
        )
        h_lay.addWidget(title_lbl)
        h_lay.addStretch()

        self._conn_lbl = QLabel("0 LINKS")
        self._conn_lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        self._conn_lbl.setStyleSheet(
            f"color: {C.PRI_DIM}; background: transparent;"
        )
        h_lay.addWidget(self._conn_lbl)

        outer.addWidget(header)

        HoloGlobeWidget = _get_hologlobe_class()
        self._globe = HoloGlobeWidget()
        self._globe._scanner.connections_updated.connect(
            self._on_conn_update
        )
        outer.addWidget(self._globe, stretch=1)

    def _on_conn_update(self, connections: list):
        self._conn_lbl.setText(f"{len(connections)} LINKS")

    def cleanup(self):
        self._globe.cleanup()


def _resolve_image_path(face_path: str | None) -> Path | None:
    if not face_path:
        return None

    raw = Path(face_path).expanduser()
    if raw.is_absolute():
        return raw if raw.exists() and raw.is_file() else None

    candidates = [
        BASE_DIR / raw,
        Path.cwd() / raw,
        Path.home() / raw,
    ]
    for p in candidates:
        resolved = p.resolve()
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


# ══════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ══════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    _log_sig     = pyqtSignal(str)
    _state_sig   = pyqtSignal(str)
    _metrics_sig = pyqtSignal(dict)

    # ── MAX LOG LINES — prevents unbounded memory growth ──────────────────
    _MAX_LOG_LINES = 500

    @staticmethod
    def _resolve_face_path(face_path: str | None) -> Path | None:
        return _resolve_image_path(face_path)

    def __init__(self, face_path: str):
        super().__init__()
        self._face_path = self._resolve_face_path(face_path)
        self.setWindowTitle("J.A.R.V.I.S — VINCEVISION")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        self.on_text_command: object = None
        self._muted         = False
        self._current_file: str | None = None
        self._drag_pos      = None
        self._log_line_count = 0

        # Background animation
        self._tick   = 0
        self._scan_y = 0.0
        self._grid   = _HexGrid(screen.width(), screen.height(), 38)
        self._reactor  = _ArcReactor()
        self._waveform = _LaunchWaveform(48)
        self._particles: list[list] = []

        self._sys_initialized = False

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        central.paintEvent = self._paint_background  # type: ignore
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header(), stretch=0)
        root.addWidget(self._build_body(),   stretch=1)
        root.addWidget(self._build_footer(), stretch=0)

        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.start(16)

        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)

        self._log_sig.connect(self._append_log)
        self._state_sig.connect(self._apply_state)
        self._metrics_sig.connect(self._update_sys_panel)

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        self._tool_manager = ToolExecutionManager(self)

        if not self._ready:
            QTimer.singleShot(200, self._show_setup)
        else:
            QTimer.singleShot(500, self._init_system_monitor)

        QShortcut(QKeySequence("F4"),
                  self).activated.connect(self._toggle_mute)
        QShortcut(QKeySequence("F11"),
                  self).activated.connect(self._toggle_fullscreen)
        QShortcut(QKeySequence("Escape"),
                  self).activated.connect(self._toggle_fullscreen)

        self._wire_layer_shortcuts()

    def _wire_layer_shortcuts(self):
        layer_keys = {
            "F1": "network",
            "F2": "bluetooth",
            "F3": "geographic",
            "F5": "security",
            "F6": "trading",
        }
        for key, layer in layer_keys.items():
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(
                lambda l=layer: self._toggle_layer_shortcut(l)
            )

    def _toggle_layer_shortcut(self, layer: str):
        if not hasattr(self, '_techmap_panel'):
            return
        btn = self._techmap_panel._layer_btns.get(layer)
        if btn:
            btn.setChecked(not btn.isChecked())
            btn.clicked.emit(btn.isChecked())

    @property
    def tool_manager(self):
        return self._tool_manager

    def _animate(self):
        self._tick   += 1
        self._scan_y  = (self._scan_y + 2.5) % self.height()
        self._reactor.step()
        self._waveform.step()

        if random.random() < 0.05:
            W, H = self.width(), self.height()
            ang  = random.uniform(0, 2 * math.pi)
            spd  = random.uniform(0.3, 2.0)
            self._particles.append([
                W/2, H/2,
                math.cos(ang) * spd, math.sin(ang) * spd,
                1.0,
                random.choice([C.PRI, C.TEAL, C.GREEN, C.ACC2]),
            ])
        self._particles = [
            [p[0]+p[2], p[1]+p[3], p[2]*0.97, p[3]*0.97,
             p[4]-0.013, p[5]]
            for p in self._particles if p[4] > 0
        ]
        self.centralWidget().update()

    def _paint_background(self, _):
        p = QPainter(self.centralWidget())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        p.fillRect(self.centralWidget().rect(), qc(C.BG))

        grad = QLinearGradient(
            0, self._scan_y-40, 0, self._scan_y+40
        )
        grad.setColorAt(0.0, qc(C.PRI, 0))
        grad.setColorAt(0.5, qc(C.PRI, 15))
        grad.setColorAt(1.0, qc(C.PRI, 0))
        p.fillRect(
            QRectF(0, self._scan_y-40, W, 80), QBrush(grad)
        )

        self._grid.draw(p, 18)

        for pt in self._particles:
            px, py, _, _, life, col = pt
            p.setBrush(QBrush(qc(col, int(180*life))))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(px, py), 2, 2)

        self._reactor.draw(p, W/2, H/2, min(W,H)*0.12, 0.8)
        p.end()

    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(60)
        w.setStyleSheet(
            f"background: rgba(0,13,20,220); "
            f"border-bottom: 1px solid {C.BORDER_B};"
        )
        lay = QHBoxLayout(w)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(12)

        self._face_label = QLabel()
        self._face_label.setFixedSize(42, 42)
        self._face_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._face_label.setStyleSheet(
            "background: rgba(0,13,20,180); border: 1px solid #0f4060; border-radius: 21px;"
        )
        if self._face_path is not None:
            pixmap = QPixmap(str(self._face_path))
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    42, 42,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._face_label.setPixmap(pixmap)
            else:
                self._face_label.setText("◉")
                self._face_label.setStyleSheet(
                    f"color: {C.PRI}; background: transparent; font-size: 18px;"
                )
        else:
            self._face_label.setText("◉")
            self._face_label.setStyleSheet(
                f"color: {C.PRI}; background: transparent; font-size: 18px;"
            )
        lay.addWidget(self._face_label)

        title = QLabel("◈  J · A · R · V · I · S  ◈")
        title.setFont(QFont("Courier New", 20, QFont.Weight.Bold))
        title.setStyleSheet(
            f"color: {C.PRI}; background: transparent;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title, stretch=1)

        return w

    def _build_body(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")

        main_lay = QVBoxLayout(w)
        main_lay.setContentsMargins(20, 10, 20, 10)
        main_lay.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self._sys_panel = self._create_static_panel(
            "◈ SYSTEM MONITOR", 280, 300
        )
        top_row.addWidget(self._sys_panel)

        self._log_panel = self._create_log_panel(
            "◈ ACTIVITY LOG", 0, 300
        )
        top_row.addWidget(self._log_panel, stretch=1)

        self._techmap_panel = TechMapPanel()
        top_row.addWidget(self._techmap_panel, stretch=2)

        main_lay.addLayout(top_row)

        self._response_panel = self._create_typing_panel(
            "◈ RESPONSE", 0, 160
        )
        main_lay.addWidget(self._response_panel)

        input_row = QHBoxLayout()
        input_row.setSpacing(10)

        self._mute_btn = QPushButton("🎙")
        self._mute_btn.setFixedSize(40, 40)
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        input_row.addWidget(self._mute_btn)

        self._input = QLineEdit()
        self._input.setPlaceholderText("◢ ENTER COMMAND...")
        self._input.setFont(QFont("Courier New", 12))
        self._input.setFixedHeight(40)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(1,13,20,200);
                color: {C.WHITE};
                border: 2px solid {C.BORDER_B};
                border-radius: 4px;
                padding: 8px 12px;
            }}
            QLineEdit:focus {{
                border: 2px solid {C.PRI};
            }}
        """)
        self._input.returnPressed.connect(self._send)
        input_row.addWidget(self._input)

        send_btn = QPushButton("▸  EXECUTE")
        send_btn.setFixedSize(120, 40)
        send_btn.setFont(QFont("Courier New", 10, QFont.Weight.Bold))
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PRI_DIM};
                color: {C.BG};
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background: {C.PRI};
            }}
        """)
        send_btn.clicked.connect(self._send)
        input_row.addWidget(send_btn)

        main_lay.addLayout(input_row)

        return w

    # ── Panel factories ────────────────────────────────────────────────────

    def _panel_base(self, title: str, min_w: int,
                    min_h: int) -> tuple[QWidget, QVBoxLayout]:
        """Create the styled outer panel shell. Returns (panel, inner_lay)."""
        panel = QWidget()
        if min_w: panel.setMinimumWidth(min_w)
        if min_h: panel.setMinimumHeight(min_h)
        panel.setStyleSheet(f"""
            QWidget {{
                background: rgba(0,13,20,180);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        lbl = QLabel(title)
        lbl.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"color: {C.PRI_DIM}; background: transparent;"
        )
        lay.addWidget(lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER_B};")
        lay.addWidget(sep)

        return panel, lay

    def _make_textedit(self) -> QTextEdit:
        content = QTextEdit()
        content.setReadOnly(True)
        content.setFont(QFont("Courier New", 9))
        content.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                color: {C.TEXT};
                border: none;
            }}
            QScrollBar:vertical {{
                background: transparent; width: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B}; border-radius: 3px;
            }}
        """)
        return content

    def _create_static_panel(self, title: str,
                             min_w: int, min_h: int) -> QWidget:
        panel, lay = self._panel_base(title, min_w, min_h)
        content = self._make_textedit()
        lay.addWidget(content)
        setattr(panel, '_content', content)
        return panel

    def _create_log_panel(self, title: str,
                          min_w: int, min_h: int) -> QWidget:
        """
        Log panel — instant rendering, no typing animation.
        Has a line-count cap to prevent memory bloat.
        """
        panel, lay = self._panel_base(title, min_w, min_h)
        content = self._make_textedit()
        lay.addWidget(content)
        setattr(panel, '_content', content)
        setattr(panel, '_line_count', 0)
        return panel

    def _create_typing_panel(self, title: str,
                             min_w: int, min_h: int) -> QWidget:
        """Response panel — fast typing animation (5 chars per tick)."""
        panel, lay = self._panel_base(title, min_w, min_h)
        content = self._make_textedit()
        lay.addWidget(content)
        setattr(panel, '_content',       content)
        setattr(panel, '_typing_queue',  [])
        setattr(panel, '_typing',        False)
        setattr(panel, '_current_line',  "")
        setattr(panel, '_current_pos',   0)
        setattr(panel, '_current_color', C.TEXT)
        return panel

    # ── System monitor ─────────────────────────────────────────────────────

    def _init_system_monitor(self):
        lines = [
            ("INITIALIZING SYSTEM MONITOR...", C.PRI),
            ("", C.TEXT),
            ("CPU  : --.--%", C.PRI),
            ("MEM  : --.--%", C.ACC2),
            ("NET  : ------", C.GREEN),
            ("GPU  : --.--%", C.ACC),
            ("TEMP : --.-°C", C.TEAL),
            ("", C.TEXT),
            ("MONITORING ACTIVE", C.GREEN),
        ]
        for text, color in lines:
            self._type_to_sys_panel(text, color)
        QTimer.singleShot(2000, self._start_metrics_updates)

    def _start_metrics_updates(self):
        self._sys_initialized = True
        self._update_metrics()

    def _type_to_sys_panel(self, text: str, color: str):
        content = getattr(self._sys_panel, '_content')
        cur = content.textCursor()
        fmt = cur.charFormat()
        fmt.setForeground(QBrush(qc(color)))
        cur.movePosition(cur.MoveOperation.End)
        cur.insertText(text + "\n", fmt)
        content.setTextCursor(cur)

    # ── Log panel — INSTANT rendering ─────────────────────────────────────

    def _append_log_instant(self, text: str, color: str):
        """
        Instantly append a line to the log panel.
        No character-by-character typing — zero delay.
        Caps at _MAX_LOG_LINES to prevent memory bloat.
        """
        content = getattr(self._log_panel, '_content')
        line_count = getattr(self._log_panel, '_line_count', 0)

        # If over cap, clear the oldest half
        if line_count >= self._MAX_LOG_LINES:
            content.clear()
            setattr(self._log_panel, '_line_count', 0)
            line_count = 0

        cur = content.textCursor()
        fmt = cur.charFormat()
        fmt.setForeground(QBrush(qc(color)))
        cur.movePosition(cur.MoveOperation.End)
        cur.insertText(text + "\n", fmt)
        content.setTextCursor(cur)
        content.ensureCursorVisible()
        setattr(self._log_panel, '_line_count', line_count + 1)

    # ── Response panel — FAST typing ──────────────────────────────────────

    def _type_to_panel(self, panel: QWidget,
                       text: str, color: str = C.TEXT):
        queue = getattr(panel, '_typing_queue')
        queue.append((text, color))
        if not getattr(panel, '_typing'):
            self._process_next_line(panel)

    def _process_next_line(self, panel: QWidget):
        queue = getattr(panel, '_typing_queue')
        if not queue:
            setattr(panel, '_typing', False)
            return
        setattr(panel, '_typing', True)
        text, color = queue.pop(0)
        setattr(panel, '_current_line',  text)
        setattr(panel, '_current_pos',   0)
        setattr(panel, '_current_color', color)
        tmr = QTimer(panel)
        tmr.timeout.connect(lambda: self._type_char(panel, tmr))
        setattr(panel, '_type_timer', tmr)
        tmr.start(8)  # 8ms tick — fast but visible

    def _type_char(self, panel: QWidget, timer: QTimer):
        content = getattr(panel, '_content')
        line    = getattr(panel, '_current_line')
        pos     = getattr(panel, '_current_pos')
        color   = getattr(panel, '_current_color')

        # ── 5 characters per tick — 5x faster than original ──────────
        chars_per_tick = 5
        end_pos = min(pos + chars_per_tick, len(line))

        if pos < len(line):
            chunk = line[pos:end_pos]
            cur   = content.textCursor()
            fmt   = cur.charFormat()
            fmt.setForeground(QBrush(qc(color)))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(chunk, fmt)
            content.setTextCursor(cur)
            content.ensureCursorVisible()
            setattr(panel, '_current_pos', end_pos)
        else:
            timer.stop()
            cur = content.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            content.setTextCursor(cur)
            # Minimal pause between lines
            QTimer.singleShot(2, lambda: self._process_next_line(panel))

    # ── System metrics panel ───────────────────────────────────────────────

    def _update_sys_panel(self, metrics: dict):
        if not self._sys_initialized:
            return
        content = getattr(self._sys_panel, '_content')
        cpu = metrics["cpu"]
        mem = metrics["mem"]
        net = metrics["net"]
        gpu = metrics["gpu"]
        tmp = metrics["tmp"]

        net_str = (f"{net*1024:.0f}KB/s"
                   if net < 1.0 else f"{net:.1f}MB/s")

        lines = [
            ("SYSTEM MONITOR",     C.PRI),
            ("",                   C.TEXT),
            (f"CPU  : {cpu:5.1f}%  {'█'*int(cpu/10)}",
             C.RED if cpu > 80 else C.PRI),
            (f"MEM  : {mem:5.1f}%  {'█'*int(mem/10)}",
             C.RED if mem > 80 else C.ACC2),
            (f"NET  : {net_str:>10}  "
             f"{'█'*int(min(100,net*10)/10)}", C.GREEN),
        ]
        if gpu >= 0:
            lines.append((
                f"GPU  : {gpu:5.1f}%  {'█'*int(gpu/10)}",
                C.RED if gpu > 80 else C.ACC
            ))
        if tmp >= 0:
            lines.append((
                f"TEMP : {tmp:5.1f}°C  "
                f"{'█'*int(min(100,tmp)/10)}",
                C.RED if tmp > 70 else C.TEAL
            ))
        lines.append(("", C.TEXT))
        lines.append(("MONITORING ACTIVE", C.GREEN))

        content.clear()
        cur = content.textCursor()
        for line, color in lines:
            fmt = cur.charFormat()
            fmt.setForeground(QBrush(qc(color)))
            cur.insertText(line + "\n", fmt)
        content.setTextCursor(cur)

    # ── Footer ─────────────────────────────────────────────────────────────

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(24)
        w.setStyleSheet(
            f"background: rgba(0,13,20,220); "
            f"border-top: 1px solid {C.BORDER};"
        )
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 0, 12, 0)

        self._status_lbl = QLabel("SYSTEM STATUS: INITIALIZING")
        self._status_lbl.setFont(QFont("Courier New", 7))
        self._status_lbl.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent;"
        )
        lay.addWidget(self._status_lbl)
        lay.addStretch()

        time_lbl = QLabel()
        time_lbl.setFont(QFont("Courier New", 7))
        time_lbl.setStyleSheet(
            f"color: {C.PRI}; background: transparent;"
        )
        lay.addWidget(time_lbl)

        def _tick():
            time_lbl.setText(time.strftime("%H:%M:%S"))

        tmr = QTimer(w)
        tmr.timeout.connect(_tick)
        tmr.start(1000)
        _tick()
        return w

    # ── Metrics ────────────────────────────────────────────────────────────

    def _update_metrics(self):
        self._metrics_sig.emit(_metrics.snapshot())

    # ── Log — INSTANT, no typing queue ────────────────────────────────────

    def _append_log(self, text: str):
        """
        Main log entry point.
        Instant rendering — no typing animation, no queue, no delay.
        """
        ts        = time.strftime("[%H:%M:%S]")
        full_text = f"{ts} {text}"
        tl        = text.lower()

        if   "you:"    in tl or "[you]"  in tl: color = C.WHITE
        elif "jarvis:" in tl or "[ai]"   in tl: color = C.PRI
        elif "error"   in tl or "fail"   in tl: color = C.RED
        elif "success" in tl or "complete" in tl: color = C.GREEN
        elif "warning" in tl:                    color = C.ACC2
        else:                                     color = C.TEXT_MED

        # INSTANT — no delay, no queue, no typing animation
        self._append_log_instant(full_text, color)

    # ── State ──────────────────────────────────────────────────────────────

    def _apply_state(self, state: str):
        color_map = {
            "LISTENING":  C.GREEN,
            "THINKING":   C.ACC2,
            "PROCESSING": C.ACC2,
            "SPEAKING":   C.ACC,
            "MUTED":      C.MUTED_C,
        }
        color = color_map.get(state, C.PRI)
        self._status_lbl.setText(
            f"SYSTEM STATUS: {state}  ·  "
            f"VINCEVISION INDUSTRIES  ·  CLASSIFIED"
        )
        self._status_lbl.setStyleSheet(
            f"color: {color}; background: transparent;"
        )
        # State goes to the response panel with fast typing
        self._type_to_panel(
            self._response_panel, f"◈ STATUS: {state}", color
        )

    # ── Input ──────────────────────────────────────────────────────────────

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(
                target=self.on_text_command,
                args=(txt,), daemon=True
            ).start()

    # ── Mute ───────────────────────────────────────────────────────────────

    def _toggle_mute(self):
        self._muted = not self._muted
        self._style_mute_btn()
        self._append_log(
            "SYSTEM: Microphone muted."
            if self._muted else
            "SYSTEM: Microphone active."
        )
        self._apply_state("MUTED" if self._muted else "LISTENING")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #140006; color: {C.MUTED_C};
                    border: 2px solid {C.MUTED_C}; border-radius: 4px;
                }}
            """)
        else:
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #00140a; color: {C.GREEN};
                    border: 2px solid {C.GREEN}; border-radius: 4px;
                }}
                QPushButton:hover {{ background: #001f10; }}
            """)

    # ── Fullscreen ─────────────────────────────────────────────────────────

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            screen = QApplication.primaryScreen().geometry()
            self.setGeometry(screen)
            self.showFullScreen()

    # ── Config ─────────────────────────────────────────────────────────────

    def _check_config(self) -> bool:
        if not API_FILE.exists(): return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return (bool(d.get("gemini_api_key"))
                    and bool(d.get("os_system")))
        except: return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 460, 390
        ov.setGeometry(
            (cw.width()-ow)//2, (cw.height()-oh)//2, ow, oh
        )
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    def _on_setup_done(self, key: str, os_name: str):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        API_FILE.write_text(
            json.dumps(
                {"gemini_api_key": key, "os_system": os_name},
                indent=4
            ),
            encoding="utf-8"
        )
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        self._append_log(
            f"SYSTEM: Initialised. OS={os_name.upper()}. JARVIS online."
        )
        QTimer.singleShot(500, self._init_system_monitor)

    # ── Resize / drag ──────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 390
            cw = self.centralWidget()
            self._overlay.setGeometry(
                (cw.width()-ow)//2, (cw.height()-oh)//2, ow, oh
            )

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                e.globalPosition().toPoint()
                - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, e):
        if (self._drag_pos
                and e.buttons() == Qt.MouseButton.LeftButton):
            self.move(
                e.globalPosition().toPoint() - self._drag_pos
            )

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    @property
    def current_file(self) -> str | None:
        return self._current_file


# ══════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════════════

class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class JarvisUI:
    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win    = MainWindow(face_path)
        self._launch = LaunchScreen()
        self._launch.showFullScreen()
        self._launch.finished.connect(self._on_launch_done)
        self.root = _RootShim(self._app)

    def _on_launch_done(self):
        self._win.showFullScreen()
        QTimer.singleShot(200, self._launch.close)

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win.current_file

    @property
    def tool_manager(self):
        return self._win.tool_manager

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)