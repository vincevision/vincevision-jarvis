"""
dev_forge.py  —  JARVIS Dev Forge Agent
Builds, runs, tests and fixes code projects end-to-end.
Supports all major IDEs across Linux, Windows and macOS.
Uses Groq AI for code generation.
"""

import os
import sys
import platform
import subprocess
import shutil
import re
import time
import threading
import json
from pathlib import Path
from typing import Optional

from actions.dev_forge_ui import get_hud

# ── Platform ──────────────────────────────────────────────────────────────────
OS         = platform.system().lower()
IS_LINUX   = OS == "linux"
IS_WINDOWS = OS == "windows"
IS_MAC     = OS == "darwin"

# ── Projects root ─────────────────────────────────────────────────────────────
PROJECTS_DIR = Path.home() / "JarvisProjects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# IDE REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

IDE_REGISTRY = {
    "vscode": {
        "name":        "Visual Studio Code",
        "check":       ["code", "--version"],
        "open_linux":  "code {path}",
        "open_win":    "code {path}",
        "open_mac":    "code {path}",
        "install": {
            "linux":   [
                "sudo apt-get update -y",
                "sudo apt-get install -y wget gpg",
                'wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /tmp/packages.microsoft.gpg',
                'sudo install -o root -g root -m 644 /tmp/packages.microsoft.gpg /etc/apt/trusted.gpg.d/',
                'echo "deb [arch=amd64] https://packages.microsoft.com/repos/code stable main" | sudo tee /etc/apt/sources.list.d/vscode.list',
                "sudo apt-get update -y",
                "sudo apt-get install -y code",
            ],
            "windows": ["winget install Microsoft.VisualStudioCode --silent"],
            "mac":     ["brew install --cask visual-studio-code"],
        },
        "languages":   ["python", "javascript", "typescript", "go", "rust",
                        "c", "cpp", "html", "css", "bash", "json", "yaml",
                        "markdown", "php", "ruby", "swift", "kotlin", "java"],
    },
    "pycharm": {
        "name":        "PyCharm",
        "check":       ["pycharm", "--version"],
        "open_linux":  "pycharm {path}",
        "open_win":    "pycharm64.exe {path}",
        "open_mac":    "open -a PyCharm {path}",
        "install": {
            "linux":   ["sudo snap install pycharm-community --classic"],
            "windows": ["winget install JetBrains.PyCharm.Community"],
            "mac":     ["brew install --cask pycharm-ce"],
        },
        "languages":   ["python"],
    },
    "intellij": {
        "name":        "IntelliJ IDEA",
        "check":       ["idea", "--version"],
        "open_linux":  "idea {path}",
        "open_win":    "idea64.exe {path}",
        "open_mac":    "open -a 'IntelliJ IDEA' {path}",
        "install": {
            "linux":   ["sudo snap install intellij-idea-community --classic"],
            "windows": ["winget install JetBrains.IntelliJIDEA.Community"],
            "mac":     ["brew install --cask intellij-idea-ce"],
        },
        "languages":   ["java", "kotlin", "scala", "groovy"],
    },
    "androidstudio": {
        "name":        "Android Studio",
        "check":       ["studio", "--version"],
        "open_linux":  "studio {path}",
        "open_win":    "studio64.exe {path}",
        "open_mac":    "open -a 'Android Studio' {path}",
        "install": {
            "linux":   ["sudo snap install android-studio --classic"],
            "windows": ["winget install Google.AndroidStudio"],
            "mac":     ["brew install --cask android-studio"],
        },
        "languages":   ["kotlin", "java", "android"],
    },
    "webstorm": {
        "name":        "WebStorm",
        "check":       ["webstorm", "--version"],
        "open_linux":  "webstorm {path}",
        "open_win":    "webstorm64.exe {path}",
        "open_mac":    "open -a WebStorm {path}",
        "install": {
            "linux":   ["sudo snap install webstorm --classic"],
            "windows": ["winget install JetBrains.WebStorm"],
            "mac":     ["brew install --cask webstorm"],
        },
        "languages":   ["javascript", "typescript", "html", "css", "react",
                        "vue", "angular", "node"],
    },
    "clion": {
        "name":        "CLion",
        "check":       ["clion", "--version"],
        "open_linux":  "clion {path}",
        "open_win":    "clion64.exe {path}",
        "open_mac":    "open -a CLion {path}",
        "install": {
            "linux":   ["sudo snap install clion --classic"],
            "windows": ["winget install JetBrains.CLion"],
            "mac":     ["brew install --cask clion"],
        },
        "languages":   ["c", "cpp", "cmake"],
    },
    "sublime": {
        "name":        "Sublime Text",
        "check":       ["subl", "--version"],
        "open_linux":  "subl {path}",
        "open_win":    "subl.exe {path}",
        "open_mac":    "subl {path}",
        "install": {
            "linux": [
                "wget -qO - https://download.sublimetext.com/sublimehq-pub.gpg | sudo apt-key add -",
                'echo "deb https://download.sublimetext.com/ apt/stable/" | sudo tee /etc/apt/sources.list.d/sublime-text.list',
                "sudo apt-get update -y && sudo apt-get install -y sublime-text",
            ],
            "windows": ["winget install SublimeHQ.SublimeText.4"],
            "mac":     ["brew install --cask sublime-text"],
        },
        "languages":   ["python", "javascript", "html", "css", "ruby",
                        "php", "bash", "markdown"],
    },
    "neovim": {
        "name":        "Neovim",
        "check":       ["nvim", "--version"],
        "open_linux":  "x-terminal-emulator -e nvim {path}",
        "open_win":    "nvim {path}",
        "open_mac":    "open -a Terminal nvim {path}",
        "install": {
            "linux":   ["sudo apt-get install -y neovim"],
            "windows": ["winget install Neovim.Neovim"],
            "mac":     ["brew install neovim"],
        },
        "languages":   ["python", "javascript", "typescript", "c", "cpp",
                        "bash", "lua", "go", "rust"],
    },
    "eclipse": {
        "name":        "Eclipse",
        "check":       ["eclipse", "-version"],
        "open_linux":  "eclipse {path}",
        "open_win":    "eclipse.exe {path}",
        "open_mac":    "open -a Eclipse {path}",
        "install": {
            "linux":   ["sudo snap install eclipse --classic"],
            "windows": ["winget install EclipseAdoptium.EclipseIDE"],
            "mac":     ["brew install --cask eclipse-java"],
        },
        "languages":   ["java", "c", "cpp"],
    },
    "xcode": {
        "name":        "Xcode",
        "check":       ["xcode-select", "--version"],
        "open_linux":  None,
        "open_win":    None,
        "open_mac":    "open -a Xcode {path}",
        "install": {
            "linux":   None,
            "windows": None,
            "mac":     ["xcode-select --install"],
        },
        "languages":   ["swift", "objective-c", "ios", "macos"],
    },
}

