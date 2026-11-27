# telegram_bot.py
"""
JARVIS Telegram Bot — Full Edition
────────────────────────────────────
Complete JARVIS control via Telegram.
All agents work directly from Telegram.
"""

import asyncio
import json
import sys
import threading
import time
import platform
import subprocess
import traceback
from pathlib import Path

_OS = platform.system()


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR    = _get_base_dir()
CONFIG_PATH = BASE_DIR / "config" / "telegram_config.json"


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(config: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


# ─────────────────────────────────────────────
# AGENT ROUTER
# ─────────────────────────────────────────────

def _route_command(text: str) -> dict:
    """
    Route a text command to the correct JARVIS agent.
    Returns dict with agent name and parameters.
    """
    text_lower = text.lower().strip()

    # ── Security Agent ───────────────────────────
    security_keywords = [
        "scan", "nmap", "port", "network scan", "wifi",
        "hack", "exploit", "vulnerability", "security",
        "arp", "whois", "traceroute", "ping", "netstat",
        "hydra", "sqlmap", "nikto", "metasploit",
        "monitor mode", "aircrack", "wifite",
        "open ports", "firewall",
    ]
    if any(kw in text_lower for kw in security_keywords):
        return {"agent": "security", "params": {"action": "custom", "command": text}}

    # ── Trading Agent ────────────────────────────
    trading_keywords = [
        "analyse", "analyze", "trading", "chart",
        "xauusd", "eurusd", "btcusd", "gold",
        "fibonacci", "fib", "position size",
        "risk calculator", "tradingview",
        "market structure", "liquidity",
        "order block", "fvg", "fair value",
    ]
    if any(kw in text_lower for kw in trading_keywords):
        # Extract symbol
        import re
        symbol = "BTC/USDT"
        for sym in [
            "XAUUSD", "GOLD", "EURUSD", "GBPUSD", "USDJPY",
            "BTCUSD", "ETHUSD", "SOLUSD", "US30", "NAS100",
            "AUDUSD", "USDCAD", "XAGUSD",
        ]:
            if sym.lower() in text_lower:
                symbol = sym
                break

        tf = "1h"
        for t in ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]:
            if t in text_lower or t.replace("h", " hour") in text_lower:
                tf = t
                break

        return {
            "agent":  "trading",
            "params": {
                "action":    "analyse",
                "symbol":    symbol,
                "timeframe": tf,
            },
        }

    # ── Email Agent ──────────────────────────────
    email_keywords = [
        "email", "inbox", "mail", "unread",
        "send email", "check email",
    ]
    if any(kw in text_lower for kw in email_keywords):
        if "send" in text_lower:
            return {"agent": "email", "params": {"action": "send"}}
        elif "unread" in text_lower:
            return {"agent": "email", "params": {"action": "unread"}}
        else:
            return {"agent": "email", "params": {"action": "check", "count": 5}}

    # ── YouTube ──────────────────────────────────
    youtube_keywords = [
        "play", "youtube", "song", "music", "video",
    ]
    if any(kw in text_lower for kw in youtube_keywords):
        query = text_lower
        for remove in ["play", "on youtube", "youtube", "jarvis"]:
            query = query.replace(remove, "")
        return {
            "agent":  "youtube",
            "params": {"action": "play", "query": query.strip()},
        }

    # ── Weather ──────────────────────────────────
    if "weather" in text_lower:
        import re
        city = "London"
        match = re.search(r"(?:weather|forecast)\s+(?:in|for|at)\s+(.+)", text_lower)
        if match:
            city = match.group(1).strip()
        return {"agent": "weather", "params": {"city": city}}

    # ── Web Search ───────────────────────────────
    search_keywords = ["search", "google", "find", "look up", "what is", "who is"]
    if any(kw in text_lower for kw in search_keywords):
        query = text_lower
        for remove in ["search", "google", "for", "look up", "find", "jarvis"]:
            query = query.replace(remove, "")
        return {
            "agent":  "web_search",
            "params": {"query": query.strip()},
        }

    # ── Number Tracer ────────────────────────────
    number_keywords = ["trace", "scam", "phone number", "caller", "spam"]
    if any(kw in text_lower for kw in number_keywords):
        import re
        phone_match = re.search(r"[\+]?[\d\s\-\(\)]{7,}", text)
        phone       = phone_match.group().strip() if phone_match else ""
        return {
            "agent":  "number_tracer",
            "params": {"action": "trace", "phone": phone},
        }

    # ── File Operations ──────────────────────────
    file_keywords = [
        "create folder", "create file", "delete file",
        "list files", "rename", "move file",
    ]
    if any(kw in text_lower for kw in file_keywords):
        return {
            "agent":  "file_controller",
            "params": {"action": "list", "path": "desktop"},
        }

    # ── Computer Control ─────────────────────────
    computer_keywords = [
        "volume", "brightness", "mute", "unmute",
        "screenshot", "lock screen", "shutdown",
        "restart", "dark mode", "wifi",
    ]
    if any(kw in text_lower for kw in computer_keywords):
        return {
            "agent":  "computer_settings",
            "params": {"description": text},
        }

    # ── Code Helper ──────────────────────────────
    code_keywords = [
        "write code", "build", "create app", "python",
        "javascript", "program", "script",
    ]
    if any(kw in text_lower for kw in code_keywords):
        return {
            "agent":  "code_helper",
            "params": {
                "action":      "write",
                "description": text,
                "language":    "python",
            },
        }

    # ── Smart Home ───────────────────────────────
    smart_keywords = [
        "light", "turn on", "turn off",
        "thermostat", "temperature", "smart home",
        "lock door", "unlock door",
    ]
    if any(kw in text_lower for kw in smart_keywords):
        action = "on" if "on" in text_lower else "off" if "off" in text_lower else "status"
        return {
            "agent":  "smart_home",
            "params": {"action": action, "device": text},
        }

    # ── Social Media ─────────────────────────────
    social_keywords = [
        "instagram", "twitter", "linkedin",
        "facebook", "social", "dm", "post",
    ]
    if any(kw in text_lower for kw in social_keywords):
        platform_name = "instagram"
        for p in ["instagram", "twitter", "linkedin", "facebook"]:
            if p in text_lower:
                platform_name = p
                break
        action = "notifications"
        if "dm" in text_lower or "message" in text_lower:
            action = "dms"
        elif "post" in text_lower:
            action = "post"
        return {
            "agent":  "social",
            "params": {"platform": platform_name, "action": action},
        }

    # ── Default: Use AI to answer ────────────────
    return {"agent": "ai", "params": {"query": text}}


