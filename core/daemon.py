import asyncio
import threading
import subprocess
import re
import time
import json
import os
import platform
from pathlib import Path
from datetime import datetime

OS = platform.system()


class JarvisDaemon:
    """
    Background Monitoring Layer.
    Runs persistent watchers that monitor the system
    and alert JARVIS proactively when something happens.
    """

    def __init__(self, jarvis_instance):
        self.jarvis         = jarvis_instance
        self.running        = True
        self._thread        = None
        self._loop          = None
        self._ghost_procs   = {}       # port -> subprocess.Popen
        self._watchers      = {}       # name -> {"running": bool, "config": dict}
        self._alerts_log    = []       # recent alerts
        self._known_devices = set()
        self._known_ports   = set()
        self._first_scan    = True
        self._log_dir       = Path("/tmp/jarvis_daemon") if OS != "Windows" \
                              else Path(os.environ.get("TEMP", "C:\\Temp")) / "jarvis_daemon"
        self._log_dir.mkdir(parents=True, exist_ok=True)

    # ─────────────────────────────────────────────────────────────────────────
    # LOGGING
    # ─────────────────────────────────────────────────────────────────────────
    def _log(self, msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        full = f"[DAEMON {timestamp}] {msg}"
        print(full)
        try:
            self.jarvis.ui.write_log(full[:200])
        except Exception:
            pass

    def _alert(self, msg: str, speak: bool = True):
        """Send an alert — log it and optionally speak it."""
        self._log(f"⚠️ ALERT: {msg}")
        self._alerts_log.append({
            "time": datetime.now().isoformat(),
            "message": msg
        })
        # Keep last 50 alerts
        if len(self._alerts_log) > 50:
            self._alerts_log = self._alerts_log[-50:]
        if speak:
            try:
                self.jarvis.speak(msg)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # NETWORK WATCHER — detects new devices on your LAN
    # ─────────────────────────────────────────────────────────────────────────
    async def network_watcher(self):
        """Monitor for new devices joining the local network."""
        self._log("Network Watcher started.")
        self._watchers["network"] = {"running": True}

        while self.running:
            try:
                if OS == "Windows":
                    res = subprocess.check_output(
                        ["arp", "-a"], text=True, timeout=10
                    )
                    current = set(re.findall(r"([\d\.]+)\s+", res))
                else:
                    res = subprocess.check_output(
                        ["arp", "-a"], text=True, timeout=10
                    )
                    current = set(re.findall(r"\(([\d\.]+)\)", res))

                # Filter out broadcast/multicast
                current = {
                    ip for ip in current
                    if not ip.endswith(".255") and not ip.startswith("224.")
                }

                if self._first_scan:
                    self._known_devices = current
                    self._first_scan = False
                    self._log(
                        f"Network baseline: {len(current)} devices"
                    )
                else:
                    new_devices = current - self._known_devices
                    gone_devices = self._known_devices - current

                    for ip in new_devices:
                        # Try to get hostname
                        hostname = ""
                        try:
                            import socket
                            hostname = socket.gethostbyaddr(ip)[0]
                        except Exception:
                            pass

                        device_str = f"{ip}"
                        if hostname:
                            device_str += f" ({hostname})"

                        self._alert(
                            f"Sir, a new device joined the network: "
                            f"{device_str}",
                            speak=True
                        )

                    for ip in gone_devices:
                        self._log(f"Device left: {ip}")

                    self._known_devices = current

            except Exception as e:
                self._log(f"Network watch error: {e}")

            await asyncio.sleep(45)

    # ─────────────────────────────────────────────────────────────────────────
    # PORT SENTRY — detects new listening ports on YOUR machine
    # ─────────────────────────────────────────────────────────────────────────
    async def port_sentry(self):
        """Monitor for new listening ports on this machine."""
        self._log("Port Sentry started.")
        self._watchers["port_sentry"] = {"running": True}

        # Known safe ports to ignore on first detection
        SAFE_PORTS = {22, 53, 80, 443, 631, 5353, 8080}
        first_run = True

        while self.running:
            try:
                current_ports = set()

                if OS == "Linux":
                    res = subprocess.check_output(
                        ["ss", "-tulnp"], text=True, timeout=10
                    )
                    for line in res.strip().split("\n")[1:]:
                        match = re.search(r":(\d+)\s", line)
                        if match:
                            current_ports.add(int(match.group(1)))
                elif OS == "Darwin":
                    res = subprocess.check_output(
                        ["lsof", "-i", "-P", "-n"], text=True, timeout=10
                    )
                    for line in res.split("\n"):
                        if "LISTEN" in line:
                            match = re.search(r":(\d+)\s", line)
                            if match:
                                current_ports.add(int(match.group(1)))
                else:
                    res = subprocess.check_output(
                        ["netstat", "-ano"], text=True, timeout=10
                    )
                    for line in res.split("\n"):
                        if "LISTENING" in line:
                            match = re.search(r":(\d+)\s", line)
                            if match:
                                current_ports.add(int(match.group(1)))

                if first_run:
                    self._known_ports = current_ports
                    first_run = False
                    self._log(
                        f"Port baseline: {len(current_ports)} listening"
                    )
                else:
                    new_ports = current_ports - self._known_ports

                    for port in new_ports:
                        if port in SAFE_PORTS:
                            continue

                        # Try to identify what opened it
                        process_info = ""
                        try:
                            if OS == "Linux":
                                pid_res = subprocess.check_output(
                                    f"ss -tlnp | grep :{port}",
                                    shell=True, text=True, timeout=5
                                )
                                process_info = pid_res.strip()[:100]
                        except Exception:
                            pass

                        self._alert(
                            f"Warning sir, new listening port detected: "
                            f"{port}. {process_info}",
                            speak=True
                        )

                    closed_ports = self._known_ports - current_ports
                    for port in closed_ports:
                        self._log(f"Port closed: {port}")

                    self._known_ports = current_ports

            except Exception as e:
                self._log(f"Port sentry error: {e}")

            await asyncio.sleep(20)

    # ─────────────────────────────────────────────────────────────────────────
    # GHOST MODE — background listeners / traps / honeypots
    # ─────────────────────────────────────────────────────────────────────────
    def start_ghost_listener(self, port: int = 4444, protocol: str = "tcp") -> str:
        """Start a background netcat listener on a port."""
        if port in self._ghost_procs:
            return f"Ghost listener already running on port {port}."

        log_file = self._log_dir / f"ghost_{port}.log"

        if OS == "Windows":
            cmd = f"ncat -lvnp {port}"
        else:
            cmd = f"nc -lvnp {port}"

        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdout=open(log_file, "w"),
                stderr=subprocess.STDOUT,
                preexec_fn=os.setpgrp if OS != "Windows" else None,
            )
            self._ghost_procs[port] = {
                "process": proc,
                "log":     str(log_file),
                "started": datetime.now().isoformat(),
                "pid":     proc.pid,
            }
            self._log(f"👻 Ghost listener started on port {port} (PID: {proc.pid})")
            return (
                f"Ghost listener active on port {port}. "
                f"PID: {proc.pid}. Log: {log_file}"
            )
        except Exception as e:
            return f"Failed to start ghost listener: {e}"

    def stop_ghost_listener(self, port: int = 4444) -> str:
        """Stop a background ghost listener."""
        info = self._ghost_procs.pop(port, None)
        if not info:
            return f"No ghost listener on port {port}."
        try:
            info["process"].terminate()
            info["process"].wait(timeout=5)
        except Exception:
            try:
                info["process"].kill()
            except Exception:
                pass
        self._log(f"👻 Ghost listener stopped on port {port}")
        return f"Ghost listener on port {port} stopped."

    def check_ghost_listener(self, port: int = 4444) -> str:
        """Check if a ghost listener has caught anything."""
        info = self._ghost_procs.get(port)
        if not info:
            return f"No ghost listener on port {port}."

        log_path = Path(info["log"])
        if not log_path.exists():
            return f"Ghost on port {port} — no log file yet."

        content = log_path.read_text(errors="ignore").strip()
        if not content:
            return (
                f"Ghost on port {port} — listening since "
                f"{info['started']}. No connections yet."
            )

        # Check for connection indicators
        connection_keywords = [
            "connect", "received", "accept", "connection from"
        ]
        has_connection = any(
            kw in content.lower() for kw in connection_keywords
        )

        if has_connection:
            return (
                f"🚨 CONNECTION DETECTED on port {port}!\n"
                f"Since: {info['started']}\n"
                f"Log:\n{content[:1500]}"
            )

        return (
            f"Ghost on port {port} — listening since "
            f"{info['started']}.\n"
            f"Log so far:\n{content[:500]}"
        )

    def list_ghost_listeners(self) -> str:
        """List all active ghost listeners."""
        if not self._ghost_procs:
            return "No active ghost listeners."
        lines = ["[ACTIVE GHOST LISTENERS]"]
        for port, info in self._ghost_procs.items():
            alive = info["process"].poll() is None
            status = "🟢 ACTIVE" if alive else "🔴 DEAD"
            lines.append(
                f"  • Port {port} — {status} — "
                f"PID: {info['pid']} — Since: {info['started']}"
            )
        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────────────
    # HONEYPOT — fake service that logs connection attempts
    # ─────────────────────────────────────────────────────────────────────────
    def start_honeypot(self, port: int = 8888, banner: str = "SSH-2.0-OpenSSH_8.9") -> str:
        """Start a Python honeypot that mimics a service and logs connections."""
        log_file = self._log_dir / f"honeypot_{port}.log"

        honeypot_code = f'''
import socket
import datetime
import sys

LOG = open("{log_file}", "a")
BANNER = "{banner}\\n"

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{{ts}}] {{msg}}"
    print(line)
    LOG.write(line + "\\n")
    LOG.flush()

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("0.0.0.0", {port}))
s.listen(5)
log(f"Honeypot listening on port {port}")

while True:
    try:
        conn, addr = s.accept()
        log(f"CONNECTION from {{addr[0]}}:{{addr[1]}}")
        try:
            conn.send(BANNER.encode())
            data = conn.recv(1024)
            if data:
                log(f"RECEIVED from {{addr[0]}}: {{data.decode(errors='ignore').strip()}}")
        except:
            pass
        conn.close()
    except KeyboardInterrupt:
        break
    except Exception as e:
        log(f"Error: {{e}}")
'''
        script_path = self._log_dir / f"honeypot_{port}.py"
        script_path.write_text(honeypot_code)

        try:
            proc = subprocess.Popen(
                [sys.executable, str(script_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setpgrp if OS != "Windows" else None,
            )
            self._ghost_procs[f"honeypot_{port}"] = {
                "process": proc,
                "log":     str(log_file),
                "started": datetime.now().isoformat(),
                "pid":     proc.pid,
                "type":    "honeypot",
            }
            self._log(f"🍯 Honeypot started on port {port} (PID: {proc.pid})")
            return (
                f"Honeypot active on port {port} with banner '{banner}'. "
                f"PID: {proc.pid}. Log: {log_file}"
            )
        except Exception as e:
            return f"Failed to start honeypot: {e}"

    # ─────────────────────────────────────────────────────────────────────────
    # FILE SYSTEM WATCHER — monitors critical files for changes
    # ─────────────────────────────────────────────────────────────────────────
    async def file_watcher(self):
        """Monitor critical system files for unauthorized changes."""
        self._log("File Watcher started.")
        self._watchers["file_watcher"] = {"running": True}

        # Files to watch
        WATCH_FILES = []
        if OS == "Linux":
            WATCH_FILES = [
                "/etc/passwd",
                "/etc/shadow",
                "/etc/hosts",
                "/etc/crontab",
                "/etc/sudoers",
                "/root/.bashrc",
                "/root/.ssh/authorized_keys",
            ]
        elif OS == "Darwin":
            WATCH_FILES = [
                "/etc/passwd",
                "/etc/hosts",
                "/etc/sudoers",
            ]

        # Get initial state
        file_state = {}
        for fp in WATCH_FILES:
            p = Path(fp)
            if p.exists():
                try:
                    stat = p.stat()
                    file_state[fp] = {
                        "mtime": stat.st_mtime,
                        "size":  stat.st_size,
                    }
                except Exception:
                    pass

        while self.running:
            for fp in WATCH_FILES:
                p = Path(fp)
                if not p.exists():
                    continue
                try:
                    stat = p.stat()
                    current = {
                        "mtime": stat.st_mtime,
                        "size":  stat.st_size,
                    }
                    prev = file_state.get(fp)
                    if prev and (
                        current["mtime"] != prev["mtime"]
                        or current["size"] != prev["size"]
                    ):
                        self._alert(
                            f"Critical file modified: {fp}! "
                            f"Size: {prev['size']}→{current['size']}",
                            speak=True
                        )
                    file_state[fp] = current
                except Exception:
                    pass

            await asyncio.sleep(30)

    # ─────────────────────────────────────────────────────────────────────────
    # LOGIN WATCHER — detects new SSH/login sessions
    # ─────────────────────────────────────────────────────────────────────────
    async def login_watcher(self):
        """Monitor for new login sessions."""
        self._log("Login Watcher started.")
        self._watchers["login_watcher"] = {"running": True}

        known_sessions = set()
        first_run = True

        while self.running:
            try:
                if OS in ("Linux", "Darwin"):
                    res = subprocess.check_output(
                        ["who"], text=True, timeout=5
                    )
                    current = set(res.strip().split("\n")) if res.strip() else set()

                    if first_run:
                        known_sessions = current
                        first_run = False
                    else:
                        new_sessions = current - known_sessions
                        for session in new_sessions:
                            if session.strip():
                                self._alert(
                                    f"New login session detected: {session.strip()}",
                                    speak=True
                                )
                        known_sessions = current

            except Exception:
                pass

            await asyncio.sleep(15)

    # ─────────────────────────────────────────────────────────────────────────
    # PROCESS WATCHER — detects suspicious new processes
    # ─────────────────────────────────────────────────────────────────────────
    async def process_watcher(self):
        """Monitor for suspicious new processes."""
        self._log("Process Watcher started.")
        self._watchers["process_watcher"] = {"running": True}

        SUSPICIOUS_NAMES = {
             "nc -", "ncat", "netcat", "socat",
             "meterpreter", "reverse_shell",
             "mimikatz", "lazagne",
             "keylogger", "rat ", " backdoor",
             "cryptominer", "xmrig", "cgminer",
             "impacket", "psexec",
             "msfvenom", "metasploit",
        }

        known_pids = set()
        first_run = True

        while self.running:
            try:
                if OS == "Linux":
                    res = subprocess.check_output(
                        ["ps", "aux", "--no-headers"],
                        text=True, timeout=10
                    )
                elif OS == "Darwin":
                    res = subprocess.check_output(
                        ["ps", "aux"], text=True, timeout=10
                    )
                else:
                    res = subprocess.check_output(
                        ["tasklist", "/fo", "csv", "/nh"],
                        text=True, timeout=10
                    )

                current_procs = {}
                for line in res.strip().split("\n"):
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            pid = int(parts[1]) if OS != "Windows" else 0
                            cmd = " ".join(parts[10:]) if OS != "Windows" else parts[0]
                            current_procs[pid] = cmd.lower()
                        except (ValueError, IndexError):
                            pass

                current_pids = set(current_procs.keys())

                if first_run:
                    known_pids = current_pids
                    first_run = False
                else:
                    new_pids = current_pids - known_pids
                    for pid in new_pids:
                        cmd = current_procs.get(pid, "")
                        for sus in SUSPICIOUS_NAMES:
                            if sus in cmd:
                                self._alert(
                                    f"Suspicious process detected: "
                                    f"PID {pid} — {cmd[:80]}",
                                    speak=True
                                )
                                break
                    known_pids = current_pids

            except Exception:
                pass

            await asyncio.sleep(10)

    # ─────────────────────────────────────────────────────────────────────────
    # STATUS & CONTROL
    # ─────────────────────────────────────────────────────────────────────────
    def get_status(self) -> str:
        """Get daemon status."""
        lines = ["[DAEMON STATUS]"]
        lines.append(f"Running: {self.running}")
        lines.append(f"Alerts logged: {len(self._alerts_log)}")
        lines.append(f"Known network devices: {len(self._known_devices)}")
        lines.append(f"Known listening ports: {len(self._known_ports)}")
        lines.append(f"Ghost listeners: {len(self._ghost_procs)}")
        lines.append("")
        lines.append("[WATCHERS]")
        for name, info in self._watchers.items():
            lines.append(f"  • {name}: {'🟢 Active' if info['running'] else '🔴 Stopped'}")
        if self._ghost_procs:
            lines.append("")
            lines.append("[GHOST LISTENERS]")
            for key, info in self._ghost_procs.items():
                alive = info["process"].poll() is None
                lines.append(
                    f"  • {key} — {'🟢' if alive else '🔴'} — "
                    f"PID: {info['pid']}"
                )
        return "\n".join(lines)

    def get_alerts(self, count: int = 10) -> str:
        """Get recent alerts."""
        if not self._alerts_log:
            return "No alerts recorded."
        recent = self._alerts_log[-count:]
        lines = [f"[LAST {len(recent)} ALERTS]"]
        for alert in recent:
            lines.append(f"  [{alert['time']}] {alert['message']}")
        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────────────
    # START / STOP
    # ─────────────────────────────────────────────────────────────────────────
    def start(self):
        """Start the daemon in a background thread."""
        def _run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            tasks = asyncio.gather(
                self.network_watcher(),
                self.port_sentry(),
                self.file_watcher(),
                self.login_watcher(),
                self.process_watcher(),
                return_exceptions=True,
            )
            try:
                self._loop.run_until_complete(tasks)
            except Exception as e:
                self._log(f"Daemon error: {e}")

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        self._log("🛡️ Daemon Layer fully initialized — all watchers active.")

    def stop(self):
        """Stop the daemon and all ghost listeners."""
        self.running = False
        # Kill all ghost listeners
        for key in list(self._ghost_procs.keys()):
            try:
                self._ghost_procs[key]["process"].terminate()
            except Exception:
                pass
        self._ghost_procs.clear()
        self._log("Daemon stopped.")


# ── Module-level singleton ────────────────────────────────────────────────────
_daemon: JarvisDaemon | None = None

def get_daemon(jarvis_instance=None) -> JarvisDaemon | None:
    global _daemon
    if _daemon is None and jarvis_instance is not None:
        _daemon = JarvisDaemon(jarvis_instance)
    return _daemon


def daemon_enabled_by_default(config_path=None) -> bool:
    """Whether the background daemon should auto-start on launch.

    OFF by default. Enable with either:
      * env var JARVIS_DAEMON=1 (takes precedence), or
      * config/daemon.json -> {"enabled": true}
    The daemon can always be started/stopped at runtime via the
    daemon_control tool ("start daemon" / "stop daemon").
    """
    env = os.environ.get("JARVIS_DAEMON")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    try:
        cfg = Path(config_path) if config_path else \
            Path(__file__).resolve().parent.parent / "config" / "daemon.json"
        if cfg.exists():
            with open(cfg, "r", encoding="utf-8") as f:
                return bool(json.load(f).get("enabled", False))
    except Exception:
        pass
    return False