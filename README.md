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

# 6. Launch — a setup popup appears on first run
python main.py
```

### 🔑 First-run setup popup

On first launch JARVIS opens a **setup popup** that prompts for your API keys —
no terminal editing required:

- **Gemini API key** (required) — free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
- **Groq API key** (optional fallback) — free at [console.groq.com/keys](https://console.groq.com/keys)

The popup has "Get free key" buttons that open the right page, a show/hide
toggle for each key, and a **Skip for now** option. Keys are saved to the
encrypted local vault **and** `config/api_keys.json`, then setup is marked
complete so the popup won't reappear.

Prefer to configure manually, or running headless? Either edit
`config/api_keys.json` directly, or let JARVIS fall back to terminal prompts
when no display is available. You can reopen the popup anytime with:

```bash
python -m core.api_key_setup
```

Everything is stored locally and gitignored. Optional credentials (Telegram,
email, etc.) can be added later by voice: *"Jarvis, update my credentials."*

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

### 🗑️ `uninstall.py` — clean removal

Reverses everything the installer created (desktop shortcuts, autostart, the
global `jarvis` command, app-menu entry, icon, sudoers rules) plus JARVIS's
local secrets and runtime data. **Safe by default:**

```bash
python uninstall.py                 # show the plan, ask before deleting
python uninstall.py --dry-run       # show the plan, delete nothing
python uninstall.py --yes           # remove without prompting
python uninstall.py --keep-data     # keep secrets/memory/reports/sessions
python uninstall.py --integrations-only   # only shortcuts/commands/sudoers
```

- **Dry-run in non-interactive shells** — nothing is deleted unless you confirm
  or pass `--yes`.
- **Never deletes the repo source or `.git`** — it prints the optional `rm -rf`
  command for that at the end, so you stay in control.
- System files that need root are skipped with a ready-to-run `sudo rm` command
  when you're not root.

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
| "Open the browser" / "Research quantum computing" | pc_controller |
| "Type 'hello world'" / "Open the terminal" | pc_controller |
| "Delete old_report.pdf" | pc_controller (→ trash) |
| "Check my Instagram inbox" / "DM @alice the photo" | instagram_manager |
| "Post this photo with #sunset" / "Schedule a reel" | instagram_manager |
| "Who doesn't follow me back?" | instagram_manager |
| "Upload this video to YouTube" / "Schedule a TikTok" | video_manager |
| "Run these three tasks in parallel" | task_control |
| "Start the dashboard" | dashboard_control |
| "Find cheap flights to Dubai next month" | flight_manager |
| "Watch NBO→LHR and alert me under $500" | flight_manager |

---

## ✈️ Flight Manager — cheap flights across sites

One command searches **Kayak, Google Flights, Skyscanner, Momondo, Expedia,
Kiwi, Booking.com and Trip.com**, then ranks what it finds.

| Action | What it does |
|---|---|
| `compare` | All sites, ranked best-first, with a 🏆 best pick |
| `search` | One site, parsed and ranked |
| `links` | Deep links only — instant, opens nothing |
| `flexible` | Cheapest day in a ±N-day window (keeps your trip length) |
| `watch` / `watches` / `check_watches` | Price tracking with 🔻 drop and  target alerts |
| `report` | Markdown comparison table (`save=true` → `reports/`) |
| `advice` | When-to-buy guidance for a date |
| `airports` | City → IATA lookup |
| `deep` | Hands Google Flights to `flight_finder` for Gemini parsing |
| `book` | Opens the site **for you to pay** — never enters card details |

**It understands plain language**
- Cities or codes: `Nairobi`, `JKIA`, `NBO` → all resolve to NBO
- Dates: `2026-12-15`, `next friday`, `in 3 weeks`, `+10d`, `Dec 15`, `15/12/2026`
- Filters: cabin, passengers, `stops=nonstop`, `max_price`, currency, preferred airlines

**Ranking isn't just price.** Offers are scored on price *plus* stops, duration
and your airline/baggage preferences — so a cheap 2-stop 18-hour itinerary
correctly ranks below a slightly pricier nonstop.

Set your defaults in `config/flights.json` (copy `config/flights.example.json`)
so *"flights to Dubai"* works without naming your home airport.

```
compare Nairobi → Dubai on 2026-12-15 returning 2026-12-22, max_price 600
flexible NBO → LHR on Dec 15, flex_days 3
watch NBO → DXB on 2026-12-15, target 400
```

**Honest limits:** deep links follow each site's published URL pattern and are
unit-tested offline, but were **not verified against the live sites** from the
build sandbox (no outbound access to those hosts). Page-text parsing is
best-effort and assumes an English locale — sites render with JavaScript and
change markup often, so `compare` may parse fewer offers than the page shows.
The deep links are the reliable part; the browser opens visibly so you can
always check for yourself. No FX rates are invented — prices are reported in
the currency the site returns.

---

## 🎬 Video Manager (YouTube + TikTok)

Creator-side publishing for **your own** channels, driven through the visible
browser so you can watch each step.

| Area | Actions |
|---|---|
| **Publish** | `upload` (video + title + description + tags + thumbnail + privacy), `schedule`, `queue`, `unschedule`, `run_due` |
| **Engage** | `comments`, `reply`, `like`, `subscribe` |
| **Organise** | `playlist_add` |
| **Insight** | `analytics`, `report`, `activity` |

Metadata is validated against each platform's **real limits before any browser
action** — YouTube titles ≤100 chars, descriptions ≤5000, tags ≤500 chars;
TikTok captions ≤2200. Privacy is checked per platform (`public/unlisted/private`
vs `public/friends/private`), so a rejected upload never half-publishes.
Publishing needs `confirm="VIDEO CONFIRMED"`; `dry_run=true` prints the exact plan.

> Watching, searching and summarising videos stays in `youtube_video.py` —
> this module is the publishing/studio side.

---

## ⚡ Parallel tasks + self-healing

The agent task queue now runs goals **concurrently** (3 slots by default) and
heals itself:

- **Transient** failures (timeouts, rate limits, 5xx, connection resets) retry
  with **exponential backoff**
- **Permanent** failures (unknown tool, permission denied, missing key, daily
  cap) **fail fast** instead of burning retries
- Optional `healer` hook can rewrite a goal between attempts; every rewrite is
  kept in the task's history

```bash
JARVIS_MAX_CONCURRENT=6 python main.py     # 1–16 slots
```

Voice/tool: `task_control` → `submit`, `status`, `list`, `stats`, `cancel`,
`retry`, `wait`.

---

## 🎙️ Wake word + barge-in

- **Wake word** — "Jarvis", "hey Jarvis", "ok Jarvis"… matched fuzzily, so
  "jervis" or "jarviz" still work. It only triggers when *addressed* — saying
  "the jarvis project is nice" won't wake it.
- **Barge-in** — interrupt JARVIS mid-sentence just by speaking. Energy-based,
  so it needs no speech-to-text: an echo guard ignores playback onset, speech
  must be sustained (~250 ms), and a cooldown stops it flapping.

Configure via `config/wake_word.json` (copy `config/wake_word.example.json`) or
`JARVIS_WAKE_WORD=0`. Tool: `wake_word_control` → `start`, `stop`, `status`,
`test`, `config`. Audio capture is optional — without `sounddevice` the text
matching and barge-in gating still work.

---

## 📊 Local dashboard

A **read-only** web dashboard — stdlib only, no build step:

```bash
python -m core.dashboard --port 8765      # or say "start dashboard"
python -m core.dashboard --json           # dump the same data as JSON
```

Shows security findings, the live task queue, Instagram/video activity against
daily caps, scheduled posts/uploads, and a health check. Auto-refreshes every
10 s. **No secrets are ever displayed** (API keys appear as set/missing only),
and every mutating HTTP verb is rejected with 405.

---

## 📸 Instagram Manager

Full management of **your own** account, built on the saved browser session
from `instagram_agent` — you sign in yourself once, JARVIS never sees or stores
your password.

| Area | Actions |
|---|---|
| **Messages** | `inbox`, `dm_read`, `dm` (text), `dm_image` (photo), `dm_many` |
| **Publishing** | `post`, `carousel` (2–10 files), `reel`, `story`, `schedule`, `queue`, `unschedule`, `run_due` |
| **Following** | `follow`, `unfollow`, `follow_many`, `followers`, `following`, `not_following_back`, `mutuals`, `fans`, `requests` |
| **Engagement** | `like`, `unlike`, `comment`, `comments`, `save` |
| **Profile** | `profile` (stats), `edit_bio`, `set_avatar`, `my_posts` |
| **Insight** | `activity` (usage today), `report` (markdown, `save=true` writes to `reports/`) |

**Smart helpers**
- Captions are composed for you — hashtags deduped and capped at 30, `@mentions`
  validated, text trimmed to Instagram's 2200-character limit
- Media is validated before upload: type, size, carousel count, reel-needs-video
- `schedule` queues a post locally; `run_due` publishes whatever is due

**Safety model**
- Every account-changing or publishing action needs `confirm="INSTAGRAM CONFIRMED"`
  — or `dry_run=true` to preview without touching anything
- **Daily caps + minimum spacing** between actions (tracked in
  `memory/instagram_state.json`) keep usage human-paced and protect the account
  from action blocks
- Batch actions accept **only handles you name**, capped at 10 per call — there
  is no scrape-then-spam loop; follower lists are for analysis only
- No CAPTCHA/2FA bypass, no password storage

```bash
# examples
"instagram login"                          # sign in yourself, session is saved
"instagram inbox"                          # read DM threads
"instagram dm @alice saying 'hey'"         # needs confirmation
"post sunset.jpg caption 'Golden hour' hashtags travel,sunset"
"who doesn't follow me back on instagram"
```

---

## 🖥️ PC control

The **`pc_controller`** agent drives the whole computer from one interface —
it orchestrates the existing low-level agents, so you can watch it work:

- **Open browser & research** — opens a *visible* browser, types your query so
  you can see it, and returns a spoken/written summary
- **Visible typing & input** — `type`, `click`, `hotkey`, `press`, `scroll`,
  `screenshot` (PyAutoGUI; move the mouse to a screen corner to abort)
- **Delete files** — say *"delete X"* and it goes to the **trash / recycle bin
  (recoverable)** by default. Permanent delete requires `confirm=true` and
  stays inside your safe user directories
- **Launch apps** — `open_app` for browser, terminal, files, calculator,
  editor, settings (cross-platform)
- **Run commands** — shell execution; catastrophic commands (`rm -rf /`,
  `mkfs`, `shutdown`, …) are blocked unless you pass `confirm=true`

### 🛡️ Background daemon — OFF by default

The proactive monitoring daemon (network/port/file/login/process watchers)
**does not auto-start**. Turn it on only if you want it:

- Voice: *"start daemon"* / *"stop daemon"* / *"daemon status"*
- Env var: `JARVIS_DAEMON=1 python main.py`
- Config: `config/daemon.json` → `{"enabled": true}` (copy from
  `config/daemon.example.json`)

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
