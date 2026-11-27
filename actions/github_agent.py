# actions/github_agent.py
import subprocess
import re
import platform
import time
from pathlib import Path
from typing import Dict, Optional

# Cross-platform defaults
DEFAULT_CLONE_DIR = Path.home() / "jarvis_repos"
DEFAULT_CLONE_DIR.mkdir(parents=True, exist_ok=True)

OS_NAME = platform.system().lower()  # linux, darwin, windows

# Tool keyword mapping for intelligent selection
TOOL_KEYWORDS = {
    "phish": "zphisher",
    "phishing": "zphisher",
    "facebook": "zphisher",
    "google": "zphisher",
    "mega": "mega",
    "download": "mega",
    "meganz": "mega",
}


def _get_terminal_cmd() -> list:
    """Return appropriate terminal command for current OS."""
    if OS_NAME == "linux":
        for term in ["qterminal", "gnome-terminal", "xterm", "konsole"]:
            if subprocess.run(["which", term], capture_output=True).returncode == 0:
                return [term, "-e"]
    elif OS_NAME == "darwin":   # macOS
        return ["open", "-a", "Terminal"]
    elif OS_NAME == "windows":
        return ["start", "cmd.exe", "/c"]
    return ["echo", "No terminal found"]


def _scan_cloned_tools() -> Dict[str, Path]:
    tools = {}
    for folder in DEFAULT_CLONE_DIR.iterdir():
        if not folder.is_dir():
            continue
        name = folder.name.lower()
        tools[name] = folder
        tools[name.replace("-", "")] = folder

        if (folder / "zphisher.sh").exists():
            tools["zphisher"] = folder
        if any("mega" in f.name.lower() for f in folder.iterdir()):
            tools["mega"] = folder
    return tools