# ── Language → best IDE map ───────────────────────────────────────────────────
LANGUAGE_IDE_MAP = {
    "python":      ["pycharm",       "vscode"],
    "javascript":  ["vscode",        "webstorm"],
    "typescript":  ["webstorm",      "vscode"],
    "java":        ["intellij",      "eclipse"],
    "kotlin":      ["intellij",      "androidstudio"],
    "android":     ["androidstudio", "intellij"],
    "swift":       ["xcode",         "vscode"],
    "c":           ["clion",         "vscode"],
    "cpp":         ["clion",         "vscode"],
    "go":          ["vscode",        "neovim"],
    "rust":        ["vscode",        "neovim"],
    "html":        ["vscode",        "webstorm"],
    "css":         ["vscode",        "webstorm"],
    "react":       ["vscode",        "webstorm"],
    "vue":         ["vscode",        "webstorm"],
    "php":         ["vscode",        "sublime"],
    "ruby":        ["vscode",        "sublime"],
    "bash":        ["vscode",        "neovim"],
    "lua":         ["vscode",        "neovim"],
}

# ── Language → run command ────────────────────────────────────────────────────
RUN_COMMANDS = {
    "python":     "python3 {entry}",
    "javascript": "node {entry}",
    "typescript": "npx ts-node {entry}",
    "java":       "javac {entry} && java {classname}",
    "kotlin":     "kotlinc {entry} -include-runtime -d out.jar && java -jar out.jar",
    "go":         "go run {entry}",
    "rust":       "cargo run",
    "c":          "gcc {entry} -o out && ./out",
    "cpp":        "g++ {entry} -o out && ./out",
    "bash":       "bash {entry}",
    "php":        "php {entry}",
    "ruby":       "ruby {entry}",
    "lua":        "lua {entry}",
    "swift":      "swift {entry}",
}

