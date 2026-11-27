# 🤖 VINCEVISION — JARVIS

**A voice-controlled AI assistant for authorized security research, penetration
testing, and everyday productivity.** Speak to it, and it plans multi-step
tasks, calls 60+ tool agents, remembers context, and reports back — out loud.

> ⚠️ **Authorized use only.** The security tooling in this repo is for systems
> you own or have **written permission** to test. You are responsible for how
> you use it. See [docs/authorized_security_platform.md](docs/authorized_security_platform.md).

---

## ✨ What it does

- 🎙️ **Voice assistant** — real-time speech in/out (Gemini native audio), PyQt6 UI
- 🧠 **Brain 2.0** — multi-step planner, executor with retries/self-healing, long-term memory (SQLite FTS5)
- 🛡️ **Professional pentest kit** — scope/RoE enforcement, findings tracker, Markdown report generator
- ☁️ **Cloud integrations** — Gmail, Google Calendar, Google Docs, Google Drive, Notion (official APIs)
- 📧 **Email & social** — browser-session login flows (no passwords stored) + IMAP fallback
- 📝 **Productivity** — notes, system monitor, morning briefing, web search, weather, and more
- 🔌 **Extensible** — drop a new `actions/<name>_agent.py` in and wire it up; evolution engine for dynamic tools

---

## 🚀 Quick start (fresh clone)

**Requirements:** Python **3.11+** (3.10 minimum), a microphone/speakers for
voice mode, and a free [Gemini API key](https://aistudio.google.com/apikey).
Linux (Kali/Debian/Ubuntu) is the primary target; macOS/Windows work for most
non-OSINT agents.

```bash
# 1. Clone
git clone https://github.com/vincevision/vincevision-jarvis.git
cd vincevision-jarvis

# 2. Virtual environment
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Browser engine (for email/social/web agents)
playwright install chromium

# 5. Create config files from templates + runtime dirs
python doctor.py --fix

# 6. Add your API keys
#    Edit config/api_keys.json:
#      gemini_api_key  → https://aistudio.google.com/apikey   (required)
#      groq_api_key    → https://console.groq.com/keys        (optional fallback)

# 7. Verify setup
python doctor.py

# 8. Launch
python main.py
```

On first launch a **setup wizard** walks you through optional credentials
(Telegram, email, etc.). Everything is stored locally and gitignored.

### 🐧 Kali / Debian / Ubuntu full installer

For the complete security-suite setup (system packages, audio, browsers,
optional tooling):

```bash
sudo bash install.sh
```

### 🩺 `doctor.py` — your setup checklist

```bash
python doctor.py          # what's ready / what's missing, with fixes
python doctor.py --fix    # create dirs + copy config templates
python doctor.py --json   # machine-readable
```

It checks Python version, assets, runtime dirs, API keys, optional configs,
and dependencies — and tells you exactly how to fix each gap.

---

## 🔑 Configuration

All real config files are **gitignored**. Templates (`*.example.json`) are
committed; `doctor.py --fix` copies them into place.

| File | Purpose | Required? |
|---|---|---|
| `config/api_keys.json` | Gemini (+ optional Groq) API keys | ✅ yes |
| `config/google_client_secret.json` | Google OAuth client (Gmail/Calendar/Docs/Drive) | optional |
| `config/notion_config.json` | Notion integration token + page/database ids | optional |
| `config/email_config.json` | IMAP/SMTP email fallback | optional |
| `config/telegram_config.json` | Telegram bot remote control | optional |
| `config/scope.json` | Pentest scope / Rules of Engagement | for pentest kit |
| `config/.credentials/` | Encrypted credential vault + OAuth tokens | auto-created |

Cloud setup walkthroughs: [docs/cloud_integrations.md](docs/cloud_integrations.md).

---

## 🗣️ Example commands

| Say… | Agent |
|---|---|
| "Good morning" | briefing (weather, email, system, news) |
| "Take a note: …" / "Search my notes for …" | notes |
| "How's my system?" | system monitor |
| "Add 10.0.0.0/24 to scope" / "Is example.com authorized?" | scope |
| "Log a finding: SQL injection, critical, CVSS 9.8" | findings |
| "Generate the pentest report for Acme" | report |
| "Export the report to Google Docs" / "Sync findings to Notion" | docs / notion |
| "Check my unread Gmail" / "Email alice@acme.com …" | gmail |
| "What's on my calendar today?" / "Schedule kickoff Friday 10am" | calendar |
| "Search the web for …" / "Weather in Nairobi" | web search / weather |

---

## 🧪 Tests

Offline test suite (no network, no API keys, no SDKs needed):

```bash
pip install pytest
python -m pytest -q tests/
```

CI runs the suite on Python 3.11 and 3.12 for every push/PR.

---

## 📁 Project layout

```
main.py                  # voice loop, tool declarations, dispatch
agent/                   # Brain 2.0: planner, executor, error handler, task queue
core/                    # AI router, memory, credentials, setup wizard, env setup
actions/                 # 60+ tool agents (one file per capability)
config/                  # gitignored configs + committed *.example.json templates
docs/                    # per-feature guides
tests/                   # offline pytest suites
doctor.py                # setup checker / fixer
install.sh               # Kali/Debian/Ubuntu full installer
requirements.txt         # Python dependencies
```

### 📚 Feature guides

- [Brain 2.0](docs/brain.md) — planner, executor, memory
- [Professional Pentest Kit](docs/pentest_kit.md) — scope, findings, reports
- [Cloud Integrations](docs/cloud_integrations.md) — Gmail/Calendar/Docs/Drive/Notion
- [Email browser login](docs/email_browser.md) · [Social browser login](docs/social_browser.md)
- [Productivity Pack](docs/productivity_pack.md)
- [Authorized security platform](docs/authorized_security_platform.md)

---

## 🔧 Troubleshooting

- **`python doctor.py` first.** It names every gap and the exact fix.
- **Audio errors (PyAudio/portaudio):** install system audio libs
  (`sudo apt install portaudio19-dev` on Debian/Ubuntu) then reinstall pyaudio.
- **Browser agents fail as root:** run JARVIS as your desktop user, or let the
  built-in `sudo -u <user>` wrapper handle it. Headless mode always works.
- **PEP 668 "externally managed environment":** use a virtualenv (step 2 above).
- **Google/Notion "not connected":** follow [docs/cloud_integrations.md](docs/cloud_integrations.md).
- **Missing optional deps:** `pip install -r requirements.txt`, or install just
  the package `doctor.py` names.

---

## 🔒 Privacy & safety

- API keys, tokens, sessions, findings, reports, and memory stay **local** and
  are **gitignored** — never commit them.
- Browser login flows store **session cookies only**, never passwords.
- The pentest scope gate is **fail-closed**: targets must be explicitly
  authorized before testing.
- Use the security tooling **only** on systems you own or are written-authorized
  to test.

---

## 🤝 Contributing

1. Fork / branch, make changes.
2. Add offline tests under `tests/` and run `python -m pytest -q tests/`.
3. Keep new agents import-time stdlib-only where possible (lazy-import heavy SDKs).
4. Open a pull request — CI must be green.

Built with ❤️ for authorized security research and getting things done.
