"""
dev_forge_ui.py  —  JARVIS Dev Forge Live HUD
A floating status window that shows real-time progress
of the Dev Forge agent while it builds, runs and fixes code.
"""

import tkinter as tk
from tkinter import ttk
import threading
import queue
import time
from typing import Optional


# ── Theme ─────────────────────────────────────────────────────────────────────
THEME = {
    "bg":           "#0d0d0d",
    "panel":        "#111111",
    "border":       "#00ff88",
    "text":         "#e0e0e0",
    "dim":          "#666666",
    "success":      "#00ff88",
    "warning":      "#ffaa00",
    "error":        "#ff4444",
    "info":         "#00aaff",
    "accent":       "#7c3aed",
    "progress_bg":  "#1a1a1a",
    "progress_fg":  "#00ff88",
    "font_main":    ("Consolas", 10),
    "font_title":   ("Consolas", 12, "bold"),
    "font_log":     ("Consolas", 9),
    "font_status":  ("Consolas", 11, "bold"),
}

# Status icons
ICONS = {
    "working":  "🔄",
    "success":  "✅",
    "error":    "❌",
    "warning":  "⚠️",
    "info":     "📋",
    "install":  "📦",
    "code":     "💻",
    "run":      "▶️",
    "fix":      "🔧",
    "plan":     "🧠",
    "folder":   "📁",
    "test":     "🧪",
    "done":     "🎉",
    "ide":      "🖥️",
}