# ── Language → file extension ─────────────────────────────────────────────────
EXTENSIONS = {
    "python":      ".py",
    "javascript":  ".js",
    "typescript":  ".ts",
    "java":        ".java",
    "kotlin":      ".kt",
    "go":          ".go",
    "rust":        ".rs",
    "c":           ".c",
    "cpp":         ".cpp",
    "bash":        ".sh",
    "php":         ".php",
    "ruby":        ".rb",
    "lua":         ".lua",
    "swift":       ".swift",
    "html":        ".html",
    "css":         ".css",
}

# ── Groq models (in order of preference) ─────────────────────────────────────
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
    "llama3-8b-8192",
]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _run_cmd(cmd: str, cwd: str = None, timeout: int = 60) -> tuple[int, str]:
    """Run a shell command. Returns (returncode, output)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True,
            text=True, timeout=timeout, cwd=cwd
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode, output
    except subprocess.TimeoutExpired:
        return 1, "Command timed out."
    except Exception as e:
        return 1, f"Error: {e}"


def _run_steps(steps: list[str], cwd: str = None) -> tuple[bool, str]:
    """Run a list of shell commands in sequence."""
    for step in steps:
        code, out = _run_cmd(step, cwd=cwd, timeout=120)
        if code != 0:
            return False, f"Failed: {step}\n{out}"
    return True, "OK"


def _detect_language(task: str) -> str:
    """Detect programming language from task description."""
    task_lower = task.lower()
    checks = [
        (["python", "py ", "flask", "django", "fastapi",
          "pandas", "numpy", "pytorch", "tensorflow"], "python"),
        (["javascript", "js ", "node", "react", "vue",
          "express", "next.js"],                        "javascript"),
        (["typescript", "ts "],                         "typescript"),
        (["java ", ".java", "spring", "maven"],         "java"),
        (["kotlin", "android"],                         "kotlin"),
        (["swift", "ios", "swiftui"],                   "swift"),
        (["c++", "cpp", ".cpp"],                        "cpp"),
        ([" c ", ".c ", "c code"],                      "c"),
        (["go ", "golang"],                             "go"),
        (["rust", "cargo"],                             "rust"),
        (["bash", "shell script", "sh "],               "bash"),
        (["php"],                                       "php"),
        (["ruby", "rails"],                             "ruby"),
        (["lua"],                                       "lua"),
        (["html", "css", "webpage", "website"],         "html"),
    ]
    for keywords, lang in checks:
        if any(k in task_lower for k in keywords):
            return lang
    return "python"


def _sanitize_name(name: str) -> str:
    """Convert task description to a valid folder/file name."""
    name = re.sub(r"[^\w\s-]", "", name.lower())
    name = re.sub(r"[\s-]+", "_", name).strip("_")
    return name[:40] or "jarvis_project"


def _find_ide(language: str, preferred: str = None) -> Optional[tuple[str, dict]]:
    """Find the best available IDE. Returns (ide_key, ide_info) or None."""
    candidates = []
    if preferred:
        preferred = preferred.lower().replace(" ", "")
        if preferred in IDE_REGISTRY:
            candidates = [preferred]
    if not candidates:
        candidates = LANGUAGE_IDE_MAP.get(language, ["vscode"])
    if "vscode" not in candidates:
        candidates.append("vscode")

    for key in candidates:
        info = IDE_REGISTRY.get(key)
        if not info:
            continue
        try:
            subprocess.run(info["check"], capture_output=True, timeout=5)
            return key, info
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def _install_ide(ide_key: str, ide_info: dict, hud) -> bool:
    """Install an IDE. Returns True on success."""
    os_key = "linux" if IS_LINUX else ("windows" if IS_WINDOWS else "mac")
    steps  = ide_info["install"].get(os_key)
    if not steps:
        hud.log(f"{ide_info['name']} not available on this OS.", "warning")
        return False
    hud.set_phase(f"Installing {ide_info['name']}...", "install")
    ok, msg = _run_steps(steps)
    if ok:
        hud.log(f"{ide_info['name']} installed successfully.", "success")
    else:
        hud.log(f"Install failed: {msg[:200]}", "error")
    return ok


def _open_ide(ide_key: str, ide_info: dict, project_path: Path, hud):
    """Open the IDE with the project folder."""
    os_key  = f"open_{'linux' if IS_LINUX else ('win' if IS_WINDOWS else 'mac')}"
    cmd_tpl = ide_info.get(os_key)
    if not cmd_tpl:
        hud.log(f"No open command for {ide_info['name']} on this OS.", "warning")
        return
    cmd = cmd_tpl.format(path=str(project_path))
    hud.set_phase(f"Opening {ide_info['name']}...", "ide")
    threading.Thread(
        target=lambda: subprocess.Popen(cmd, shell=True),
        daemon=True
    ).start()
    time.sleep(2)
    hud.log(f"{ide_info['name']} opened with project.", "success")


# ─────────────────────────────────────────────────────────────────────────────
# GROQ AI
# ─────────────────────────────────────────────────────────────────────────────

def _get_groq_key() -> str:
    """Get Groq API key from credential manager or config file."""
    # Try credential manager first
    try:
        from core.credential_manager import get_credential
        key = get_credential("groq", "api_key")
        if key:
            return key
    except Exception:
        pass

    # Fall back to api_keys.json
    try:
        cfg = Path(__file__).resolve().parent.parent / "config" / "api_keys.json"
        data = json.loads(cfg.read_text())
        return data.get("groq_api_key", "")
    except Exception:
        pass

    return ""


def _call_ai(prompt: str, api_key: str) -> str:
    """Call Groq to generate code or fix errors. Tries models in order."""
    from groq import Groq

    client = Groq(api_key=api_key)

    for model in GROQ_MODELS:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=8192,
            )
            result = resp.choices[0].message.content or ""
            if result.strip():
                print(f"[DevForge] ✅ AI response via {model} ({len(result)} chars)")
                return result
        except Exception as e:
            err = str(e).lower()
            print(f"[DevForge] ⚠️ Model {model} failed: {e}")
            # If rate limited or model unavailable try next
            if "rate" in err or "model" in err or "not found" in err:
                continue
            # Any other error — return it
            return f"AI_ERROR: {e}"

    return "AI_ERROR: All Groq models failed."


# ─────────────────────────────────────────────────────────────────────────────
# PROJECT PLANNING & CODE GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def _plan_project(task: str, language: str, api_key: str) -> dict:
    """Ask AI to plan the project structure."""
    prompt = f"""