def _execute_agent(route: dict) -> str:
    """Execute the routed agent and return result."""
    agent  = route["agent"]
    params = route["params"]

    try:
        if agent == "security":
            from actions.security_agent import security_agent
            return security_agent(params)

        elif agent == "trading":
            from actions.trading_agent import trading_agent
            return trading_agent(params)

        elif agent == "email":
            from actions.email_agent import email_agent
            return email_agent(params)

        elif agent == "youtube":
            from actions.youtube_video import youtube_video
            return youtube_video(params)

        elif agent == "weather":
            from actions.weather_report import weather_action
            return weather_action(params)

        elif agent == "web_search":
            from actions.web_search import web_search
            return web_search(params)

        elif agent == "number_tracer":
            from actions.number_tracer import number_tracer
            return number_tracer(params)

        elif agent == "file_controller":
            from actions.file_controller import file_controller
            return file_controller(params)

        elif agent == "computer_settings":
            from actions.computer_settings import computer_settings
            return computer_settings(params)

        elif agent == "code_helper":
            from actions.code_helper import code_helper
            return code_helper(params)

        elif agent == "smart_home":
            from actions.smart_home import smart_home
            return smart_home(params)

        elif agent == "social":
            from actions.social_agent import social_agent
            return social_agent(params)

        elif agent == "ai":
            from core.ai_router import ask_ai
            result = ask_ai(
                prompt=params.get("query", ""),
                system=(
                    "You are JARVIS, Tony Stark's AI assistant. "
                    "Be concise and helpful. Address user as sir."
                ),
                preferred="groq",
            )
            if result["success"]:
                return result["text"]
            return f"AI error: {result['error']}"

        else:
            return f"Unknown agent: {agent}"

    except Exception as e:
        traceback.print_exc()
        return f"Agent error ({agent}): {e}"


