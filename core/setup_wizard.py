# core/setup_wizard.py
"""
JARVIS Number Tracer — GUI First-Run Setup Wizard
──────────────────────────────────────────────────
Beautiful Tkinter wizard that guides users through getting all API keys.
"""

import os
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from pathlib import Path


# ═════════════════════════════════════════════
# COLOR THEME (matches JARVIS UI)
# ═════════════════════════════════════════════
class Theme:
    BG_DARK     = "#0a0a1a"
    BG_MID      = "#1a1a2e"
    BG_LIGHT    = "#0f1f3a"
    ACCENT      = "#00d4ff"
    ACCENT_DIM  = "#0099cc"
    SUCCESS     = "#00ff88"
    WARNING     = "#ffaa00"
    DANGER      = "#ff4444"
    TEXT_WHITE  = "#ffffff"
    TEXT_GRAY   = "#aaaaaa"
    TEXT_DIM    = "#666666"
    BTN_BG      = "#1a1a2e"
    BTN_HOVER   = "#2a2a4e"


# ═════════════════════════════════════════════
# CREDENTIAL HELPERS
# ═════════════════════════════════════════════
def _save_cred(service: str, key: str, value: str) -> bool:
    try:
        from core.credential_manager import save_credential
        save_credential(service, key, value)
        return True
    except Exception as e:
        print(f"[Wizard] Failed to save: {e}")
        return False


def _get_cred(service: str, key: str) -> str:
    try:
        from core.credential_manager import get_credential
        return get_credential(service, key) or ""
    except Exception:
        return ""


# ═════════════════════════════════════════════
# SERVICE DEFINITIONS
# ═════════════════════════════════════════════
SERVICES = [
    {
        "id":       "telegram",
        "name":     "📱 Telegram API",
        "tagline":  "Highly Recommended — FREE",
        "color":    Theme.SUCCESS,
        "features": [
            "✅ Real names of phone owners",
            "✅ Usernames, bios, profile photos",
            "✅ Last seen status & premium badge",
            "✅ Works globally for ANY country",
        ],
        "url":      "https://my.telegram.org/auth",
        "instructions": (
            "1. Click 'Open Website' below\n"
            "2. Log in with your Telegram phone number\n"
            "3. Click 'API development tools'\n"
            "4. Fill the form (any name like 'JARVIS' is fine)\n"
            "5. Copy your api_id (numbers) and api_hash (long string)\n"
            "6. Paste them below"
        ),
        "fields": [
            {"key": "api_id",   "label": "API ID (numbers only)",       "type": "number"},
            {"key": "api_hash", "label": "API Hash (long letters/digits)", "type": "text"},
        ],
        "needs_login": True,  # Special flag for Telegram login
    },
    {
        "id":       "ipqualityscore",
        "name":     "🛡️ IPQualityScore",
        "tagline":  "Recommended — 5,000 free per month",
        "color":    Theme.ACCENT,
        "features": [
            "✅ Fraud score (0-100)",
            "✅ Spammer & risky flags",
            "✅ Carrier, line type, city, region",
            "✅ Whether the number was leaked",
        ],
        "url":      "https://www.ipqualityscore.com/create-account",
        "instructions": (
            "1. Sign up at the website\n"
            "2. Verify your email\n"
            "3. Copy your API key from the dashboard\n"
            "4. Paste it below"
        ),
        "fields": [
            {"key": "api_key", "label": "IPQualityScore API Key", "type": "text"},
        ],
    },
    {
        "id":       "numverify",
        "name":     "📞 NumVerify",
        "tagline":  "Optional — 100 free per month",
        "color":    Theme.WARNING,
        "features": [
            "✅ Carrier name globally",
            "✅ Line type (mobile/landline)",
            "✅ Country & location",
        ],
        "url":      "https://numverify.com/product",
        "instructions": (
            "1. Sign up at the website\n"
            "2. Choose the FREE plan (100 lookups/month)\n"
            "3. Copy your API access key from the dashboard\n"
            "4. Paste it below"
        ),
        "fields": [
            {"key": "api_key", "label": "NumVerify API Key", "type": "text"},
        ],
    },
    {
        "id":       "opencnam",
        "name":     "📇 OpenCNAM",
        "tagline":  "Optional — US numbers only",
        "color":    Theme.WARNING,
        "features": [
            "✅ Caller ID name lookup (US only)",
        ],
        "url":      "https://www.opencnam.com",
        "instructions": (
            "1. Sign up at OpenCNAM\n"
            "2. Get your Account SID and Auth Token from the dashboard\n"
            "3. Paste both below"
        ),
        "fields": [
            {"key": "sid",   "label": "Account SID",  "type": "text"},
            {"key": "token", "label": "Auth Token",   "type": "text"},
        ],
    },
    {
        "id":       "hibp",
        "name":     "🔓 HaveIBeenPwned",
        "tagline":  "Optional — $3.95/month",
        "color":    Theme.WARNING,
        "features": [
            "✅ Email breach data",
            "✅ Password leak detection",
        ],
        "url":      "https://haveibeenpwned.com/API/Key",
        "instructions": (
            "1. Subscribe at the website ($3.95/month)\n"
            "2. Copy your API key\n"
            "3. Paste it below"
        ),
        "fields": [
            {"key": "api_key", "label": "HIBP API Key", "type": "text"},
        ],
    },
]