You are an expert software architect.
The user wants: "{task}"
Language: {language}

Return ONLY a JSON object (no markdown, no explanation, no code fences) like this:
{{
  "project_name": "short_snake_case_name",
  "description": "one line description",
  "files": [
    {{"filename": "main.py", "description": "entry point"}}
  ]
}}

Rules:
- Keep filenames simple and valid
- Entry point must be FIRST in the list
- Maximum 6 files for simple tasks
- No test files unless user asked for tests
- Return ONLY the JSON, nothing else
"""
    raw = _call_ai(prompt, api_key)

    if raw.startswith("AI_ERROR"):
        print(f"[DevForge] Plan AI error: {raw}")
        ext = EXTENSIONS.get(language, ".py")
        return {
            "project_name": _sanitize_name(task),
            "description":  task,
            "files":        [{"filename": f"main{ext}", "description": "main file"}],
        }

    # Strip markdown fences if any
    raw = re.sub(r"```json|```", "", raw).strip()

    # Extract JSON if there's surrounding text
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        raw = match.group(0)

    try:
        return json.loads(raw)
    except Exception as e:
        print(f"[DevForge] JSON parse error: {e} — raw: {raw[:200]}")
        ext = EXTENSIONS.get(language, ".py")
        return {
            "project_name": _sanitize_name(task),
            "description":  task,
            "files":        [{"filename": f"main{ext}", "description": "main file"}],
        }


def _generate_file(
    task: str, language: str, filename: str,
    description: str, all_files: list, api_key: str
) -> str:
    """Generate complete code for a single file."""
    file_list = "\n".join(
        f"  - {f['filename']}: {f['description']}" for f in all_files
    )
    prompt = f"""
