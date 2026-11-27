import os
import sys
import json
import importlib
import importlib.util
import re
import subprocess
from pathlib import Path


EVOLVED_DIR = Path("actions/evolved")
EVOLVED_DIR.mkdir(parents=True, exist_ok=True)

if str(EVOLVED_DIR.parent) not in sys.path:
    sys.path.insert(0, str(EVOLVED_DIR.parent))


# ── Package name mapping ──────────────────────────────────────────────────────
IMPORT_TO_PACKAGE = {
    "cv2":                "opencv-python",
    "PIL":                "Pillow",
    "sklearn":            "scikit-learn",
    "bs4":                "beautifulsoup4",
    "yaml":               "pyyaml",
    "dotenv":             "python-dotenv",
    "telegram":           "python-telegram-bot",
    "instagrapi":         "instagrapi",
    "instaloader":        "instaloader",
    "tweepy":             "tweepy",
    "selenium":           "selenium",
    "playwright":         "playwright",
    "pyautogui":          "pyautogui",
    "pyperclip":          "pyperclip",
    "pynput":             "pynput",
    "scapy":              "scapy",
    "paramiko":           "paramiko",
    "cryptography":       "cryptography",
    "nacl":               "pynacl",
    "Crypto":             "pycryptodome",
    "requests":           "requests",
    "httpx":              "httpx",
    "aiohttp":            "aiohttp",
    "websockets":         "websockets",
    "fastapi":            "fastapi",
    "flask":              "flask",
    "django":             "django",
    "sqlalchemy":         "sqlalchemy",
    "pymongo":            "pymongo",
    "redis":              "redis",
    "pandas":             "pandas",
    "numpy":              "numpy",
    "matplotlib":         "matplotlib",
    "scipy":              "scipy",
    "torch":              "torch",
    "tensorflow":         "tensorflow",
    "openai":             "openai",
    "anthropic":          "anthropic",
    "groq":               "groq",
    "rich":               "rich",
    "click":              "click",
    "typer":              "typer",
    "pydantic":           "pydantic",
    "arrow":              "arrow",
    "pendulum":           "pendulum",
    "psutil":             "psutil",
    "docker":             "docker",
    "kubernetes":         "kubernetes",
    "boto3":              "boto3",
    "speedtest":          "speedtest-cli",
    "ping3":              "ping3",
    "geocoder":           "geocoder",
    "geopy":              "geopy",
    "folium":             "folium",
    "qrcode":             "qrcode",
    "barcode":            "python-barcode",
    "pyzbar":             "pyzbar",
    "pytesseract":        "pytesseract",
    "speech_recognition": "SpeechRecognition",
    "pyttsx3":            "pyttsx3",
    "playsound":          "playsound",
    "pygame":             "pygame",
    "webdriver_manager":  "webdriver-manager",
    "undetected_chromedriver": "undetected-chromedriver",
}

BLACKLIST = {
    "os", "sys", "re", "json", "time", "datetime", "pathlib",
    "subprocess", "threading", "asyncio", "logging", "random",
    "string", "math", "collections", "itertools", "functools",
    "typing", "io", "struct", "socket", "ssl", "hashlib",
    "hmac", "base64", "urllib", "http", "email", "html",
    "xml", "csv", "sqlite3", "contextlib", "copy", "gc",
    "inspect", "importlib", "platform", "shutil", "tempfile",
    "glob", "fnmatch", "stat", "signal", "traceback", "warnings",
    "abc", "dataclasses", "enum", "weakref", "queue",
}


def _extract_imports(code: str) -> list:
    imports = []
    for line in code.split("\n"):
        line = line.strip()
        m = re.match(r"^import\s+([\w,\s]+)", line)
        if m:
            for part in m.group(1).split(","):
                name = part.strip().split(".")[0]
                if name:
                    imports.append(name)
        m = re.match(r"^from\s+([\w.]+)\s+import", line)
        if m:
            name = m.group(1).split(".")[0]
            if name:
                imports.append(name)
    return list(set(imports))


