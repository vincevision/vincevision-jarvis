# ☁️ Cloud Integrations Pack

JARVIS now talks to **Gmail, Google Calendar, Google Docs, Google Drive and
Notion** through their official APIs — no browser windows, no fragile
scraping. Everything is voice-driven and wired into the Brain 2.0 planner.

> All credentials stay on your machine in gitignored config files. Nothing
> is ever committed.

---

## 🔑 One-time setup

### Google (covers Gmail + Calendar + Docs + Drive)

1. Go to <https://console.cloud.google.com/> and create a project.
2. Enable these APIs: **Gmail API, Google Calendar API, Google Docs API,
   Google Drive API**.
3. Configure the OAuth consent screen (External, add yourself as a test
   user), then create an **OAuth client ID → Desktop app**.
4. Download the client JSON and save it as:
   ```
   config/google_client_secret.json
   ```
5. Say **“connect google”** (or run the `google_auth` tool with
   `action=connect`). A browser window opens once for consent; the token is
   cached in `config/.credentials/google_token.json` and auto-refreshes.

Scopes requested: `gmail.modify`, `calendar`, `documents`, `drive.file`.
The `drive.file` scope means JARVIS can only see files it created or you
explicitly open with it — not your whole Drive.

### Notion

1. Create an internal integration at <https://www.notion.so/my-integrations>
   and copy its token.
2. Open the page or database JARVIS should use → **••• → Connections** → add
   your integration.
3. Say **“notion setup”** with the token and page id, e.g. the
   `notion_agent` tool with:
   ```json
   {"action": "setup", "token": "***", "parent_page_id": "...", "database_id": "..."}
   ```
   Stored in `config/notion_config.json` (gitignored).

---

## 🗣️ Voice / tool reference

### `google_auth` — connection manager
| Action | What it does |
|---|---|
| `connect` | Run the one-time OAuth consent flow |
| `status` | Show connection state |
| `logout` | Delete the cached token |
| `setup` | Print setup instructions |

### `gmail_agent` — official Gmail API
| Action | Example |
|---|---|
| `unread` | “Check my unread Gmail” |
| `list` / `search` | “Search Gmail for invoice” (`query`) |
| `read` | “Read message `<id>`” |
| `send` | “Email alice@acme.com subject 'Report' body '…'” (`to`, `subject`, `body`) |
| `labels` | List labels |

This is the reliable headless path; the older browser/IMAP `email_agent`
still exists as a fallback.

### `calendar_agent` — Google Calendar
| Action | Example |
|---|---|
| `today` | “What's on my calendar today?” |
| `upcoming` | “Show my next 7 days” (`days`) |
| `create` | “Schedule pentest kickoff tomorrow 10am” (`summary`, `start`, optional `end`, `location`, `description`, `duration_minutes`) |
| `delete` | “Cancel event `<id>`” |

Times: ISO (`2026-11-28T15:00`) or date-only for all-day events. Default
timezone **Africa/Nairobi** (override with `timezone`).

### `docs_agent` — Google Docs
| Action | Example |
|---|---|
| `create` | “Create a doc called Engagement Notes” (`title`, `text`) |
| `read` | “Read doc `<id>`” |
| `append` | “Append this to doc `<id>`” (`text`) |
| `export_report` | **“Export the pentest report to Google Docs”** — builds the report from your findings + scope and pushes it into a shareable Doc (`client`, `title`) |

### `drive_agent` — Google Drive
| Action | Example |
|---|---|
| `list` | “List my recent Drive files” |
| `search` | “Find report in Drive” (`query`) |
| `upload` | “Upload reports/pentest_report.md to Drive” (`path`, optional `folder_id`) |
| `download` | “Download file `<id>`” (`dest`) |

### `notion_agent` — Notion workspace
| Action | Example |
|---|---|
| `setup` / `status` | Connect / check |
| `search` | “Search Notion for runbook” (`query`) |
| `create_page` | “Create a Notion page called Recon Notes” (`title`, `content`) |
| `append` | “Append to Notion page `<id>`” (`text`) |
| `sync_findings` | **“Sync my findings to Notion”** — pushes every recorded finding into your Notion database (Name, Severity, CVSS, Target, Status) or a summary page |

---

## 🔗 Pentest workflow tie-in

The pack closes the loop on the Professional Pentest Kit:

```
scope_agent → findings_agent → report_agent
                                   │
                 ┌─────────────────┴─────────────────┐
                 ▼                                   ▼
        docs_agent.export_report            notion_agent.sync_findings
        (shareable Google Doc)              (Notion database / page)
                 │
                 ▼
        drive_agent.upload (archive the .md)
```

Example planner chain: *“Generate the pentest report for Acme, export it to
Google Docs, and sync findings to Notion.”*

---

## 🧪 Tests

47 offline tests in `tests/test_cloud_integrations.py` — no network, no
Google/Notion SDKs needed (all external calls are faked). Full suite:

```bash
python -m pytest -q tests/test_brain.py tests/test_email_browser.py \
  tests/test_social_browser.py tests/test_productivity_pack.py \
  tests/test_pentest_kit.py tests/test_cloud_integrations.py
```

## 🔒 Privacy & safety

- `config/google_client_secret.json`, `config/notion_config.json` and
  `config/.credentials/` are **gitignored**.
- Tokens refresh locally; no credentials are logged or committed.
- Drive uses the minimal `drive.file` scope.
- These agents read/write **your own** cloud data only — they are
  productivity integrations, not attack tooling.

## 📦 New dependencies

```
google-api-python-client>=2.100.0
google-auth>=2.23.0
google-auth-oauthlib>=1.1.0
google-auth-httplib2>=0.1.1
```

Notion uses `requests` (already installed). Install with
`pip install -r requirements.txt`.