You are an expert {language} developer.
Task: "{task}"
You are writing the file: {filename} ({description})

Project files:
{file_list}

Rules:
- Write COMPLETE, WORKING, PRODUCTION-QUALITY code
- NO placeholders, NO TODOs, NO incomplete sections
- NO markdown fences — return ONLY raw source code
- Handle all errors properly
- Add brief comments for clarity
- The code must run successfully without any modification
- Make it fully functional and impressive
"""
    code = _call_ai(prompt, api_key)

    if code.startswith("AI_ERROR"):
        print(f"[DevForge] Code gen failed for {filename}: {code}")
        return f"# Generation failed for {filename}\n# Error: {code}\n"

    # Strip accidental markdown fences
    code = re.sub(r"^```[\w]*\n?", "", code.strip())
    code = re.sub(r"\n?```$", "", code.strip())

    return code


def _fix_errors(
    task: str, language: str, filename: str,
    code: str, error: str, attempt: int, api_key: str
) -> str:
    """Ask AI to fix code errors."""
    prompt = f"""
You are an expert {language} debugger.
Task: "{task}"
File: {filename}
Fix attempt: {attempt}

ERROR OUTPUT:
{error[:2000]}

CURRENT CODE:
{code}

Rules:
- Fix ALL errors shown above
- Return ONLY the complete corrected source code
- NO markdown, NO explanation — raw code only
- The fixed code must run without any errors
"""
    fixed = _call_ai(prompt, api_key)

    if fixed.startswith("AI_ERROR"):
        return code  # Return original if fix fails

    # Strip accidental markdown fences
    fixed = re.sub(r"^```[\w]*\n?", "", fixed.strip())
    fixed = re.sub(r"\n?```$", "", fixed.strip())

    return fixed


# ─────────────────────────────────────────────────────────────────────────────
# RUNTIME & TESTING
# ─────────────────────────────────────────────────────────────────────────────

def _get_run_command(language: str, entry_file: str, project_path: Path) -> str:
    """Build the run command for a language."""
    tpl       = RUN_COMMANDS.get(language, f"python3 {entry_file}")
    classname = Path(entry_file).stem
    return tpl.format(entry=entry_file, classname=classname)


def _has_errors(output: str) -> bool:
    """Check if run output contains errors."""
    error_patterns = [
        r"error:", r"traceback", r"exception",
        r"syntaxerror", r"nameerror", r"typeerror",
        r"importerror", r"modulenotfounderror",
        r"fatal error", r"segmentation fault",
        r"cannot find symbol", r"undefined reference",
        r"compilation failed", r"build failed",
    ]
    out_lower = output.lower()
    return any(re.search(p, out_lower) for p in error_patterns)


def _install_dependencies(language: str, project_path: Path, hud) -> bool:
    """Install runtime dependencies."""
    if language == "python":
        req = project_path / "requirements.txt"
        if req.exists():
            hud.log("Installing Python dependencies...", "install")
            code, out = _run_cmd(
                "pip install -r requirements.txt --break-system-packages",
                cwd=str(project_path), timeout=120
            )
            hud.log(
                "Dependencies installed." if code == 0 else f"Dep warning: {out[:150]}",
                "success" if code == 0 else "warning"
            )

    elif language == "javascript":
        pkg = project_path / "package.json"
        if pkg.exists():
            hud.log("Running npm install...", "install")
            code, out = _run_cmd("npm install", cwd=str(project_path), timeout=120)
            hud.log(
                "npm install done." if code == 0 else f"npm warning: {out[:150]}",
                "success" if code == 0 else "warning"
            )

    elif language == "rust":
        hud.log("Building Rust project...", "working")
        code, out = _run_cmd("cargo build", cwd=str(project_path), timeout=180)
        if code != 0:
            hud.log(f"Cargo build warning: {out[:150]}", "warning")

    return True


# ─────────────────────────────────────────────────────────────────────────────
# MAIN AGENT ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def dev_forge(parameters: dict, player=None, speak=None) -> str:
    """
    Main Dev Forge agent entry point.

    parameters:
        task        : str  — what to build
        language    : str  — programming language (auto-detected if empty)
        ide         : str  — preferred IDE (auto-picked if empty)
        open_ide    : bool — open IDE after building (default True)
        max_retries : int  — max AI fix attempts on errors (default 3)
        project_dir : str  — custom output directory
    """

    # ── API Key ───────────────────────────────────────────────────────────────
    api_key = _get_groq_key()
    if not api_key:
        return (
            "Dev Forge needs a Groq API key. "
            "Please add it via the credential manager or api_keys.json."
        )

    # ── Parameters ────────────────────────────────────────────────────────────
    task          = parameters.get("task", "").strip()
    language      = parameters.get("language", "").strip().lower()
    preferred_ide = parameters.get("ide", "").strip().lower()
    open_ide      = parameters.get("open_ide", True)
    max_retries   = int(parameters.get("max_retries", 3))
    custom_dir    = parameters.get("project_dir", "")

    if not task:
        return "Please tell me what you want to build."

    # ── HUD ───────────────────────────────────────────────────────────────────
    hud = get_hud()
    hud.show(task)
    hud.set_progress(0)
    hud.log(f"Task: {task}", "info")

    def done(msg: str, success: bool = True) -> str:
        hud.finish(msg, success)
        if speak:
            try:
                speak(msg)
            except Exception:
                pass
        return msg

    try:
        # ── PHASE 1: Detect language ──────────────────────────────────────────
        hud.set_phase("Analysing task...", "plan")
        hud.set_progress(5)
        if not language:
            language = _detect_language(task)
        hud.log(f"Language: {language}", "success")

        # ── PHASE 2: Plan project ─────────────────────────────────────────────
        hud.set_phase("Planning project structure...", "plan")
        hud.set_progress(10)
        plan         = _plan_project(task, language, api_key)
        project_name = _sanitize_name(plan.get("project_name", task))
        files        = plan.get("files", [])

        hud.log(f"Project name: {project_name}", "info")
        hud.log(f"Files to generate: {len(files)}", "info")
        for f in files:
            hud.log(f"  → {f['filename']}", "dim")

        # ── PHASE 3: Create workspace ─────────────────────────────────────────
        hud.set_phase("Creating workspace...", "folder")
        hud.set_progress(18)
        project_path = (
            Path(custom_dir) / project_name if custom_dir
            else PROJECTS_DIR / project_name
        )
        project_path.mkdir(parents=True, exist_ok=True)
        hud.log(f"Workspace: {project_path}", "success")

        # ── PHASE 4: Check / Install IDE ──────────────────────────────────────
        hud.set_phase("Checking IDE...", "ide")
        hud.set_progress(22)
        ide_result = _find_ide(language, preferred_ide)

        if ide_result:
            ide_key, ide_info = ide_result
            hud.log(f"IDE found: {ide_info['name']}", "success")
        else:
            hud.set_phase("IDE not found — installing...", "install")
            candidates = (
                [preferred_ide] if preferred_ide
                else LANGUAGE_IDE_MAP.get(language, ["vscode"])
            )
            ide_key  = candidates[0] if candidates else "vscode"
            ide_info = IDE_REGISTRY.get(ide_key, IDE_REGISTRY["vscode"])
            installed = _install_ide(ide_key, ide_info, hud)
            if not installed:
                ide_key  = "vscode"
                ide_info = IDE_REGISTRY["vscode"]
                _install_ide(ide_key, ide_info, hud)

        hud.set_progress(30)

        # ── PHASE 5: Generate code ────────────────────────────────────────────
        hud.set_phase("Generating code with Groq AI...", "code")
        step_size       = 25 / max(len(files), 1)
        generated_files = {}

        for i, file_info in enumerate(files):
            filename    = file_info["filename"]
            description = file_info.get("description", "")

            hud.set_status(f"Writing {filename}...", "working")
            hud.log(f"Generating {filename}...", "working")

            code = _generate_file(
                task, language, filename,
                description, files, api_key
            )

            file_path = project_path / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(code, encoding="utf-8")

            generated_files[filename] = code
            hud.log(f"✅ {filename} written ({len(code.splitlines())} lines)", "success")
            hud.set_progress(30 + (i + 1) * step_size)

        # ── PHASE 6: Install dependencies ─────────────────────────────────────
        hud.set_phase("Installing dependencies...", "install")
        hud.set_progress(58)
        _install_dependencies(language, project_path, hud)

        # ── PHASE 7: Run & Test ───────────────────────────────────────────────
        hud.set_phase("Running code...", "run")
        hud.set_progress(65)

        entry_file = files[0]["filename"] if files else f"main{EXTENSIONS.get(language, '.py')}"
        run_cmd    = _get_run_command(language, entry_file, project_path)
        hud.log(f"Run: {run_cmd}", "dim")

        skip_run = language in ("html", "css")
        if skip_run:
            hud.log("Web project — skipping terminal run.", "info")
            run_output = ""
            has_error  = False
        else:
            code_rc, run_output = _run_cmd(
                run_cmd, cwd=str(project_path), timeout=30
            )
            has_error = _has_errors(run_output) or code_rc != 0
            hud.log(
                f"Output: {run_output[:200]}",
                "info" if not has_error else "error"
            )

        hud.set_progress(75)

        # ── PHASE 8: Fix errors ───────────────────────────────────────────────
        fix_attempt = 0
        while has_error and fix_attempt < max_retries:
            fix_attempt += 1
            hud.set_phase(
                f"Fixing errors (attempt {fix_attempt}/{max_retries})...", "fix"
            )
            hud.log(f"Asking Groq to fix errors (attempt {fix_attempt})...", "warning")

            original_code = generated_files.get(entry_file, "")
            fixed_code    = _fix_errors(
                task, language, entry_file,
                original_code, run_output, fix_attempt, api_key
            )

            file_path = project_path / entry_file
            file_path.write_text(fixed_code, encoding="utf-8")
            generated_files[entry_file] = fixed_code
            hud.log(f"Fix applied to {entry_file}.", "success")

            hud.set_status("Re-running after fix...", "run")
            code_rc, run_output = _run_cmd(
                run_cmd, cwd=str(project_path), timeout=30
            )
            has_error = _has_errors(run_output) or code_rc != 0
            hud.set_progress(75 + fix_attempt * (10 / max_retries))

            if not has_error:
                hud.log(f"Fixed successfully on attempt {fix_attempt}!", "success")
                break
            else:
                hud.log(f"Still errors after attempt {fix_attempt}.", "warning")

        # ── PHASE 9: Open IDE ─────────────────────────────────────────────────
        hud.set_progress(90)
        if open_ide:
            _open_ide(ide_key, ide_info, project_path, hud)

        # ── PHASE 10: Final report ────────────────────────────────────────────
        hud.set_progress(98)
        hud.set_phase("Finalizing...", "working")

        if has_error:
            summary = (
                f"Project '{project_name}' built with warnings. "
                f"{fix_attempt} fix attempt(s) made. "
                f"Check the IDE for remaining issues."
            )
            return done(summary, success=False)

        summary = (
            f"Project '{project_name}' built successfully! "
            f"{len(files)} file(s) written, code runs without errors. "
            f"Opened in {ide_info['name']}. "
            f"Location: {project_path}"
        )
        return done(summary, success=True)

    except Exception as e:
        import traceback
        traceback.print_exc()
        hud.log(f"Dev Forge error: {e}", "error")
        return done(f"Dev Forge encountered an error: {e}", success=False)