def _is_installed(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


def _install_package(package_name: str, player=None) -> bool:
    print(f"[EVO] 📦 Installing: {package_name}")
    if player:
        try:
            player.write_log(f"[EVO] 📦 Installing: {package_name}")
        except Exception:
            pass
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package_name, "--quiet"],
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode == 0:
            print(f"[EVO] ✅ Installed: {package_name}")
            if player:
                try:
                    player.write_log(f"[EVO] ✅ Installed: {package_name}")
                except Exception:
                    pass
            return True
        else:
            print(
                f"[EVO] ❌ Install failed: {package_name}\n"
                f"{result.stderr[:200]}"
            )
            return False
    except Exception as e:
        print(f"[EVO] ❌ Install error {package_name}: {e}")
        return False


def _auto_install_dependencies(code: str, player=None) -> dict:
    """Scan code for imports, check what is missing, install automatically."""
    imports = _extract_imports(code)
    results = {}
    for module in imports:
        if module in BLACKLIST or module.startswith("_"):
            continue
        if _is_installed(module):
            continue
        pip_name = IMPORT_TO_PACKAGE.get(module, module)
        ok = _install_package(pip_name, player=player)
        results[module] = ok
        if module == "playwright" and ok:
            try:
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    capture_output=True,
                    timeout=120
                )
            except Exception:
                pass
    return results