class DevForgeHUD:
    """
    Floating HUD window for Dev Forge agent.
    Thread-safe — all UI updates go through a queue.
    """

    def __init__(self):
        self._root:      Optional[tk.Tk]    = None
        self._thread:    Optional[threading.Thread] = None
        self._queue:     queue.Queue        = queue.Queue()
        self._running:   bool               = False
        self._progress:  float              = 0.0
        self._log_lines: list[str]          = []
        self._max_logs:  int                = 50

    # ── Public API (call from any thread) ─────────────────────────────────────

    def show(self, task: str = ""):
        """Show the HUD window."""
        if self._running:
            self.set_task(task)
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._run_ui, args=(task,), daemon=True
        )
        self._thread.start()
        time.sleep(0.3)   # Let window initialize

    def hide(self):
        """Hide and destroy the HUD window."""
        self._queue.put(("hide", None))

    def set_task(self, task: str):
        """Update the main task label."""
        self._queue.put(("task", task))

    def set_status(self, status: str, kind: str = "info"):
        """
        Update the current status line.
        kind: info | success | error | warning | working
        """
        icon = ICONS.get(kind, "🔄")
        self._queue.put(("status", (f"{icon}  {status}", kind)))

    def set_progress(self, percent: float):
        """Set progress bar 0–100."""
        self._queue.put(("progress", min(max(percent, 0), 100)))

    def log(self, message: str, kind: str = "info"):
        """Add a line to the log panel."""
        icon  = ICONS.get(kind, "•")
        color = {
            "success": THEME["success"],
            "error":   THEME["error"],
            "warning": THEME["warning"],
            "info":    THEME["info"],
            "working": THEME["text"],
            "dim":     THEME["dim"],
        }.get(kind, THEME["text"])
        self._queue.put(("log", (f"{icon}  {message}", color)))

    def set_phase(self, phase: str, kind: str = "working"):
        """Shortcut: update status + log at the same time."""
        self.set_status(phase, kind)
        self.log(phase, kind)

    def finish(self, message: str = "Done!", success: bool = True):
        """Mark task as complete."""
        kind = "success" if success else "error"
        self.set_progress(100)
        self.set_status(message, kind)
        self.log(message, kind)

    # ── Internal UI (runs in its own thread) ──────────────────────────────────

    def _run_ui(self, task: str):
        self._root = tk.Tk()
        root = self._root

        root.title("DEV FORGE")
        root.configure(bg=THEME["bg"])
        root.resizable(False, False)
        root.attributes("-topmost", True)
        root.overrideredirect(False)

        # Position — top right corner
        root.update_idletasks()
        sw = root.winfo_screenwidth()
        root.geometry(f"440x580+{sw - 460}+30")

        self._build_ui(root, task)
        root.after(50, self._process_queue)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.mainloop()
        self._running = False

    def _build_ui(self, root: tk.Tk, task: str):
        # ── Outer border frame
        outer = tk.Frame(root, bg=THEME["border"], padx=1, pady=1)
        outer.pack(fill="both", expand=True, padx=6, pady=6)

        inner = tk.Frame(outer, bg=THEME["bg"])
        inner.pack(fill="both", expand=True)

        # ── Title bar
        title_bar = tk.Frame(inner, bg=THEME["panel"], pady=8)
        title_bar.pack(fill="x")

        tk.Label(
            title_bar,
            text="🔨  DEV FORGE",
            font=THEME["font_title"],
            bg=THEME["panel"],
            fg=THEME["border"],
        ).pack(side="left", padx=12)

        self._close_btn = tk.Button(
            title_bar,
            text="✕",
            font=("Consolas", 10),
            bg=THEME["panel"],
            fg=THEME["dim"],
            bd=0,
            activebackground=THEME["error"],
            activeforeground="white",
            cursor="hand2",
            command=self._on_close,
        )
        self._close_btn.pack(side="right", padx=10)

        # Divider
        tk.Frame(inner, bg=THEME["border"], height=1).pack(fill="x")

        # ── Task
        task_frame = tk.Frame(inner, bg=THEME["bg"], pady=8, padx=12)
        task_frame.pack(fill="x")

        tk.Label(
            task_frame,
            text="TASK",
            font=("Consolas", 8),
            bg=THEME["bg"],
            fg=THEME["dim"],
        ).pack(anchor="w")

        self._task_label = tk.Label(
            task_frame,
            text=task or "Waiting...",
            font=("Consolas", 10, "bold"),
            bg=THEME["bg"],
            fg=THEME["text"],
            wraplength=400,
            justify="left",
        )
        self._task_label.pack(anchor="w")

        # ── Status
        status_frame = tk.Frame(inner, bg=THEME["panel"], pady=10, padx=12)
        status_frame.pack(fill="x")

        tk.Label(
            status_frame,
            text="STATUS",
            font=("Consolas", 8),
            bg=THEME["panel"],
            fg=THEME["dim"],
        ).pack(anchor="w")

        self._status_label = tk.Label(
            status_frame,
            text="🔄  Initializing...",
            font=THEME["font_status"],
            bg=THEME["panel"],
            fg=THEME["info"],
            wraplength=400,
            justify="left",
        )
        self._status_label.pack(anchor="w")

        # ── Progress bar
        prog_frame = tk.Frame(inner, bg=THEME["bg"], pady=8, padx=12)
        prog_frame.pack(fill="x")

        tk.Label(
            prog_frame,
            text="PROGRESS",
            font=("Consolas", 8),
            bg=THEME["bg"],
            fg=THEME["dim"],
        ).pack(anchor="w")

        bar_bg = tk.Frame(prog_frame, bg=THEME["progress_bg"], height=14)
        bar_bg.pack(fill="x", pady=(2, 0))
        bar_bg.pack_propagate(False)

        self._bar_fill = tk.Frame(bar_bg, bg=THEME["progress_fg"], height=14)
        self._bar_fill.place(x=0, y=0, relwidth=0.0, height=14)

        self._pct_label = tk.Label(
            prog_frame,
            text="0%",
            font=("Consolas", 8),
            bg=THEME["bg"],
            fg=THEME["dim"],
        )
        self._pct_label.pack(anchor="e")

        # Divider
        tk.Frame(inner, bg=THEME["border"], height=1).pack(fill="x", padx=12)

        # ── Log panel
        log_header = tk.Frame(inner, bg=THEME["bg"], pady=4, padx=12)
        log_header.pack(fill="x")

        tk.Label(
            log_header,
            text="📋  ACTIVITY LOG",
            font=("Consolas", 8),
            bg=THEME["bg"],
            fg=THEME["dim"],
        ).pack(anchor="w")

        log_outer = tk.Frame(inner, bg=THEME["panel"], padx=8, pady=6)
        log_outer.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self._log_text = tk.Text(
            log_outer,
            font=THEME["font_log"],
            bg=THEME["panel"],
            fg=THEME["text"],
            bd=0,
            wrap="word",
            state="disabled",
            height=14,
            cursor="arrow",
        )
        self._log_text.pack(fill="both", expand=True)

        # Tag colors for log
        self._log_text.tag_configure("success", foreground=THEME["success"])
        self._log_text.tag_configure("error",   foreground=THEME["error"])
        self._log_text.tag_configure("warning", foreground=THEME["warning"])
        self._log_text.tag_configure("info",    foreground=THEME["info"])
        self._log_text.tag_configure("working", foreground=THEME["text"])
        self._log_text.tag_configure("dim",     foreground=THEME["dim"])

        # ── Bottom bar
        bottom = tk.Frame(inner, bg=THEME["panel"], pady=6)
        bottom.pack(fill="x", side="bottom")

        self._bottom_label = tk.Label(
            bottom,
            text="JARVIS DEV FORGE  •  AI-Powered Coding Agent",
            font=("Consolas", 8),
            bg=THEME["panel"],
            fg=THEME["dim"],
        )
        self._bottom_label.pack()

    def _process_queue(self):
        """Process all pending UI updates from the queue."""
        try:
            while True:
                cmd, data = self._queue.get_nowait()

                if cmd == "task":
                    self._task_label.config(text=data)

                elif cmd == "status":
                    text, kind = data
                    color = {
                        "success": THEME["success"],
                        "error":   THEME["error"],
                        "warning": THEME["warning"],
                        "info":    THEME["info"],
                        "working": THEME["text"],
                    }.get(kind, THEME["text"])
                    self._status_label.config(text=text, fg=color)

                elif cmd == "progress":
                    pct = data / 100.0
                    self._bar_fill.place(relwidth=pct)
                    self._pct_label.config(text=f"{int(data)}%")
                    # Change bar color near completion
                    color = THEME["success"] if data >= 100 else THEME["progress_fg"]
                    self._bar_fill.config(bg=color)

                elif cmd == "log":
                    text, color = data
                    self._log_text.config(state="normal")
                    tag = self._color_to_tag(color)
                    self._log_text.insert("end", text + "\n", tag)
                    # Keep log trimmed
                    lines = int(self._log_text.index("end-1c").split(".")[0])
                    if lines > self._max_logs:
                        self._log_text.delete("1.0", "2.0")
                    self._log_text.config(state="disabled")
                    self._log_text.see("end")

                elif cmd == "hide":
                    if self._root:
                        self._root.destroy()
                    self._running = False
                    return

        except queue.Empty:
            pass

        if self._running and self._root:
            self._root.after(50, self._process_queue)

    def _color_to_tag(self, color: str) -> str:
        mapping = {
            THEME["success"]: "success",
            THEME["error"]:   "error",
            THEME["warning"]: "warning",
            THEME["info"]:    "info",
            THEME["text"]:    "working",
            THEME["dim"]:     "dim",
        }
        return mapping.get(color, "working")

    def _on_close(self):
        self._running = False
        if self._root:
            self._root.destroy()


# ── Singleton accessor ────────────────────────────────────────────────────────
_hud_instance: Optional[DevForgeHUD] = None


def get_hud() -> DevForgeHUD:
    """Get or create the singleton HUD instance."""
    global _hud_instance
    if _hud_instance is None:
        _hud_instance = DevForgeHUD()
    return _hud_instance