# ─────────────────────────────────────────────
# BOT CLASS
# ─────────────────────────────────────────────

class JarvisTelegramBot:

    def __init__(
        self,
        token:          str,
        authorized_ids: list[int],
        speak=None,
        on_command=None,
        player=None,
    ):
        self.token          = token
        self.authorized_ids = set(authorized_ids)
        self.speak          = speak
        self.on_command     = on_command
        self.player         = player
        self._app           = None
        self._loop          = None
        self._thread        = None
        self._running       = False
        self._pending_notif: list[tuple] = []

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="TelegramBotThread",
        )
        self._thread.start()
        print("[Telegram] 🤖 Bot thread started")

    def stop(self):
        self._running = False
        if self._loop and self._app:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._shutdown(), self._loop
                ).result(timeout=5)
            except Exception:
                pass

    async def _shutdown(self):
        try:
            if self._app:
                await self._app.updater.stop()
                await self._app.stop()
        except Exception:
            pass

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._start_bot())
        except Exception as e:
            print(f"[Telegram] Bot error: {e}")
        finally:
            self._running = False

    async def _start_bot(self):
        from telegram.ext import (
            Application, CommandHandler,
            MessageHandler, filters,
        )

        app = Application.builder().token(self.token).build()
        self._app = app

        # ── Commands ─────────────────────────────
        commands = {
            "start":       self._cmd_start,
            "help":        self._cmd_help,
            "status":      self._cmd_status,
            "screenshot":  self._cmd_screenshot,
            "mute":        self._cmd_mute,
            "unmute":      self._cmd_unmute,
            "stop":        self._cmd_stop,
            "ip":          self._cmd_ip,
            "processes":   self._cmd_processes,
            "security":    self._cmd_security,
            "scan":        self._cmd_scan,
            "emails":      self._cmd_emails,
            "weather":     self._cmd_weather,
            "trade":       self._cmd_trade,
            "search":      self._cmd_search,
            "files":       self._cmd_files,
            "social":      self._cmd_social,
            "code":        self._cmd_code,
            "smarthome":   self._cmd_smarthome,
            "trace":       self._cmd_trace,
            "credentials": self._cmd_credentials,
        }
        for name, handler in commands.items():
            app.add_handler(CommandHandler(name, handler))

        # ── Message handlers ─────────────────────
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._handle_message,
        ))
        app.add_handler(MessageHandler(
            filters.PHOTO, self._handle_photo,
        ))
        app.add_handler(MessageHandler(
            filters.Document.ALL, self._handle_document,
        ))

        print("[Telegram] ✅ Bot ready")

        async with app:
            await app.start()

            for uid in self.authorized_ids:
                try:
                    await app.bot.send_message(
                        chat_id=uid,
                        text=(
                            "🤖 JARVIS Online — Full Edition\n\n"
                            "All capabilities available via Telegram:\n"
                            "🔒 Security  📊 Trading  📧 Email\n"
                            "🎵 YouTube  🌤 Weather  🔍 Search\n"
                            "💻 Code  📱 Social  🏠 Smart Home\n"
                            "📞 Number Trace  📸 Screenshot\n\n"
                            "Type /help for commands or just tell me "
                            "what you need!"
                        ),
                    )
                except Exception as e:
                    print(f"[Telegram] Notify error {uid}: {e}")

            for chat_id, text in self._pending_notif:
                targets = [chat_id] if chat_id else list(self.authorized_ids)
                for uid in targets:
                    try:
                        await app.bot.send_message(chat_id=uid, text=text)
                    except Exception:
                        pass
            self._pending_notif.clear()

            await app.updater.start_polling(
                drop_pending_updates=True,
            )
            print("[Telegram] 📡 Polling started")

            while self._running:
                await asyncio.sleep(1)

            await app.updater.stop()
            await app.stop()

    # ─────────────────────────────────────────
    # SEND HELPERS
    # ─────────────────────────────────────────

    def send_message(self, text: str, chat_id: int = None):
        if not self._app or not self._loop or not self._running:
            self._pending_notif.append((chat_id, text))
            return
        targets = [chat_id] if chat_id else list(self.authorized_ids)
        for uid in targets:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._app.bot.send_message(
                        chat_id=uid,
                        text=str(text)[:4096],
                    ),
                    self._loop,
                )
                future.result(timeout=10)
            except Exception as e:
                print(f"[Telegram] Send error: {e}")

    def send_photo(self, image_path: str, caption: str = ""):
        if not self._app or not self._loop:
            return
        for uid in self.authorized_ids:
            try:
                with open(image_path, "rb") as f:
                    data = f.read()
                asyncio.run_coroutine_threadsafe(
                    self._app.bot.send_photo(
                        chat_id=uid, photo=data, caption=caption,
                    ),
                    self._loop,
                ).result(timeout=15)
            except Exception as e:
                print(f"[Telegram] Photo error: {e}")

    def notify(self, message: str):
        self.send_message(f"🔔 JARVIS Notification\n\n{message}")

    def _is_authorized(self, user_id: int) -> bool:
        if not self.authorized_ids:
            return True
        return user_id in self.authorized_ids

    # ─────────────────────────────────────────
    # AGENT EXECUTION WRAPPER
    # ─────────────────────────────────────────

    async def _run_agent_and_reply(self, update, route: dict):
        """Run an agent in background and send result to Telegram."""
        chat_id = update.effective_chat.id
        agent   = route["agent"]

        await update.message.reply_text(
            f"⚡ Processing ({agent})..."
        )

        def _execute():
            try:
                result = _execute_agent(route)
                # Split long messages
                chunks = [
                    result[i:i+4000]
                    for i in range(0, len(result), 4000)
                ]
                for chunk in chunks:
                    asyncio.run_coroutine_threadsafe(
                        self._app.bot.send_message(
                            chat_id=chat_id,
                            text=chunk,
                        ),
                        self._loop,
                    ).result(timeout=30)

            except Exception as e:
                asyncio.run_coroutine_threadsafe(
                    self._app.bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ Error: {e}",
                    ),
                    self._loop,
                )

        threading.Thread(target=_execute, daemon=True).start()

    # ─────────────────────────────────────────
    # COMMAND HANDLERS
    # ─────────────────────────────────────────

    async def _cmd_start(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized")
            return
        await update.message.reply_text(
            "🤖 JARVIS AI — Full Telegram Edition\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📋 Available commands:\n\n"
            "SYSTEM:\n"
            "  /status      — System stats\n"
            "  /screenshot  — Capture screen\n"
            "  /processes   — Running processes\n"
            "  /ip          — IP addresses\n"
            "  /mute        — Mute mic\n"
            "  /unmute      — Unmute mic\n"
            "  /credentials — Check saved credentials\n"
            "  /stop        — Shutdown JARVIS\n\n"
            "SECURITY:\n"
            "  /security    — Quick security scan\n"
            "  /scan <target> — Nmap scan\n\n"
            "TRADING:\n"
            "  /trade <symbol> — ICT analysis\n\n"
            "COMMUNICATION:\n"
            "  /emails      — Check inbox\n"
            "  /social <platform> — Social media\n\n"
            "TOOLS:\n"
            "  /weather <city> — Weather report\n"
            "  /search <query> — Web search\n"
            "  /files       — List desktop files\n"
            "  /code <desc> — Write code\n"
            "  /smarthome   — Smart home status\n"
            "  /trace <number> — Phone investigation\n\n"
            "OR just type any command naturally!\n"
            "Example: analyse gold on 1 hour"
        )

    async def _cmd_help(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        await update.message.reply_text(
            "📖 JARVIS Help\n\n"
            "Just type naturally:\n"
            "• scan 192.168.1.0/24\n"
            "• analyse XAUUSD on 4 hour\n"
            "• check my emails\n"
            "• weather in Tokyo\n"
            "• search latest AI news\n"
            "• play drake on youtube\n"
            "• write a python calculator\n"
            "• trace +1234567890\n"
            "• turn on living room light\n"
            "• check instagram DMs\n\n"
            "📸 Send a photo for AI analysis\n"
            "📎 Send a file for processing"
        )

    async def _cmd_status(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        try:
            import psutil
            cpu    = psutil.cpu_percent(interval=1)
            mem    = psutil.virtual_memory()
            disk   = psutil.disk_usage("/")
            uptime = time.time() - psutil.boot_time()
            up_str = f"{int(uptime//3600)}h {int((uptime%3600)//60)}m"

            await update.message.reply_text(
                f"📊 JARVIS Status\n\n"
                f"🖥️ CPU:    {cpu:.1f}%\n"
                f"🧠 RAM:    {mem.percent:.1f}% "
                f"({mem.used//1024**3:.1f}/{mem.total//1024**3:.1f} GB)\n"
                f"💾 Disk:   {disk.percent:.1f}%\n"
                f"⏱️ Uptime: {up_str}\n"
                f"💻 OS:     {_OS}\n"
                f"🤖 Status: ONLINE"
            )
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_screenshot(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        await update.message.reply_text("📸 Capturing...")
        try:
            import mss, mss.tools
            path = Path.home() / "Desktop" / "tg_screenshot.png"
            with mss.mss() as sct:
                shot = sct.grab(sct.monitors[0])
                mss.tools.to_png(shot.rgb, shot.size, output=str(path))
            with open(path, "rb") as f:
                await update.message.reply_photo(
                    photo=f,
                    caption=f"📸 {time.strftime('%H:%M:%S')}"
                )
            path.unlink(missing_ok=True)
        except Exception as e:
            await update.message.reply_text(f"Screenshot failed: {e}")

    async def _cmd_mute(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        if self.player:
            try: self.player.muted = True
            except: pass
        await update.message.reply_text("🔇 Muted")

    async def _cmd_unmute(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        if self.player:
            try: self.player.muted = False
            except: pass
        await update.message.reply_text("🎙 Unmuted")

    async def _cmd_stop(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        await update.message.reply_text("⛔ Shutting down JARVIS...")
        import os
        threading.Timer(2, lambda: os._exit(0)).start()

    async def _cmd_ip(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        try:
            import socket, requests
            local  = socket.gethostbyname(socket.gethostname())
            public = requests.get("https://api.ipify.org", timeout=5).text
            await update.message.reply_text(
                f"🌐 IP\n\nLocal:  {local}\nPublic: {public}"
            )
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_processes(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        try:
            import psutil
            procs = sorted(
                psutil.process_iter(["name", "cpu_percent", "memory_percent"]),
                key=lambda p: p.info.get("cpu_percent") or 0,
                reverse=True,
            )[:10]
            lines = ["📋 Top Processes\n"]
            for p in procs:
                name = (p.info.get("name") or "")[:18]
                cpu  = p.info.get("cpu_percent") or 0
                mem  = p.info.get("memory_percent") or 0
                lines.append(f"{name:<18} CPU:{cpu:5.1f}% MEM:{mem:4.1f}%")
            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_security(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        await update.message.reply_text("🔍 Scanning...")
        try:
            result = subprocess.run(
                ["ss", "-tulnp"],
                capture_output=True, text=True, timeout=10,
            )
            lines = result.stdout.strip().split("\n")[:15]
            await update.message.reply_text(
                f"🔒 Open Ports\n\n" + "\n".join(lines)
            )
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def _cmd_scan(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        target = " ".join(context.args) if context.args else ""
        if not target:
            await update.message.reply_text("Usage: /scan <target>")
            return
        route = {
            "agent":  "security",
            "params": {
                "action":  "nmap_scan",
                "target":  target,
                "options": "-sV",
            },
        }
        await self._run_agent_and_reply(update, route)

    async def _cmd_emails(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        route = {"agent": "email", "params": {"action": "check", "count": 5}}
        await self._run_agent_and_reply(update, route)

    async def _cmd_weather(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        city = " ".join(context.args) if context.args else "London"
        route = {"agent": "weather", "params": {"city": city}}
        await self._run_agent_and_reply(update, route)

    async def _cmd_trade(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        args   = context.args or ["XAUUSD"]
        symbol = args[0].upper()
        tf     = args[1] if len(args) > 1 else "1h"
        route  = {
            "agent":  "trading",
            "params": {
                "action":           "analyse",
                "symbol":           symbol,
                "timeframe":        tf,
                "open_tradingview": False,
                "draw_chart":       False,
            },
        }
        await self._run_agent_and_reply(update, route)

    async def _cmd_search(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        query = " ".join(context.args) if context.args else ""
        if not query:
            await update.message.reply_text("Usage: /search <query>")
            return
        route = {"agent": "web_search", "params": {"query": query}}
        await self._run_agent_and_reply(update, route)

    async def _cmd_files(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        route = {
            "agent":  "file_controller",
            "params": {"action": "list", "path": "desktop"},
        }
        await self._run_agent_and_reply(update, route)

    async def _cmd_social(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        args     = context.args or ["instagram"]
        platform = args[0].lower()
        action   = args[1] if len(args) > 1 else "notifications"
        route    = {
            "agent":  "social",
            "params": {
                "platform": platform,
                "action":   action,
            },
        }
        await self._run_agent_and_reply(update, route)

    async def _cmd_code(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        desc = " ".join(context.args) if context.args else ""
        if not desc:
            await update.message.reply_text(
                "Usage: /code <description>\n"
                "Example: /code a simple calculator"
            )
            return
        route = {
            "agent":  "code_helper",
            "params": {
                "action":      "write",
                "description": desc,
                "language":    "python",
            },
        }
        await self._run_agent_and_reply(update, route)

    async def _cmd_smarthome(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        route = {"agent": "smart_home", "params": {"action": "status"}}
        await self._run_agent_and_reply(update, route)

    async def _cmd_trace(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        phone = " ".join(context.args) if context.args else ""
        if not phone:
            await update.message.reply_text("Usage: /trace <phone number>")
            return
        route = {
            "agent":  "number_tracer",
            "params": {"action": "trace", "phone": phone},
        }
        await self._run_agent_and_reply(update, route)

    async def _cmd_credentials(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        try:
            from core.credential_manager import list_credentials
            creds = list_credentials()
            if not creds:
                await update.message.reply_text("No credentials saved.")
                return
            lines = ["🔑 Saved Credentials\n"]
            for svc, keys in creds.items():
                if svc == "setup":
                    continue
                lines.append(f"  {svc}: {', '.join(keys)}")
            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    # ─────────────────────────────────────────
    # MESSAGE HANDLERS
    # ─────────────────────────────────────────

    async def _handle_message(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            await update.message.reply_text("❌ Unauthorized")
            return

        text = update.message.text.strip()
        print(f"[Telegram] 📨 {update.effective_user.first_name}: {text}")

        # Route to correct agent
        route = _route_command(text)
        await self._run_agent_and_reply(update, route)

        # Also relay to JARVIS voice if connected
        if self.on_command:
            try:
                self.on_command(text)
            except Exception:
                pass

    async def _handle_photo(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        await update.message.reply_text("📸 Analysing image...")
        try:
            photo     = update.message.photo[-1]
            file      = await context.bot.get_file(photo.file_id)
            save_path = Path.home() / "Desktop" / f"tg_photo_{int(time.time())}.jpg"
            await file.download_to_drive(str(save_path))

            # Use AI to analyse the image
            try:
                from core.ai_router import ask_ai
                result = ask_ai(
                    prompt=(
                        "Describe what you see in this image. "
                        "Be concise and helpful."
                    ),
                    preferred="groq",
                )
                analysis = result["text"] if result["success"] else "Could not analyse."
            except Exception:
                analysis = "Image saved to desktop."

            await update.message.reply_text(
                f"📸 Image saved: {save_path.name}\n\n{analysis}"
            )

            if self.on_command:
                self.on_command(
                    f"[FILE_UPLOADED] path={save_path} | "
                    f"name={save_path.name} | type=jpg"
                )

        except Exception as e:
            await update.message.reply_text(f"Photo error: {e}")

    async def _handle_document(self, update, context):
        if not self._is_authorized(update.effective_user.id):
            return
        await update.message.reply_text("📎 Saving file...")
        try:
            doc       = update.message.document
            file      = await context.bot.get_file(doc.file_id)
            save_path = Path.home() / "Desktop" / doc.file_name
            await file.download_to_drive(str(save_path))

            size = save_path.stat().st_size
            size_str = (
                f"{size} B" if size < 1024
                else f"{size/1024:.1f} KB" if size < 1024**2
                else f"{size/1024**2:.1f} MB"
            )

            await update.message.reply_text(
                f"📎 File saved: {doc.file_name} ({size_str})\n"
                f"Tell me what to do with it!"
            )

            if self.on_command:
                self.on_command(
                    f"[FILE_UPLOADED] path={save_path} | "
                    f"name={doc.file_name} | size={size_str}"
                )

        except Exception as e:
            await update.message.reply_text(f"File error: {e}")


# ─────────────────────────────────────────────
# GLOBAL INSTANCE
# ─────────────────────────────────────────────

_bot: JarvisTelegramBot | None = None


def start_telegram_bot(
    token:          str,
    authorized_ids: list[int],
    speak=None,
    on_command=None,
    player=None,
) -> str:
    global _bot
    if _bot and _bot._running:
        return "Bot already running."
    if not token:
        return "No token."
    _bot = JarvisTelegramBot(
        token=token, authorized_ids=authorized_ids,
        speak=speak, on_command=on_command, player=player,
    )
    _bot.start()
    return f"Telegram bot started. Auth: {list(authorized_ids)}"


def stop_telegram_bot() -> str:
    global _bot
    if _bot:
        _bot.stop()
        _bot = None
        return "Bot stopped."
    return "Not running."


def send_telegram_notification(message: str) -> str:
    global _bot
    if _bot and _bot._running:
        _bot.notify(message)
        return f"Sent: {message[:50]}"
    return "Bot not running."


def get_bot() -> JarvisTelegramBot | None:
    return _bot


# ─────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────

def _run_setup() -> dict:
    print("\n" + "═" * 60)
    print("📱  TELEGRAM BOT SETUP")
    print("═" * 60)
    print()
    print("Step 1: Create a bot")
    print("  1. Telegram → @BotFather → /newbot")
    print("  2. Copy the bot token")
    print()
    print("Step 2: Get your user ID")
    print("  1. Telegram → @userinfobot")
    print("  2. Copy your ID number")
    print()

    token = input("Bot token: ").strip()
    if not token:
        return {}

    ids_str = input("Your user ID(s) (comma separated): ").strip()
    ids     = [int(x.strip()) for x in ids_str.split(",") if x.strip().isdigit()]

    config = {"token": token, "authorized_ids": ids, "enabled": True}
    _save_config(config)
    print(f"✅ Saved! Token: {token[:20]}... IDs: {ids}")
    return config


def telegram_agent(parameters: dict, player=None, speak=None) -> str:
    params  = parameters or {}
    action  = params.get("action", "status").lower().strip()
    message = params.get("message", "").strip()

    if action == "setup":
        config = _run_setup()
        if not config:
            return "Setup cancelled."
        return start_telegram_bot(
            token=config["token"],
            authorized_ids=config["authorized_ids"],
            speak=speak,
            on_command=getattr(player, "on_text_command", None),
            player=player,
        )
    elif action == "start":
        config = _load_config()
        if not config.get("token"):
            return "No config. Say 'Jarvis setup telegram bot'."
        return start_telegram_bot(
            token=config["token"],
            authorized_ids=config.get("authorized_ids", []),
            speak=speak,
            on_command=getattr(player, "on_text_command", None),
            player=player,
        )
    elif action == "stop":
        return stop_telegram_bot()
    elif action in ("notify", "send", "message"):
        if not message:
            return "Provide a message."
        return send_telegram_notification(message)
    elif action == "status":
        if _bot and _bot._running:
            config = _load_config()
            return f"Bot ONLINE. Auth: {config.get('authorized_ids', [])}"
        return "Bot not running."
    else:
        return f"Unknown: {action}. Use: setup, start, stop, notify, status"