# ═════════════════════════════════════════════
# SETUP WIZARD CLASS
# ═════════════════════════════════════════════
class SetupWizard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🔍 JARVIS — Number Tracer Setup")
        self.root.geometry("800x720")
        self.root.configure(bg=Theme.BG_DARK)
        self.root.attributes("-topmost", True)

        # Center on screen
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"+{x}+{y}")

        self.current_page = 0
        self.configured   = []
        self.field_vars   = {}

        # Make sure window can be closed
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._show_welcome()

    def _on_close(self):
        if messagebox.askyesno(
            "Cancel Setup?",
            "Are you sure you want to cancel the setup?\n\n"
            "You can re-run the wizard anytime later.",
        ):
            self.root.destroy()

    # ── UI construction ──────────────────────
    def _build_ui(self):
        # Header
        self.header = tk.Frame(self.root, bg=Theme.BG_MID, height=70)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)

        self.header_title = tk.Label(
            self.header,
            text="🔍 JARVIS Number Tracer Setup",
            font=("Arial", 20, "bold"),
            fg=Theme.ACCENT,
            bg=Theme.BG_MID,
        )
        self.header_title.pack(pady=15)

        # Progress bar
        self.progress_frame = tk.Frame(self.root, bg=Theme.BG_DARK, height=10)
        self.progress_frame.pack(fill="x", padx=20, pady=(10, 0))

        self.progress_canvas = tk.Canvas(
            self.progress_frame,
            height=6,
            bg=Theme.BG_MID,
            highlightthickness=0,
        )
        self.progress_canvas.pack(fill="x")

        # Main content area
        self.content = tk.Frame(self.root, bg=Theme.BG_DARK)
        self.content.pack(fill="both", expand=True, padx=30, pady=20)

        # Footer with buttons
        self.footer = tk.Frame(self.root, bg=Theme.BG_DARK, height=70)
        self.footer.pack(fill="x", side="bottom", padx=20, pady=10)
        self.footer.pack_propagate(False)

    def _update_progress(self, current: int, total: int):
        """Draw progress bar."""
        self.progress_canvas.delete("all")
        self.progress_canvas.update_idletasks()
        w = self.progress_canvas.winfo_width()
        if w < 10:
            w = 740
        if total > 0:
            fill_w = int(w * (current / total))
            self.progress_canvas.create_rectangle(
                0, 0, fill_w, 6,
                fill=Theme.ACCENT,
                outline="",
            )

    def _clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()
        for w in self.footer.winfo_children():
            w.destroy()

    def _make_button(self, parent, text, command, color=None, is_primary=False):
        bg = color or (Theme.ACCENT if is_primary else Theme.BTN_BG)
        fg = Theme.BG_DARK if is_primary else Theme.TEXT_WHITE

        btn = tk.Button(
            parent,
            text=text,
            font=("Arial", 11, "bold" if is_primary else "normal"),
            bg=bg,
            fg=fg,
            activebackground=Theme.BTN_HOVER,
            activeforeground=Theme.TEXT_WHITE,
            relief="flat",
            padx=20,
            pady=10,
            cursor="hand2",
            command=command,
        )
        return btn

    # ═════════════════════════════════════════
    # PAGE 1: WELCOME
    # ═════════════════════════════════════════
    def _show_welcome(self):
        self._clear_content()
        self._update_progress(0, len(SERVICES) + 1)

        # Big icon
        tk.Label(
            self.content,
            text="🔍",
            font=("Arial", 60),
            bg=Theme.BG_DARK,
            fg=Theme.ACCENT,
        ).pack(pady=(20, 10))

        tk.Label(
            self.content,
            text="Welcome to the Number Tracer Setup",
            font=("Arial", 18, "bold"),
            bg=Theme.BG_DARK,
            fg=Theme.TEXT_WHITE,
        ).pack(pady=(0, 10))

        tk.Label(
            self.content,
            text=(
                "This wizard will help you configure API keys to unlock\n"
                "Truecaller-grade phone number investigation."
            ),
            font=("Arial", 11),
            bg=Theme.BG_DARK,
            fg=Theme.TEXT_GRAY,
            justify="center",
        ).pack(pady=(0, 20))

        # Features box
        features_frame = tk.Frame(self.content, bg=Theme.BG_LIGHT, padx=20, pady=15)
        features_frame.pack(fill="x", pady=10)

        tk.Label(
            features_frame,
            text="What you'll get:",
            font=("Arial", 12, "bold"),
            bg=Theme.BG_LIGHT,
            fg=Theme.ACCENT,
        ).pack(anchor="w", pady=(0, 8))

        features = [
            "🔍  Find the real owner's name from any phone number",
            "📱  Check if number is on Telegram, WhatsApp, Signal",
            "🌐  Discover linked social media profiles",
            "🛡️  Detect scammers with fraud scoring",
            "📧  Find linked email addresses",
            "🔓  Check data breach databases",
            "📊  Generate detailed investigation reports",
        ]
        for f in features:
            tk.Label(
                features_frame,
                text=f,
                font=("Arial", 10),
                bg=Theme.BG_LIGHT,
                fg=Theme.TEXT_WHITE,
                anchor="w",
            ).pack(fill="x", pady=2)

        # Note
        tk.Label(
            self.content,
            text=(
                "ℹ️  You can skip any service and configure it later.\n"
                "The tool works without API keys — but with limited results."
            ),
            font=("Arial", 9, "italic"),
            bg=Theme.BG_DARK,
            fg=Theme.TEXT_DIM,
            justify="center",
        ).pack(pady=15)

        # Footer buttons
        self._make_button(
            self.footer,
            "Skip Setup",
            self._on_close,
        ).pack(side="left", padx=5)

        self._make_button(
            self.footer,
            "Get Started  →",
            self._next_service,
            is_primary=True,
        ).pack(side="right", padx=5)

    # ═════════════════════════════════════════
    # SERVICE PAGES
    # ═════════════════════════════════════════
    def _next_service(self):
        if self.current_page >= len(SERVICES):
            self._show_complete()
            return
        self._show_service(SERVICES[self.current_page])

    def _show_service(self, service: dict):
        self._clear_content()
        self._update_progress(self.current_page + 1, len(SERVICES) + 1)
        self.field_vars = {}

        # Service title
        title_frame = tk.Frame(self.content, bg=Theme.BG_DARK)
        title_frame.pack(fill="x", pady=(0, 5))

        tk.Label(
            title_frame,
            text=service["name"],
            font=("Arial", 20, "bold"),
            bg=Theme.BG_DARK,
            fg=Theme.TEXT_WHITE,
        ).pack(side="left")

        tk.Label(
            title_frame,
            text=f"  ({self.current_page + 1}/{len(SERVICES)})",
            font=("Arial", 11),
            bg=Theme.BG_DARK,
            fg=Theme.TEXT_DIM,
        ).pack(side="left", pady=(8, 0))

        tk.Label(
            self.content,
            text=service["tagline"],
            font=("Arial", 11, "italic"),
            bg=Theme.BG_DARK,
            fg=service["color"],
        ).pack(anchor="w", pady=(0, 15))

        # Features
        feat_frame = tk.Frame(self.content, bg=Theme.BG_LIGHT, padx=15, pady=12)
        feat_frame.pack(fill="x", pady=5)

        tk.Label(
            feat_frame,
            text="Features:",
            font=("Arial", 10, "bold"),
            bg=Theme.BG_LIGHT,
            fg=Theme.ACCENT,
        ).pack(anchor="w")

        for feat in service["features"]:
            tk.Label(
                feat_frame,
                text=feat,
                font=("Arial", 10),
                bg=Theme.BG_LIGHT,
                fg=Theme.TEXT_WHITE,
                anchor="w",
            ).pack(fill="x", pady=1)

        # Instructions
        inst_frame = tk.Frame(self.content, bg=Theme.BG_MID, padx=15, pady=12)
        inst_frame.pack(fill="x", pady=10)

        tk.Label(
            inst_frame,
            text="📋 How to get your credentials:",
            font=("Arial", 10, "bold"),
            bg=Theme.BG_MID,
            fg=Theme.WARNING,
        ).pack(anchor="w", pady=(0, 5))

        tk.Label(
            inst_frame,
            text=service["instructions"],
            font=("Arial", 10),
            bg=Theme.BG_MID,
            fg=Theme.TEXT_WHITE,
            justify="left",
            anchor="w",
        ).pack(anchor="w")

        # Open website button
        ws_btn = tk.Button(
            inst_frame,
            text="🌐  Open Website",
            font=("Arial", 10, "bold"),
            bg=Theme.ACCENT,
            fg=Theme.BG_DARK,
            relief="flat",
            padx=15, pady=6,
            cursor="hand2",
            command=lambda: webbrowser.open(service["url"]),
        )
        ws_btn.pack(anchor="w", pady=(8, 0))

        # Input fields
        fields_frame = tk.Frame(self.content, bg=Theme.BG_DARK)
        fields_frame.pack(fill="x", pady=15)

        for field in service["fields"]:
            tk.Label(
                fields_frame,
                text=field["label"],
                font=("Arial", 10),
                bg=Theme.BG_DARK,
                fg=Theme.TEXT_WHITE,
                anchor="w",
            ).pack(fill="x", pady=(8, 2))

            var = tk.StringVar()
            existing = _get_cred(service["id"], field["key"])
            if existing:
                var.set(existing)

            entry = tk.Entry(
                fields_frame,
                textvariable=var,
                font=("Courier", 11),
                bg=Theme.BG_MID,
                fg=Theme.TEXT_WHITE,
                insertbackground=Theme.ACCENT,
                relief="flat",
                bd=0,
            )
            entry.pack(fill="x", ipady=8, padx=2)

            self.field_vars[field["key"]] = var

        # Footer buttons
        self._make_button(
            self.footer,
            "← Back",
            self._previous_service,
        ).pack(side="left", padx=5)

        self._make_button(
            self.footer,
            "Skip This",
            self._skip_service,
        ).pack(side="left", padx=5)

        save_text = "Save & Continue  →"
        if service.get("needs_login"):
            save_text = "Save & Login  →"

        self._make_button(
            self.footer,
            save_text,
            lambda: self._save_service(service),
            is_primary=True,
        ).pack(side="right", padx=5)

    def _previous_service(self):
        if self.current_page == 0:
            self._show_welcome()
        else:
            self.current_page -= 1
            self._show_service(SERVICES[self.current_page])

    def _skip_service(self):
        self.current_page += 1
        self._next_service()

    def _save_service(self, service: dict):
        # Validate fields
        values = {}
        for field in service["fields"]:
            val = self.field_vars[field["key"]].get().strip()
            if not val:
                messagebox.showwarning(
                    "Missing Input",
                    f"Please enter {field['label']} or click 'Skip This'.",
                )
                return
            if field["type"] == "number" and not val.isdigit():
                messagebox.showerror(
                    "Invalid Input",
                    f"{field['label']} must contain only numbers.",
                )
                return
            values[field["key"]] = val

        # Save credentials
        for key, val in values.items():
            _save_cred(service["id"], key, val)

        # Special handling for Telegram — needs login
        if service.get("needs_login") and service["id"] == "telegram":
            self._show_telegram_login(values)
            return

        self.configured.append(service["name"])
        self.current_page += 1
        self._next_service()

    # ═════════════════════════════════════════
    # TELEGRAM LOGIN PAGE (special)
    # ═════════════════════════════════════════
    def _show_telegram_login(self, telegram_creds: dict):
        self._clear_content()
        self._update_progress(self.current_page + 1, len(SERVICES) + 1)

        tk.Label(
            self.content,
            text="📱 Telegram Login",
            font=("Arial", 20, "bold"),
            bg=Theme.BG_DARK,
            fg=Theme.TEXT_WHITE,
        ).pack(pady=(10, 5))

        tk.Label(
            self.content,
            text="Step 2: Authorize JARVIS to use your Telegram account",
            font=("Arial", 11, "italic"),
            bg=Theme.BG_DARK,
            fg=Theme.SUCCESS,
        ).pack(pady=(0, 15))

        info_frame = tk.Frame(self.content, bg=Theme.BG_LIGHT, padx=15, pady=12)
        info_frame.pack(fill="x", pady=10)

        tk.Label(
            info_frame,
            text=(
                "Enter your Telegram phone number below.\n"
                "A login code will be sent to your Telegram app.\n"
                "Enter that code when prompted."
            ),
            font=("Arial", 10),
            bg=Theme.BG_LIGHT,
            fg=Theme.TEXT_WHITE,
            justify="left",
        ).pack(anchor="w")

        # Phone input
        tk.Label(
            self.content,
            text="Your Telegram Phone (with country code):",
            font=("Arial", 10),
            bg=Theme.BG_DARK,
            fg=Theme.TEXT_WHITE,
            anchor="w",
        ).pack(fill="x", pady=(15, 2))

        phone_var = tk.StringVar()
        phone_entry = tk.Entry(
            self.content,
            textvariable=phone_var,
            font=("Courier", 12),
            bg=Theme.BG_MID,
            fg=Theme.TEXT_WHITE,
            insertbackground=Theme.ACCENT,
            relief="flat",
        )
        phone_entry.pack(fill="x", ipady=8)
        phone_entry.insert(0, "+")

        # Code input (hidden initially)
        code_frame = tk.Frame(self.content, bg=Theme.BG_DARK)

        tk.Label(
            code_frame,
            text="Login code (from your Telegram app):",
            font=("Arial", 10),
            bg=Theme.BG_DARK,
            fg=Theme.TEXT_WHITE,
            anchor="w",
        ).pack(fill="x", pady=(15, 2))

        code_var = tk.StringVar()
        code_entry = tk.Entry(
            code_frame,
            textvariable=code_var,
            font=("Courier", 16),
            bg=Theme.BG_MID,
            fg=Theme.ACCENT,
            insertbackground=Theme.ACCENT,
            relief="flat",
            justify="center",
        )
        code_entry.pack(fill="x", ipady=8)

        # Password input (for 2FA)
        password_frame = tk.Frame(self.content, bg=Theme.BG_DARK)

        tk.Label(
            password_frame,
            text="2FA Password (only if you enabled it):",
            font=("Arial", 10),
            bg=Theme.BG_DARK,
            fg=Theme.WARNING,
            anchor="w",
        ).pack(fill="x", pady=(15, 2))

        password_var = tk.StringVar()
        password_entry = tk.Entry(
            password_frame,
            textvariable=password_var,
            show="•",
            font=("Courier", 12),
            bg=Theme.BG_MID,
            fg=Theme.TEXT_WHITE,
            insertbackground=Theme.ACCENT,
            relief="flat",
        )
        password_entry.pack(fill="x", ipady=8)

        # Status message
        status_label = tk.Label(
            self.content,
            text="",
            font=("Arial", 10, "italic"),
            bg=Theme.BG_DARK,
            fg=Theme.TEXT_GRAY,
            wraplength=700,
            justify="left",
        )
        status_label.pack(pady=10)

        # State holder
        login_state = {"client": None, "phone_sent": False, "phone": None}

        def update_status(msg: str, color: str = Theme.TEXT_GRAY):
            status_label.config(text=msg, fg=color)
            self.root.update_idletasks()

        def send_code():
            phone = phone_var.get().strip()
            if not phone or phone == "+" or len(phone) < 8:
                messagebox.showerror("Invalid Phone", "Enter a valid phone number with country code.")
                return

            update_status("📡 Connecting to Telegram...", Theme.ACCENT)

            def worker():
                try:
                    from telethon.sync     import TelegramClient
                    from telethon.sessions import StringSession

                    api_id   = int(telegram_creds["api_id"])
                    api_hash = telegram_creds["api_hash"]

                    client = TelegramClient(StringSession(), api_id, api_hash)
                    client.connect()

                    update_status("📨 Sending login code...", Theme.ACCENT)
                    sent = client.send_code_request(phone)

                    login_state["client"]     = client
                    login_state["phone_sent"] = True
                    login_state["phone"]      = phone

                    self.root.after(0, lambda: code_frame.pack(fill="x"))
                    self.root.after(0, lambda: password_frame.pack(fill="x"))
                    self.root.after(0, lambda: code_entry.focus_set())
                    update_status(
                        f"✅ Code sent! Check your Telegram app.\n"
                        f"Enter the code below and click 'Verify'.",
                        Theme.SUCCESS,
                    )
                    self.root.after(0, lambda: send_btn.config(text="Verify Code  →", command=verify_code))

                except Exception as e:
                    update_status(f"❌ Error: {e}", Theme.DANGER)

            threading.Thread(target=worker, daemon=True).start()

        def verify_code():
            code = code_var.get().strip()
            if not code:
                messagebox.showerror("Missing Code", "Enter the login code from Telegram.")
                return

            if not login_state["client"]:
                messagebox.showerror("Not Connected", "Click 'Send Code' first.")
                return

            update_status("🔐 Verifying code...", Theme.ACCENT)

            def worker():
                try:
                    from telethon.errors import (
                        SessionPasswordNeededError, PhoneCodeInvalidError,
                    )
                    client = login_state["client"]
                    phone  = login_state["phone"]

                    try:
                        client.sign_in(phone=phone, code=code)
                    except SessionPasswordNeededError:
                        password = password_var.get().strip()
                        if not password:
                            update_status(
                                "🔒 2FA enabled — enter your 2FA password above.",
                                Theme.WARNING,
                            )
                            return
                        client.sign_in(password=password)

                    me = client.get_me()
                    session_string = client.session.save()
                    client.disconnect()

                    _save_cred("telegram", "session_string", session_string)

                    self.configured.append("📱 Telegram API")

                    update_status(
                        f"✅ Logged in as {me.first_name} (@{me.username or 'no username'})!",
                        Theme.SUCCESS,
                    )

                    # Move to next service after 2 sec
                    self.root.after(2000, lambda: (
                        setattr(self, "current_page", self.current_page + 1),
                        self._next_service(),
                    ))

                except Exception as e:
                    update_status(f"❌ Login failed: {e}", Theme.DANGER)

            threading.Thread(target=worker, daemon=True).start()

        # Footer buttons
        self._make_button(
            self.footer,
            "← Back",
            lambda: self._show_service(SERVICES[self.current_page]),
        ).pack(side="left", padx=5)

        self._make_button(
            self.footer,
            "Skip Login",
            lambda: (
                setattr(self, "current_page", self.current_page + 1),
                self._next_service(),
            ),
        ).pack(side="left", padx=5)

        send_btn = self._make_button(
            self.footer,
            "Send Code  →",
            send_code,
            is_primary=True,
        )
        send_btn.pack(side="right", padx=5)

        phone_entry.focus_set()

    # ═════════════════════════════════════════
    # COMPLETE PAGE
    # ═════════════════════════════════════════
    def _show_complete(self):
        self._clear_content()
        self._update_progress(len(SERVICES) + 1, len(SERVICES) + 1)

        tk.Label(
            self.content,
            text="✅",
            font=("Arial", 80),
            bg=Theme.BG_DARK,
            fg=Theme.SUCCESS,
        ).pack(pady=(20, 5))

        tk.Label(
            self.content,
            text="Setup Complete!",
            font=("Arial", 22, "bold"),
            bg=Theme.BG_DARK,
            fg=Theme.TEXT_WHITE,
        ).pack(pady=(0, 10))

        if self.configured:
            tk.Label(
                self.content,
                text="✅ Configured services:",
                font=("Arial", 12, "bold"),
                bg=Theme.BG_DARK,
                fg=Theme.SUCCESS,
            ).pack(pady=(15, 5))

            list_frame = tk.Frame(self.content, bg=Theme.BG_LIGHT, padx=20, pady=12)
            list_frame.pack(pady=5)

            for s in self.configured:
                tk.Label(
                    list_frame,
                    text=f"  • {s}",
                    font=("Arial", 11),
                    bg=Theme.BG_LIGHT,
                    fg=Theme.TEXT_WHITE,
                    anchor="w",
                ).pack(fill="x", pady=2)
        else:
            tk.Label(
                self.content,
                text=(
                    "⚠️ No services configured.\n"
                    "The tracer will use free scraping only."
                ),
                font=("Arial", 11),
                bg=Theme.BG_DARK,
                fg=Theme.WARNING,
                justify="center",
            ).pack(pady=15)

        tk.Label(
            self.content,
            text=(
                "\n🎯 You can now use the number tracer!\n\n"
                'Try saying:  "Jarvis, trace this number +1234567890"'
            ),
            font=("Arial", 11),
            bg=Theme.BG_DARK,
            fg=Theme.TEXT_GRAY,
            justify="center",
        ).pack(pady=15)

        tk.Label(
            self.content,
            text="ℹ️ Re-run this wizard anytime from JARVIS",
            font=("Arial", 9, "italic"),
            bg=Theme.BG_DARK,
            fg=Theme.TEXT_DIM,
        ).pack(pady=5)

        # Footer
        self._make_button(
            self.footer,
            "✨ Close & Start Using JARVIS",
            self.root.destroy,
            is_primary=True,
        ).pack(side="right", padx=5)

    # ── Run the wizard ───────────────────────
    def run(self):
        self.root.mainloop()


# ═════════════════════════════════════════════
# PUBLIC API
# ═════════════════════════════════════════════
def run_number_tracer_setup():
    """Launch the GUI setup wizard."""
    try:
        wizard = SetupWizard()
        wizard.run()
    except Exception as e:
        print(f"[Wizard] GUI error: {e}")
        # Fallback: just print message
        print("\n[JARVIS] Setup wizard failed to start.")
        print("[JARVIS] You can configure credentials manually via JARVIS:")
        print("[JARVIS]   Say: 'Save credential telegram api_id YOUR_ID'\n")


def is_first_run_tracer() -> bool:
    """True if no number tracer credentials are configured."""
    services = [
        ("telegram",       "api_id"),
        ("ipqualityscore", "api_key"),
        ("numverify",      "api_key"),
        ("opencnam",       "sid"),
    ]
    for service, key in services:
        if _get_cred(service, key):
            return False
    return True


if __name__ == "__main__":
    run_number_tracer_setup()