"""
api_key_setup.py — VINCEVISION / JARVIS first-run API-key popup
────────────────────────────────────────────────────────────────
A friendly GUI popup that prompts for the Gemini (required) and Groq
(optional) API keys on first run — no terminal editing needed. Keys are
saved to the encrypted credential vault AND config/api_keys.json.

Design:
  * tkinter is imported lazily, so this module is stdlib-only at import time
    and the offline test suite / CI need no GUI.
  * Pure helpers (validate_keys / save_api_keys) are separated from the UI
    so they can be tested without a display.
  * run_gui_setup() returns None when no GUI is available, letting the caller
    fall back to the terminal wizard.

Manual launch:  python -m core.api_key_setup
"""

import os
import sys
import webbrowser

GEMINI_KEY_URL = "https://aistudio.google.com/apikey"
GROQ_KEY_URL = "https://console.groq.com/keys"

PLACEHOLDER_MARKERS = ("YOUR_", "_HERE", "CHANGE_ME", "PASTE")


# ── Pure helpers (testable without a display) ───────────────────────────────

def validate_keys(gemini: str, groq: str = ""):
    """Return (ok, message). Gemini is required; Groq is optional."""
    gemini = (gemini or "").strip()
    groq = (groq or "").strip()
    if not gemini:
        return False, "Gemini API key is required. Paste it, or click 'Skip for now'."
    if any(m in gemini.upper() for m in PLACEHOLDER_MARKERS):
        return False, "That looks like a placeholder. Paste your real Gemini key."
    if len(gemini) < 20:
        return False, "That Gemini key looks too short — make sure you copied the whole key."
    if groq and len(groq) < 20:
        return False, "That Groq key looks too short. Leave it blank to skip it."
    return True, ""


def save_api_keys(gemini: str, groq: str = "") -> str:
    """Persist keys to the vault + api_keys.json and mark setup complete."""
    from core import credential_manager as cm

    gemini = (gemini or "").strip()
    groq = (groq or "").strip()
    results = []
    if gemini:
        cm.save_credential("gemini", "api_key", gemini)
        cm._update_api_keys_json("gemini_api_key", gemini)
        results.append("✅ Gemini API key saved")
    if groq:
        cm.save_credential("groq", "api_key", groq)
        cm._update_api_keys_json("groq_api_key", groq)
        results.append("✅ Groq API key saved")

    cm.mark_setup_complete()

    if not results:
        return ("Setup skipped — you can add keys anytime by saying "
                "'Jarvis, update my credentials'.")
    return "Setup complete:\n" + "\n".join(results)


# ── GUI availability ────────────────────────────────────────────────────────

def _display_present() -> bool:
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True  # macOS / Windows have a windowing system


def gui_available() -> bool:
    """Quick pre-check: can we reasonably open a Tk window here?"""
    if os.environ.get("JARVIS_NO_GUI"):
        return False
    if not _display_present():
        return False
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:
        return False


# ── Themed Tk dialog ────────────────────────────────────────────────────────

class _Theme:
    BG_DARK = "#0a0a1a"
    BG_MID = "#1a1a2e"
    ACCENT = "#00d4ff"
    SUCCESS = "#00ff88"
    WARNING = "#ffaa00"
    DANGER = "#ff4444"
    TEXT_WHITE = "#ffffff"
    TEXT_GRAY = "#aaaaaa"


