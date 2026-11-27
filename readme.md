# VINCEVISION — J.A.R.V.I.S (VinceVision) AI Assistant

This repository contains **JARVIS**, a voice-first, tool-using AI assistant with a custom **PyQt6 “HUD” UI**. It connects to **Google Gemini Live** for real-time audio input/output, then delegates actions to a set of Python “agents” and tool functions (browser automation, file operations, smart home controls, etc.).

The project is designed to run as a desktop application (full-screen, borderless) and includes a first-run setup flow to store your API key.

---

## What the code does (high level)

### 1) `main.py` — live voice + tool execution orchestrator
- Starts the GUI (`JarvisUI`).
- Launches **Gemini Live** (`google.genai.Client(...).aio.live.connect(...)`) with:
  - **Audio streaming** (mic capture -> Gemini input)
  - **Audio playback** (Gemini output PCM -> speakers)
  - A large list of tool/function declarations.
- Implements a runtime loop that:
  - Receives transcription and tool-call requests from Gemini.
  - Executes the requested tool by calling the appropriate function/agent.
  - Sends tool results back to Gemini.
- Includes special handling for:
  - `save_memory` (writes to `memory.memory_manager`)
  - `screen_process` (runs vision capture; instructs the model to stay silent so the vision module can speak)
  - `shutdown_jarvis` (terminates the process)
  - `agent_task` (queues multi-step tasks via `agent.task_queue`)

### 2) `ui.py` — full-screen HUD + controls
- Provides `JarvisUI`, a wrapper around a PyQt6 application.
- Shows an animated launch screen, then the main HUD:
  - **System monitor panel** (CPU/MEM/NET/GPU/TEMP via `psutil` + `nvidia-smi` when available)
  - **Activity log** (shows “You:” and “Jarvis:” messages)
  - **Response/status panel**
  - **Mute** toggle button
  - Text input for commands as a fallback to voice
- Implements a small **typing animation** for log lines.

### 3) `setup.py` — installs dependencies & Playwright browsers
- Installs Python requirements.
- Runs `playwright install` to fetch browser dependencies used by automation tools.

---

## Tools / agents

`main.py` defines tool declarations (function names + JSON parameter schemas) for many capabilities, and then routes each tool call to a Python implementation.

Examples include:
- **General computer control**: `open_app`, `browser_control`, `computer_control`, `desktop_control`, `file_controller`, `computer_settings`
- **Media & content**: `youtube_video`, `flight_finder`, `weather_report`
- **Communication**: `send_message`, `reminder`, Telegram integration via `telegram_bot`
- **File processing**: `file_processor` (image/PDF/doc/audio/video/archive conversions and analyses)
- **Specialized agents**:
  - `tiktok_agent`
  - `social_login`
  - `security_agent`
  - `email_agent`
  - `social_agent`
  - `trading_agent`
  - `number_tracer`
  - `smart_home`
  - `bluetooth_agent`
  - `dev_forge` (project builder)
  - `game_updater` (Steam/Epic updates — treated as a special-only tool)

---

## Configuration & first run

### Gemini API key
- On first launch, the UI prompts for your **Gemini API key**.
- The key and OS selection are written to:
  - `config/api_keys.json` (inside the repo folder)

`main.py` also supports reading the key via an internal credential manager (`core.credential_manager`).

### Optional Telegram bot
- `main.py` attempts to auto-start the Telegram bot if `actions/telegram_bot` configuration indicates it is enabled.

---

## How to run

### 1) Install dependencies
You can either run the project’s setup script directly (recommended), or install manually.

Example:
```bash
python setup.py
```

### 2) Start JARVIS
```bash
python main.py
```

When it starts, you’ll see the animated boot screen, then the HUD.

---

## Notes / dependencies

- The project uses **audio streaming** (`sounddevice`).
- It uses **PyQt6** for the UI.
- It uses **Playwright + browser automation** for web-related tools.
- It uses **Gemini Live** audio modalities.

---

## Project layout (top-level)

- `main.py` — orchestrates Gemini live session + tool routing + audio I/O
- `ui.py` — HUD UI (`JarvisUI`) and animated launch screen
- `actions/` — implementations for the tool functions/agents
- `core/` — shared utilities (prompt, credentials, etc.)
- `agent/` — task queue and agent orchestration
- `memory/` — long-term memory storage and formatting
- `config/` — API keys and runtime configuration

---

## Safety / operational guidance

This assistant can control your computer and interact with external services (browsers, messaging, smart-home devices, etc.). Use with care, especially for actions that can transmit data (messages/emails) or execute system commands through specialized tools.