def _run_command(cmd: list, cwd: Optional[Path] = None, timeout: int = 60) -> str:
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return (result.stdout + "\n" + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return "⏰ Command timed out."
    except Exception as e:
        return f"❌ Error: {str(e)}"


def github_agent(parameters: dict, player=None, speak=None) -> str:
    action = parameters.get("action", "clone").lower()
    repo_input = parameters.get("repo") or parameters.get("url")
    request = parameters.get("request", "").lower()
    template = parameters.get("template") or parameters.get("option")
    target_url = parameters.get("target_url", "")
    mega_link = parameters.get("mega_link") or parameters.get("link")

    def log(msg: str):
        if player: player.write_log(f"[GitHubAgent] {msg}")
        print(f"[GitHubAgent] {msg}")

    def say(msg: str):
        if speak: speak(msg)

    cloned_tools = _scan_cloned_tools()

    # ====================== CLONE ANY GITHUB REPO ======================
    if action in ["clone", "clone_and_install"]:
        if not repo_input:
            return "❌ No GitHub repository provided."

        clone_url = repo_input if repo_input.startswith("http") else f"https://github.com/{repo_input}.git"
        repo_name = clone_url.rstrip("/").rstrip(".git").split("/")[-1]
        target_path = DEFAULT_CLONE_DIR / repo_name

        if target_path.exists():
            return f"⚠️ {repo_name} already exists.\nUse 'use' action with your request."

        log(f"Cloning {clone_url}")
        say(f"Cloning {repo_name}. Please wait...")

        cmd = ["git", "clone", "--depth", "1", "--recurse-submodules", clone_url, str(target_path)]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            if action == "clone_and_install":
                if (target_path / "setup.sh").exists():
                    say("Running setup...")
                    _run_command(["bash", "setup.sh"], target_path)
                elif (target_path / "requirements.txt").exists():
                    say("Installing dependencies...")
                    _run_command(["pip3", "install", "-r", "requirements.txt"], target_path)
            say(f"{repo_name} is ready.")
            return f"✅ Cloned successfully:\n{target_path}"
        except Exception as e:
            return f"❌ Clone failed: {str(e)}"

    # ====================== INTELLIGENT USE ======================
    if action in ["use", "run", "execute"]:
        if not request and not repo_input:
            return "❌ Please describe what you want to do (e.g. 'phish with Google' or 'download from mega')."

        tool_path = None
        tool_name = None

        if repo_input:
            key = repo_input.lower().split("/")[-1].replace(".git", "")
            tool_path = cloned_tools.get(key)
            tool_name = key
        else:
            for keyword, name in TOOL_KEYWORDS.items():
                if keyword in request:
                    tool_name = name
                    tool_path = cloned_tools.get(tool_name)
                    break
            if not tool_path:
                for name, path in cloned_tools.items():
                    if any(word in name for word in request.split()):
                        tool_path = path
                        tool_name = name
                        break

        if not tool_path or not tool_path.exists():
            return "❌ No matching cloned tool found. Please clone it first."

        log(f"Selected tool: {tool_path.name}")

        # ====================== ZPHISHER ======================
        if "zphisher" in tool_path.name.lower():
            say("Launching Zphisher.")
            template = template or "2"
            if OS_NAME == "linux":
                expect_script = f"""
spawn bash zphisher.sh
expect "Choose a template" {{ send "{template}\\r" }}
expect "Enter" {{ send "{target_url or 'https://example.com'}\\r" }}
expect eof
"""
                try:
                    output = subprocess.run(["expect", "-c", expect_script], 
                                          cwd=tool_path, capture_output=True, text=True, timeout=60).stdout
                    url_match = re.search(r'(https?://[^\s]+?(?:login|free|php|\.html))', output, re.IGNORECASE)
                    phishing_url = url_match.group(1) if url_match else "Link not captured"
                    return f"""✅ Zphisher finished!

**Phishing Link:** {phishing_url}

**Log:**
{output[-700:]}"""
                except Exception as e:
                    return f"⚠️ Zphisher error: {str(e)}"
            else:
                # Non-Linux: just open terminal
                subprocess.Popen([* _get_terminal_cmd(), "bash", "zphisher.sh"], cwd=tool_path)
                return f"✅ Zphisher opened in terminal on {OS_NAME}. Full automation is Linux-only."

        # ====================== MEGA.NZ ======================
        if "mega" in str(tool_path).lower() or "mega" in request:
            if not mega_link:
                say("Please provide the full Mega.nz link.")
                return "🔗 Please reply with the Mega.nz link you want to download."

            say("Downloading from Mega.nz...")
            for tool in ["megadl", "mega-get", "rclone"]:
                try:
                    if tool == "rclone":
                        result = _run_command(["rclone", "copy", mega_link, str(DEFAULT_CLONE_DIR / "mega_downloads")], timeout=180)
                    else:
                        result = _run_command([tool, mega_link], cwd=tool_path, timeout=180)
                    if "Downloaded" in result or "saved" in result.lower():
                        return f"✅ Mega download completed!\n\n{result}"
                except Exception:
                    continue
            return f"⚠️ Download started for {mega_link}. Check {DEFAULT_CLONE_DIR}"

        # ====================== GENERIC EXECUTION ======================
        say(f"Running {tool_path.name}...")
        for pattern in ["main.py", "run.sh", "start.sh", "*.sh"]:
            matches = list(tool_path.glob(pattern))
            if matches:
                file = matches[0]
                if file.suffix == ".py":
                    output = _run_command(["python3", str(file)], tool_path, timeout=30)
                else:
                    term_cmd = _get_terminal_cmd()
                    subprocess.Popen([*term_cmd, str(file)], cwd=tool_path)
                    return f"✅ {tool_path.name} launched in new terminal."
                return f"✅ {tool_path.name} executed.\n\n{output[-900:]}"

        return f"✅ Tool located at {tool_path}\nNo automatic launcher found. Opened folder for manual use."

    return "❌ Unknown action. Use: clone, clone_and_install, use, run, execute"


def get_declaration():
    return {
        "name": "github_agent",
        "description": (
            "Universal cross-platform GitHub Tool Manager. Can clone any GitHub repo. "
            "When given a task (phishing, mega download, recon, etc.), it scans all "
            "cloned tools, selects the best one, runs it, and returns clean results. "
            "Works on Linux, macOS, and Windows (with graceful degradation)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "clone | clone_and_install | use | run | execute"},
                "repo": {"type": "STRING", "description": "GitHub URL or owner/repo"},
                "request": {"type": "STRING", "description": "Natural language request e.g. 'phish with Google' or 'download from mega'"},
                "template": {"type": "STRING", "description": "Zphisher template number"},
                "target_url": {"type": "STRING", "description": "Target URL for tools"},
                "mega_link": {"type": "STRING", "description": "Full mega.nz link"},
            },
            "required": ["action"]
        }
    }