class _SetupDialog:
    """The popup window. Built only when a display is available."""

    def __init__(self):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.result = None
        self.root = tk.Tk()
        self.root.title("JARVIS — First-Time Setup")
        self.root.configure(bg=_Theme.BG_DARK)
        self.root.resizable(False, False)
        self._center(560, 560)

        self.gemini_var = tk.StringVar()
        self.groq_var = tk.StringVar()
        self._show_gemini = False
        self._show_groq = False

        self._build()

    def _center(self, w, h):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _build(self):
        tk = self.tk
        pad = {"padx": 24}

        tk.Label(self.root, text="🤖 Welcome to JARVIS", font=("Segoe UI", 20, "bold"),
                 bg=_Theme.BG_DARK, fg=_Theme.ACCENT).pack(pady=(24, 4))
        tk.Label(self.root,
                 text="Add your AI API keys to get started.\nStored encrypted on this machine only — never uploaded.",
                 font=("Segoe UI", 10), bg=_Theme.BG_DARK, fg=_Theme.TEXT_GRAY,
                 justify="center").pack(pady=(0, 16))

        self.gemini_entry = self._key_section(
            "Gemini API Key  (required)", self.gemini_var, GEMINI_KEY_URL,
            "Free at aistudio.google.com → 'Get API key'", self._toggle_gemini)
        self.groq_entry = self._key_section(
            "Groq API Key  (optional fallback)", self.groq_var, GROQ_KEY_URL,
            "Free at console.groq.com → 'API Keys'", self._toggle_groq)

        self.status = tk.Label(self.root, text="", font=("Segoe UI", 9),
                               bg=_Theme.BG_DARK, fg=_Theme.WARNING,
                               wraplength=500, justify="center")
        self.status.pack(pady=(8, 0), **pad)

        btns = tk.Frame(self.root, bg=_Theme.BG_DARK)
        btns.pack(pady=16, fill="x", **pad)
        tk.Button(btns, text="Skip for now", command=self._skip,
                  bg=_Theme.BG_MID, fg=_Theme.TEXT_GRAY, relief="flat",
                  font=("Segoe UI", 10), padx=16, pady=8, cursor="hand2").pack(side="left")
        tk.Button(btns, text="Save & Continue", command=self._save,
                  bg=_Theme.ACCENT, fg=_Theme.BG_DARK, relief="flat",
                  font=("Segoe UI", 11, "bold"), padx=20, pady=8, cursor="hand2").pack(side="right")

        tk.Label(self.root,
                 text="Update anytime: say 'Jarvis, update my credentials'.",
                 font=("Segoe UI", 8), bg=_Theme.BG_DARK, fg=_Theme.TEXT_GRAY).pack(pady=(0, 12))

    def _key_section(self, label, var, url, hint, toggle_cmd):
        tk = self.tk
        frame = tk.Frame(self.root, bg=_Theme.BG_MID)
        frame.pack(fill="x", padx=24, pady=6)
        tk.Label(frame, text=label, font=("Segoe UI", 11, "bold"),
                 bg=_Theme.BG_MID, fg=_Theme.TEXT_WHITE).pack(anchor="w", padx=12, pady=(10, 2))
        row = tk.Frame(frame, bg=_Theme.BG_MID)
        row.pack(fill="x", padx=12)
        entry = tk.Entry(row, textvariable=var, show="•", font=("Consolas", 11),
                         bg=_Theme.BG_DARK, fg=_Theme.TEXT_WHITE, insertbackground=_Theme.ACCENT,
                         relief="flat")
        entry.pack(side="left", fill="x", expand=True, ipady=6)
        tk.Button(row, text="👁", command=toggle_cmd, bg=_Theme.BG_MID,
                  fg=_Theme.TEXT_GRAY, relief="flat", cursor="hand2").pack(side="left", padx=(6, 0))
        bottom = tk.Frame(frame, bg=_Theme.BG_MID)
        bottom.pack(fill="x", padx=12, pady=(4, 10))
        tk.Label(bottom, text=hint, font=("Segoe UI", 8),
                 bg=_Theme.BG_MID, fg=_Theme.TEXT_GRAY).pack(side="left")
        tk.Button(bottom, text="Get free key ↗", command=lambda: webbrowser.open(url),
                  bg=_Theme.BG_MID, fg=_Theme.ACCENT, relief="flat",
                  font=("Segoe UI", 8, "underline"), cursor="hand2").pack(side="right")
        return entry

    def _toggle_gemini(self):
        self._show_gemini = not self._show_gemini
        self.gemini_entry.config(show="" if self._show_gemini else "•")

    def _toggle_groq(self):
        self._show_groq = not self._show_groq
        self.groq_entry.config(show="" if self._show_groq else "•")

    def _save(self):
        gemini = self.gemini_var.get()
        groq = self.groq_var.get()
        ok, msg = validate_keys(gemini, groq)
        if not ok:
            self.status.config(text=msg, fg=_Theme.WARNING)
            return
        self.result = save_api_keys(gemini, groq)
        self.status.config(text="✅ Saved! Starting JARVIS…", fg=_Theme.SUCCESS)
        self.root.after(700, self.root.destroy)

    def _skip(self):
        from core import credential_manager as cm
        cm.mark_setup_complete()
        self.result = ("Setup skipped — add keys anytime by saying "
                       "'Jarvis, update my credentials'.")
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def run_gui_setup():
    """Open the popup. Returns a result string, or None if no GUI is available
    (so the caller can fall back to the terminal wizard)."""
    if not gui_available():
        return None
    try:
        dialog = _SetupDialog()
        dialog.run()
        return dialog.result
    except Exception as e:
        print(f"[Setup] GUI popup failed ({e}); falling back to terminal setup.")
        return None


if __name__ == "__main__":
    out = run_gui_setup()
    if out is None:
        print("No display available. Run the terminal setup instead: python main.py")
    else:
        print(out)
