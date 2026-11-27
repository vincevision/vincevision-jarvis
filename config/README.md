# ⚙️ config/

Real config files here are **gitignored** — they hold your keys, tokens, and
client data. The committed `*.example.json` files are safe templates.

## Setup

```bash
python doctor.py --fix     # copies each template to its real filename
```

Then edit the real files with your values:

| Template | Real file (gitignored) | What it's for |
|---|---|---|
| `api_keys.example.json` | `api_keys.json` | Gemini (required) + Groq (optional) API keys |
| `email_config.example.json` | `email_config.json` | IMAP/SMTP email fallback |
| `telegram_config.example.json` | `telegram_config.json` | Telegram bot remote control |
| `notion_config.example.json` | `notion_config.json` | Notion integration token + page/database ids |
| `scope.example.json` | `scope.json` | Pentest scope / Rules of Engagement |

`google_client_secret.json` (Google OAuth) has no template — download it from
Google Cloud Console; see [../docs/cloud_integrations.md](../docs/cloud_integrations.md).

The encrypted credential vault and OAuth tokens live in `.credentials/`
(also gitignored) and are managed by the setup wizard / agents.

**Never commit real config files.** If you add a new secret-bearing config,
add it to `.gitignore` and ship an `*.example.json` template instead.
