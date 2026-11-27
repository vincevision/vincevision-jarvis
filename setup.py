import subprocess
import sys
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def run(cmd: list, check: bool = True):
    print(f"  ▶ {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=check)
    except subprocess.CalledProcessError as e:
        print(f"  ⚠️  Command failed (non-fatal): {e}")

def create_directories():
    print("\n📁 Creating JARVIS directories...")
    dirs = [
        Path.home() / "jarvis_captures" / "wifi",
        Path.home() / "jarvis_captures" / "payloads",
        Path.home() / "jarvis_captures" / "osint",
        Path.home() / "jarvis_captures" / "darkweb",
        Path.home() / "jarvis_captures" / "keylogger",
        Path.home() / "jarvis_captures" / "exploits",
        Path.home() / "JarvisProjects",
        BASE_DIR / "config",
        BASE_DIR / "memory",
        BASE_DIR / "logs",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        print(f"  ✅ {d}")

def install_requirements():
    print("\n📦 Installing Python packages from requirements.txt...")
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

def install_playwright():
    print("\n🌐 Installing Playwright browsers...")
    run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
    run([sys.executable, "-m", "playwright", "install", "firefox"],  check=False)
    run([sys.executable, "-m", "playwright", "install-deps"],         check=False)

def install_osint_extras():
    print("\n🔍 Installing OSINT extras via pip...")
    packages = [
        "sherlock-project",
        "holehe",
        "h8mail",
        "stem",
    ]
    for pkg in packages:
        run([sys.executable, "-m", "pip", "install", pkg], check=False)

def check_api_keys():
    print("\n🔑 Checking API keys...")
    api_file = BASE_DIR / "config" / "api_keys.json"
    if api_file.exists():
        import json
        try:
            data    = json.loads(api_file.read_text())
            gemini  = "✅" if data.get("gemini_api_key") else "❌ Missing"
            groq    = "✅" if data.get("groq_api_key")   else "❌ Missing"
            print(f"  Gemini API : {gemini}")
            print(f"  Groq API   : {groq}")
        except Exception:
            print("  ⚠️  Could not parse api_keys.json")
    else:
        print("  ⚠️  config/api_keys.json not found")
        print(f"  Create it at: {api_file}")

def print_banner():
    print("""
  ╔══════════════════════════════════════════╗
  ║         JARVIS - Python Setup            ║
  ╚══════════════════════════════════════════╝
    """)

def print_summary():
    print("""
  ╔══════════════════════════════════════════╗
  ║         ✅ Setup Complete!               ║
  ╚══════════════════════════════════════════╝

  Run JARVIS:
    python main.py

  Capture directories:
    ~/jarvis_captures/wifi
    ~/jarvis_captures/payloads
    ~/jarvis_captures/osint
    ~/jarvis_captures/darkweb
    ~/jarvis_captures/keylogger
    ~/jarvis_captures/exploits

  🤖 Ready, sir.
    """)

# ── Main ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    print_banner()
    install_requirements()
    install_playwright()
    install_osint_extras()
    create_directories()
    check_api_keys()
    print_summary()