class EvolutionEngine:
    """
    Self-Evolution Engine.
    Builds, tests, and hot-loads new tools at runtime.
    Auto-installs dependencies. Generates interactive browser-aware tools.
    """

    def __init__(self, api_key: str):
        self.api_key       = api_key
        self.loaded_tools: dict = {}
        self.registry_path = EVOLVED_DIR / "_registry.json"
        self._load_registry()

    def _load_registry(self):
        if self.registry_path.exists():
            try:
                with open(self.registry_path) as f:
                    self.loaded_tools = json.load(f)
                print(
                    f"[EVO] 📦 Loaded {len(self.loaded_tools)} evolved tools"
                )
            except Exception:
                self.loaded_tools = {}

    def _save_registry(self):
        with open(self.registry_path, "w") as f:
            json.dump(self.loaded_tools, f, indent=2)

    def _extract_code(self, text: str) -> str:
        match = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text.strip()

    def _extract_json(self, text: str) -> dict:
        text = re.sub(r"```(?:json)?", "", text).strip().strip("`")
        try:
            return json.loads(text)
        except Exception:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except Exception:
                    pass
        return {}

    def _ask(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.2,
        max_tokens: int = 8192,
        log=None,
    ) -> str:
        """Ask AI via router — Gemini first, Groq fallback."""
        try:
            from core.ai_router import ask_ai
            result = ask_ai(
                prompt      = prompt,
                system      = system,
                preferred   = "gemini",
                temperature = temperature,
                max_tokens  = max_tokens,
                log         = log,
            )
            if result["success"]:
                print(
                    f"[EVO] ✅ {result['provider']} ({result['model']})"
                )
                return result["text"]
            print(f"[EVO] ❌ All providers failed: {result['error']}")
            return ""
        except Exception as e:
            print(f"[EVO] ❌ Router error: {e}")
            return ""

    async def generate_tool(
        self,
        requirement: str,
        tool_name: str = None,
        speak=None,
        player=None
    ) -> dict:
        """
        Generate a new interactive tool from a natural language requirement.
        Auto-installs required packages.
        Forces interactive UX patterns.
        """
        if speak:
            speak("Generating new capability, sir. One moment.")

        # ── Step 1: Design ────────────────────────────────────────────────────
        design_prompt = f"""You are an elite Python developer building tools for JARVIS AI.

REQUIREMENT: {requirement}

Design a new JARVIS tool module. Respond ONLY with a JSON object:
{{
  "tool_name": "snake_case_name",
  "description": "What this tool does (1-2 sentences)",
  "parameters": {{
    "param1": {{"type": "STRING", "description": "...", "required": false}},
    "param2": {{"type": "INTEGER", "description": "...", "required": false}}
  }},
  "actions": ["run", "status", "stop", "setup"],
  "packages": ["package1", "package2"],
  "interactive": true,
  "needs_browser": false,
  "needs_login": false
}}

Rules:
- Make ALL parameters optional (required: false) — tool prompts if missing
- Set needs_browser: true if it automates a website
- Set needs_login: true if it needs account credentials
- Include ALL pip packages needed in packages list
- Tool name must be snake_case
Respond ONLY with the JSON. No explanation."""

        design_text = self._ask(
            prompt      = design_prompt,
            temperature = 0.3,
            max_tokens  = 2048,
            log         = player,
        )
        if not design_text:
            return {"success": False, "error": "AI unavailable for design"}

        design = self._extract_json(design_text)
        if not design or "tool_name" not in design:
            return {
                "success": False,
                "error":   f"Could not parse design: {design_text[:200]}"
            }

        if tool_name:
            design["tool_name"] = tool_name

        tname = design["tool_name"]
        print(f"[EVO] 🎨 Designed: {tname}")

        # ── Step 1.5: Pre-install packages from design ────────────────────────
        packages = design.get("packages", [])
        if packages:
            print(f"[EVO] 📦 Pre-installing: {packages}")
            if player:
                try:
                    player.write_log(
                        f"[EVO] 📦 Installing: {', '.join(packages)}"
                    )
                except Exception:
                    pass
            if speak:
                speak(
                    f"Installing required packages: "
                    f"{', '.join(packages[:3])}"
                )
            for pkg in packages:
                _install_package(pkg, player=player)

        # ── Step 2: Build guidance based on tool type ─────────────────────────
        needs_browser = design.get("needs_browser", False)
        needs_login   = design.get("needs_login", False)

        browser_guidance = ""
        if needs_browser:
            browser_guidance = """
BROWSER AUTOMATION RULES:
- For Instagram: use instagrapi library (API-based, more reliable than selenium)
- If using selenium: use undetected_chromedriver to bypass bot detection
- Set headless=False so user can SEE the browser working
- Add random delays: time.sleep(random.uniform(1.5, 3.5)) between actions
- Log every major action: player.write_log("Clicking follow button...")
- Speak progress updates via speak() every 10 operations
- Handle popups and dialogs gracefully with try/except
- Take screenshot on error for debugging
"""

        login_guidance = ""
        if needs_login:
            login_guidance = """
CREDENTIAL MANAGEMENT RULES:
- NEVER hardcode credentials in the code
- Check parameters first: username = parameters.get("username", "")
- If empty: load from CREDENTIALS_FILE (Path.home() / ".jarvis_credentials" / tool_name + ".json")
- If still empty: return a clear message telling user exactly what to say
  Example: return "Please say: use insta_unfollow with username YOUR_USERNAME and password YOUR_PASSWORD"
- After successful login: save credentials to CREDENTIALS_FILE for next time
- Handle 2FA: detect it, speak alert, wait for user
- Handle wrong password: speak clear error message
- Handle account lock: speak warning, stop immediately
"""

        interactive_guidance = """
INTERACTIVE UX RULES (MANDATORY):
- Speak progress via speak() if speak is not None — every 10 iterations minimum
- Log everything via player.write_log() if player is not None
- Show counts: speak(f"Processed {i} of {total}...") 
- NEVER silently fail — always return descriptive result strings
- If required input missing: return message telling user EXACTLY what to provide
- Speak start message: speak("Starting X, sir.")
- Speak completion: speak(f"Done. Processed {count} items.")
- Save results to LOG_DIR = Path.home() / "JARVIS_logs" / tool_name
- Return summary: f"Done. Processed {n} items. Log saved to {log_file}"
- Add safety limits: max operations per session to prevent bans
- Add progress percentage: speak(f"Progress: {percent}%")
"""

        # ── Step 3: Generate code ─────────────────────────────────────────────
        code_prompt = f"""You are an elite Python developer building an INTERACTIVE JARVIS tool.

TOOL NAME: {tname}
DESCRIPTION: {design.get('description', requirement)}
PARAMETERS: {json.dumps(design.get('parameters', {}), indent=2)}
ACTIONS: {design.get('actions', ['run', 'status', 'setup'])}
PACKAGES AVAILABLE (already installed): {packages}
FULL REQUIREMENT: {requirement}

{browser_guidance}
{login_guidance}
{interactive_guidance}

Write a COMPLETE, WORKING, INTERACTIVE Python module with this structure:

import time
import random
import json
from pathlib import Path
from datetime import datetime

# Graceful imports
try:
    import package_name
    PACKAGE_OK = True
except ImportError:
    PACKAGE_OK = False

# ── Config ────────────────────────────────────────────────────────────────────
CREDENTIALS_FILE = Path.home() / ".jarvis_credentials" / "{tname}.json"
LOG_DIR          = Path.home() / "JARVIS_logs" / "{tname}"

def _log(player, msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{tname.upper()}] [{{ts}}] {{msg}}"
    print(line)
    if player:
        try: player.write_log(line[:300])
        except: pass

def _speak(speak, msg: str):
    if speak:
        try: speak(msg)
        except: pass

def _save_creds(data: dict):
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(json.dumps(data, indent=2))

def _load_creds() -> dict:
    try:
        if CREDENTIALS_FILE.exists():
            return json.loads(CREDENTIALS_FILE.read_text())
    except: pass
    return {{}}

def {tname}(parameters: dict, player=None, speak=None) -> str:
    action   = parameters.get("action", "run")
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # ── Get credentials ───────────────────────────────────────────────────────
    creds    = _load_creds()
    username = parameters.get("username") or creds.get("username", "")
    password = parameters.get("password") or creds.get("password", "")

    # ── Check missing credentials ─────────────────────────────────────────────
    if not username or not password:
        return (
            f"Credentials needed. Please say: "
            f"use {tname} with username YOUR_USERNAME and password YOUR_PASSWORD"
        )

    # ── Save credentials for next time ────────────────────────────────────────
    if username and password:
        _save_creds({{"username": username, "password": password}})

    _log(player, f"Starting {{action}} for {{username}}")
    _speak(speak, f"Starting {{action}}, sir.")

    # ── Main logic here ───────────────────────────────────────────────────────
    # [IMPLEMENT THE FULL LOGIC HERE]

    return f"Done. {{action}} completed for {{username}}."

DECLARATION = {{
    "name": "{tname}",
    "description": "{design.get('description', requirement)[:150]}",
    "parameters": {{
        "type": "OBJECT",
        "properties": {{
            "action":   {{"type": "STRING",  "description": "run | status | stop | setup"}},
            "username": {{"type": "STRING",  "description": "Account username"}},
            "password": {{"type": "STRING",  "description": "Account password"}},
            "count":    {{"type": "INTEGER", "description": "Max items to process per session"}},
            "delay":    {{"type": "NUMBER",  "description": "Delay between actions in seconds"}},
        }},
        "required": []
    }}
}}

Now write the FULL implementation replacing the [IMPLEMENT THE FULL LOGIC HERE] placeholder.
Make it genuinely functional, production quality, and fully interactive.
Handle all errors gracefully. Speak progress. Log everything.
For Instagram tools: use instagrapi (pip install instagrapi).
Write ONLY the complete Python code. No explanation."""

        code = self._ask(
            prompt      = code_prompt,
            temperature = 0.2,
            max_tokens  = 8192,
            log         = player,
        )
        if not code:
            return {"success": False, "error": "AI unavailable for code generation"}

        code = self._extract_code(code) if "```" in code else code.strip()
        if not code:
            return {"success": False, "error": "No code generated"}

        # ── Step 4: Syntax check + fix ────────────────────────────────────────
        tool_path = EVOLVED_DIR / f"{tname}.py"
        try:
            compile(code, str(tool_path), "exec")
        except SyntaxError as e:
            print(f"[EVO] ⚠️ Syntax error — fixing: {e}")
            code = self._fix_code(code, str(e), player)
            try:
                compile(code, str(tool_path), "exec")
            except SyntaxError as e2:
                return {
                    "success": False,
                    "error":   f"Syntax unfixable: {e2}"
                }

        # ── Step 5: Save ──────────────────────────────────────────────────────
        tool_path.write_text(code, encoding="utf-8")
        print(f"[EVO] 💾 Saved: {tool_path}")

        # ── Step 6: Auto-install from code scan ───────────────────────────────
        install_results = _auto_install_dependencies(code, player=player)
        if install_results:
            installed = [k for k, v in install_results.items() if v]
            failed    = [k for k, v in install_results.items() if not v]
            if installed:
                print(f"[EVO] ✅ Auto-installed: {installed}")
            if failed:
                print(f"[EVO] ⚠️ Could not install: {failed}")

        # ── Step 7: Extract declaration ───────────────────────────────────────
        declaration = self._extract_declaration(code, tname, design)

        # ── Step 8: Register ──────────────────────────────────────────────────
        self.loaded_tools[tname] = {
            "path":          str(tool_path),
            "declaration":   declaration,
            "description":   design.get("description", requirement),
            "packages":      packages,
            "interactive":   design.get("interactive", True),
            "needs_browser": needs_browser,
            "needs_login":   needs_login,
        }
        self._save_registry()

        if speak:
            speak(f"New capability '{tname}' is ready, sir.")

        return {
            "success":     True,
            "tool_name":   tname,
            "declaration": declaration,
            "path":        str(tool_path),
            "description": design.get("description", requirement),
        }

    def _hot_load_with_retry(
        self,
        tname: str,
        tool_path: Path,
        code: str,
        player=None
    ) -> tuple:
        """Try to hot-load, install missing packages on ImportError, retry."""
        for attempt in range(3):
            try:
                spec   = importlib.util.spec_from_file_location(
                    tname, str(tool_path)
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                sys.modules[f"evolved_{tname}"] = module
                print(f"[EVO] ✅ Hot-loaded: {tname}")
                return module, True

            except ImportError as e:
                missing = (
                    str(e)
                    .replace("No module named ", "")
                    .strip("'\"")
                    .split(".")[0]
                )
                print(f"[EVO] ❌ Missing: {missing} — installing...")
                pip_name = IMPORT_TO_PACKAGE.get(missing, missing)
                ok = _install_package(pip_name, player=player)
                if not ok or attempt >= 2:
                    print(f"[EVO] ❌ Could not resolve: {missing}")
                    return None, False

            except Exception as e:
                print(f"[EVO] ❌ Hot-load error for {tname}: {e}")
                return None, False

        return None, False

    def _extract_declaration(
        self, code: str, tname: str, design: dict
    ) -> dict:
        """Extract DECLARATION from code or build from design."""
        try:
            namespace = {}
            exec(compile(code, "<string>", "exec"), namespace)
            if "DECLARATION" in namespace:
                return namespace["DECLARATION"]
        except Exception:
            pass

        props    = {}
        required = []
        for pname, pinfo in design.get("parameters", {}).items():
            props[pname] = {
                "type":        pinfo.get("type", "STRING"),
                "description": pinfo.get("description", "")
            }
            if pinfo.get("required", False):
                required.append(pname)

        # Always add standard interactive params
        props.setdefault(
            "action",
            {"type": "STRING", "description": "run | status | stop | setup"}
        )
        props.setdefault(
            "username",
            {"type": "STRING", "description": "Account username"}
        )
        props.setdefault(
            "password",
            {"type": "STRING", "description": "Account password"}
        )
        props.setdefault(
            "count",
            {"type": "INTEGER", "description": "Max items to process per session"}
        )
        props.setdefault(
            "delay",
            {"type": "NUMBER", "description": "Delay between actions in seconds"}
        )

        return {
            "name":        tname,
            "description": design.get("description", tname),
            "parameters":  {
                "type":       "OBJECT",
                "properties": props,
                "required":   [],
            }
        }

    def _fix_code(self, code: str, error: str, player=None) -> str:
        """Ask AI to fix broken code."""
        prompt = (
            f"Fix this Python code. Error: {error}\n\n"
            f"CODE:\n{code}\n\n"
            f"Return ONLY the fixed Python code. No explanation."
        )
        fixed = self._ask(
            prompt      = prompt,
            temperature = 0.1,
            max_tokens  = 8192,
            log         = player,
        )
        if fixed:
            return (
                self._extract_code(fixed)
                if "```" in fixed
                else fixed.strip()
            )
        return code

    def hot_load(self, tool_name: str) -> tuple:
        """Hot-load a tool with auto-install on ImportError."""
        info = self.loaded_tools.get(tool_name)
        if not info:
            print(f"[EVO] ❌ Not in registry: {tool_name}")
            return None, None

        tool_path = Path(info["path"])
        if not tool_path.exists():
            print(f"[EVO] ❌ File missing: {tool_path}")
            return None, None

        code   = tool_path.read_text(encoding="utf-8")
        module, _ = self._hot_load_with_retry(tool_name, tool_path, code)
        return module, info.get("declaration", {})

    def hot_load_all(self) -> list:
        """Load all evolved tools. Returns declarations only."""
        declarations = []
        for tname in list(self.loaded_tools.keys()):
            _, decl = self.hot_load(tname)
            if decl:
                declarations.append(decl)
        return declarations

    def call_evolved_tool(
        self,
        tool_name: str,
        parameters: dict,
        player=None,
        speak=None
    ) -> str:
        """
        Call an evolved tool.
        Auto-installs missing dependencies on first call.
        """
        info = self.loaded_tools.get(tool_name)
        if not info:
            return (
                f"Tool '{tool_name}' not found. "
                f"Say: list evolved tools"
            )

        tool_path = Path(info["path"])
        if not tool_path.exists():
            return f"Tool file missing for '{tool_name}'."

        code   = tool_path.read_text(encoding="utf-8")
        module, _ = self._hot_load_with_retry(
            tool_name, tool_path, code, player
        )

        if not module:
            # Last resort: full dep scan and install
            print(f"[EVO] 🔄 Full dep scan for {tool_name}...")
            if player:
                try:
                    player.write_log(
                        f"[EVO] Installing dependencies for {tool_name}..."
                    )
                except Exception:
                    pass
            if speak:
                speak(
                    f"Installing dependencies for {tool_name}, sir. "
                    f"One moment."
                )
            _auto_install_dependencies(code, player=player)
            module, _ = self._hot_load_with_retry(
                tool_name, tool_path, code, player
            )

        if not module:
            return (
                f"Could not load '{tool_name}' — dependency install failed. "
                f"Try: Jarvis, install deps for {tool_name}"
            )

        func = getattr(module, tool_name, None)
        if not func:
            return f"Function '{tool_name}' not found in module."

        try:
            if speak:
                speak(f"Running {tool_name.replace('_', ' ')}, sir.")
            return func(
                parameters = parameters,
                player     = player,
                speak      = speak
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"Tool '{tool_name}' error: {e}"

    def install_tool_deps(self, tool_name: str, player=None) -> str:
        """Manually trigger dependency install for a tool."""
        info = self.loaded_tools.get(tool_name)
        if not info:
            return f"Tool '{tool_name}' not found."
        tool_path = Path(info["path"])
        if not tool_path.exists():
            return "Tool file not found."
        code    = tool_path.read_text(encoding="utf-8")
        results = _auto_install_dependencies(code, player=player)
        if not results:
            return f"No missing dependencies for '{tool_name}'."
        installed = [k for k, v in results.items() if v]
        failed    = [k for k, v in results.items() if not v]
        msg = []
        if installed:
            msg.append(f"Installed: {', '.join(installed)}")
        if failed:
            msg.append(f"Failed: {', '.join(failed)}")
        return " | ".join(msg) or "Done."

    def rebuild_tool(
        self,
        tool_name: str,
        player=None,
        speak=None
    ) -> str:
        """Delete and regenerate an existing tool with better prompts."""
        info = self.loaded_tools.get(tool_name)
        if not info:
            return f"Tool '{tool_name}' not found."
        requirement = info.get("description", tool_name)
        self.delete_evolved_tool(tool_name)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We are inside an async context — can't use run_until_complete
                return (
                    f"Please rebuild via voice: "
                    f"Jarvis, build a tool called {tool_name}, "
                    f"requirement is {requirement}"
                )
        except Exception:
            pass
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(
            self.generate_tool(
                requirement = requirement,
                tool_name   = tool_name,
                speak       = speak,
                player      = player,
            )
        )
        loop.close()
        if result["success"]:
            return f"Tool '{tool_name}' rebuilt successfully."
        return f"Rebuild failed: {result.get('error')}"

    def list_evolved_tools(self) -> str:
        if not self.loaded_tools:
            return "No evolved tools yet."
        lines = ["[EVOLVED TOOLS]"]
        for name, info in self.loaded_tools.items():
            flags = []
            if info.get("interactive"):   flags.append("🖥️ interactive")
            if info.get("needs_browser"): flags.append("🌐 browser")
            if info.get("needs_login"):   flags.append("🔑 login")
            flag_str = " ".join(flags)
            lines.append(
                f"  • {name}: "
                f"{info.get('description', '')[:80]} "
                f"{flag_str}"
            )
        return "\n".join(lines)

    def delete_evolved_tool(self, tool_name: str) -> str:
        if tool_name not in self.loaded_tools:
            return f"Tool '{tool_name}' not found."
        info = self.loaded_tools.pop(tool_name)
        path = Path(info.get("path", ""))
        if path.exists():
            path.unlink()
        self._save_registry()
        return f"Tool '{tool_name}' deleted."


# ── Singleton ─────────────────────────────────────────────────────────────────
_engine: EvolutionEngine | None = None


def get_evolution_engine(api_key: str = None) -> EvolutionEngine:
    global _engine
    if _engine is None:
        if not api_key:
            raise ValueError("api_key required on first call")
        _engine = EvolutionEngine(api_key)
    return _engine