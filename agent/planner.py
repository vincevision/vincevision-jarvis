"""
planner.py — VINCEVISION Brain 2.0
──────────────────────────────────
Goal → multi-step plan with DATA FLOW between steps.

Upgrade over the original planner:
  * Steps may reference earlier outputs with {{stepN}} placeholders.
  * Up to 8 steps (was 5), with explicit depends_on edges.
  * The plan carries success_criteria used by the executor's self-verification.
  * All LLM calls go through core.ai_router (correct google-genai SDK +
    automatic Gemini → Groq fallback). The previous code called the legacy
    `genai.configure` / `GenerativeModel` API through the new SDK import,
    which silently failed and collapsed every plan to a single web_search.
"""

import json
import re

from core.ai_router import ask_ai

MAX_STEPS = 8
_REF_RE = re.compile(r"\{\{\s*step\s*(\d+)\s*\}\}", re.IGNORECASE)


PLANNER_PROMPT = """You are the planning module of VINCEVISION, a personal AI assistant.
Your job: break any user goal into a sequence of steps using ONLY the tools listed below.

ABSOLUTE RULES:
- NEVER use generated_code or write Python scripts. It does not exist.
- Use web_search for ANY information retrieval, research, or current data.
- Use file_controller to save content to disk.
- Max 8 steps. Use the minimum steps needed.

DATA FLOW (important):
- A step MAY use the output of an EARLIER step by writing {{stepN}} inside any
  string parameter, where N is that earlier step's number.
- Example: step 3 writes a file whose content is "{{step1}}\n\n{{step2}}".
- Only reference steps that come BEFORE the current step. Never self-reference.
- List the steps you depend on in "depends_on".
- Prefer passing real results forward over writing placeholder text.

AVAILABLE TOOLS AND THEIR PARAMETERS:

open_app
  app_name: string (required)

web_search
  query: string (required) — write a clear, focused search query
  mode: "search" or "compare" (optional, default: search)
  items: list of strings (optional, for compare mode)
  aspect: string (optional, for compare mode)

game_updater
  action: "update" | "install" | "list" | "download_status" | "schedule" (required)
  platform: "steam" | "epic" | "both" (optional, default: both)
  game_name: string (optional)
  app_id: string (optional)
  shutdown_when_done: boolean (optional)

browser_control
  action: "go_to" | "search" | "click" | "type" | "scroll" | "get_text" | "press" | "close" (required)
  url: string (for go_to)
  query: string (for search)
  text: string (for click/type)
  direction: "up" | "down" (for scroll)

file_controller
  action: "write" | "create_file" | "read" | "list" | "delete" | "move" | "copy" | "find" | "disk_usage" (required)
  path: string — use "desktop" for Desktop folder
  name: string — filename
  content: string — file content (for write/create_file); may contain {{stepN}}

computer_settings
  action: string (required)
  description: string — natural language description
  value: string (optional)

computer_control
  action: "type" | "click" | "hotkey" | "press" | "scroll" | "screenshot" | "screen_find" | "screen_click" (required)
  text: string (for type)
  x, y: int (for click)
  keys: string (for hotkey, e.g. "ctrl+c")
  key: string (for press)
  direction: "up" | "down" (for scroll)
  description: string (for screen_find/screen_click)

screen_process
  text: string (required) — what to analyze or ask about the screen
  angle: "screen" | "camera" (optional)

send_message
  receiver: string (required)
  message_text: string (required); may contain {{stepN}}
  platform: string (required)

reminder
  date: string YYYY-MM-DD (required)
  time: string HH:MM (required)
  message: string (required)

desktop_control
  action: "wallpaper" | "organize" | "clean" | "list" | "task" (required)
  path: string (optional)
  task: string (optional)

youtube_video
  action: "play" | "summarize" | "trending" (required)
  query: string (for play)

weather_report
  city: string (required)

flight_finder
  origin: string (required)
  destination: string (required)
  date: string (required)

code_helper
  action: "write" | "edit" | "run" | "explain" (required)
  description: string (required)
  language: string (optional)
  output_path: string (optional)
  file_path: string (optional)

dev_agent
  description: string (required)
  language: string (optional)

notes_agent
  action: "add" | "search" | "list" | "read" | "update" | "delete" (required)
  text: string (for add/update)
  title: string (optional)
  tags: string (optional)
  query: string (for search)
  id: int (for read/update/delete)

system_agent
  action: "status" | "cpu" | "memory" | "disk" | "battery" | "network" | "processes" | "uptime" (required)

briefing_agent
  action: "briefing" (optional)
  city: string (optional, default Nairobi)

scope_agent
  action: "add" | "remove" | "list" | "check" | "authorize" (required)
  target: string (IP, CIDR, or domain)
  authorized_by: string (for authorize)

findings_agent
  action: "add" | "list" | "get" | "update" | "delete" | "summary" (required)
  title: string (for add)
  severity: "critical" | "high" | "medium" | "low" | "info"
  target: string (optional)
  id: int (for get/update/delete)

report_agent
  action: "generate" | "preview" (optional)
  client: string (optional)
  title: string (optional)

google_auth
  action: "connect" | "status" | "logout" | "setup" (optional)

gmail_agent
  action: "unread" | "list" | "search" | "read" | "send" | "labels" (optional)
  query: string (for search)
  id: string (for read)
  to / subject / body: strings (for send)

calendar_agent
  action: "today" | "upcoming" | "create" | "delete" (optional)
  summary: string (for create)
  start: ISO datetime or YYYY-MM-DD (for create)
  end: ISO datetime (optional)
  id: string (for delete)

docs_agent
  action: "create" | "read" | "append" | "export_report" (optional)
  title / text: strings
  id: string (for read/append)
  client: string (for export_report)

drive_agent
  action: "list" | "search" | "upload" | "download" (optional)
  query: string (for search)
  path: string (for upload)
  id: string (for download)

notion_agent
  action: "setup" | "status" | "search" | "create_page" | "append" | "sync_findings" (optional)
  token / parent_page_id / database_id: strings (for setup)
  query: string (for search)
  title / content: strings (for create_page)

pc_controller
  action: "open_browser" | "research" | "type" | "delete" | "open_app" | "run" | "click" | "hotkey" | "screenshot" | "close_browser" | "status" (required)
  url: string (for open_browser)
  query: string (for research)
  text: string (for type)
  path / name: strings (for delete)
  command: string (for run)
  confirm: "true" to allow permanent delete or destructive commands

instagram_manager
  action: "inbox" | "dm_read" | "dm" | "dm_image" | "post" | "carousel" | "reel" |
          "story" | "schedule" | "queue" | "unschedule" | "run_due" | "follow" |
          "unfollow" | "follow_many" | "followers" | "following" | "not_following_back" |
          "mutuals" | "fans" | "requests" | "like" | "unlike" | "comment" | "comments" |
          "save" | "profile" | "edit_bio" | "set_avatar" | "my_posts" | "activity" |
          "report" | "help" (required)
  username: string (single handle); usernames: comma-separated (batch, max 10)
  message / text: string (DM body or comment)
  media: file path (comma-separated for carousel); caption / hashtags / mentions: strings
  url: post URL (like / comment / save)
  when: unix timestamp (schedule); id: scheduled post id (unschedule)
  confirm: "INSTAGRAM CONFIRMED" for any account-changing action; dry_run: "true" to preview

video_manager
  action: "upload" | "schedule" | "queue" | "unschedule" | "run_due" | "comments" |
          "reply" | "like" | "subscribe" | "playlist_add" | "analytics" | "report" |
          "activity" | "help" (required)
  platform: "youtube" | "tiktok"; video: file path; title / description / tags: strings
  privacy: public | unlisted | private (youtube), public | friends | private (tiktok)
  thumbnail: image path; url: video URL; when: unix timestamp; id: scheduled upload id
  confirm: "VIDEO CONFIRMED" to publish; dry_run: "true" to preview the plan

task_control
  action: "submit" | "status" | "list" | "stats" | "cancel" | "retry" | "wait" (required)
  goal: string (for submit); priority: high | normal | low; task_id: string

wake_word_control
  action: "start" | "stop" | "status" | "test" | "config" (required)
  text: string (for test)

dashboard_control
  action: "start" | "stop" | "status" (required)
  port: number (optional, default 8765)

flight_manager
  action: "search" | "compare" | "links" | "flexible" | "watch" | "unwatch" |
          "watches" | "check_watches" | "report" | "advice" | "airports" |
          "deep" | "book" | "help" (required)
  origin / destination: city name or IATA code (Nairobi, NBO)
  date / return_date: 2026-12-15, 'next friday', 'in 3 weeks', 'Dec 15'
  trip: oneway | roundtrip; passengers: 1-9; cabin: economy|premium|business|first
  stops: any | nonstop | 1stop; max_price: number; currency: USD/KES/EUR...
  sites: comma-separated subset of kayak,google,skyscanner,momondo,expedia,kiwi,booking,trip
  flex_days: 0-7 (flexible); target: alert price (watch); id: watch id (unwatch)
  confirm: "FLIGHT CONFIRMED" for book (opens the site only; never enters payment)

EXAMPLES:

Goal: "research mechanical engineering and save it to a notepad file"
{
  "goal": "research mechanical engineering and save it to a notepad file",
  "success_criteria": "A desktop file exists containing real research about mechanical engineering",
  "steps": [
    {"step": 1, "tool": "web_search", "description": "Research overview", "parameters": {"query": "mechanical engineering overview definition history"}, "critical": true, "depends_on": []},
    {"step": 2, "tool": "web_search", "description": "Research applications", "parameters": {"query": "mechanical engineering applications and future trends"}, "critical": true, "depends_on": []},
    {"step": 3, "tool": "file_controller", "description": "Save combined research", "parameters": {"action": "write", "path": "desktop", "name": "mechanical_engineering.txt", "content": "MECHANICAL ENGINEERING RESEARCH\n\n{{step1}}\n\n{{step2}}"}, "critical": true, "depends_on": [1, 2]}
  ]
}

Goal: "find the weather in Nairobi and message it to John on WhatsApp"
{
  "goal": "find the weather in Nairobi and message it to John on WhatsApp",
  "success_criteria": "John receives a WhatsApp message containing the Nairobi weather",
  "steps": [
    {"step": 1, "tool": "weather_report", "description": "Get Nairobi weather", "parameters": {"city": "Nairobi"}, "critical": true, "depends_on": []},
    {"step": 2, "tool": "send_message", "description": "Send weather to John", "parameters": {"receiver": "John", "message_text": "Nairobi weather: {{step1}}", "platform": "WhatsApp"}, "critical": true, "depends_on": [1]}
  ]
}

Goal: "What is the price of Bitcoin"
{
  "goal": "What is the price of Bitcoin",
  "success_criteria": "The current Bitcoin price is retrieved",
  "steps": [
    {"step": 1, "tool": "web_search", "description": "Bitcoin price", "parameters": {"query": "Bitcoin price today USD"}, "critical": true, "depends_on": []}
  ]
}

OUTPUT — return ONLY valid JSON, no markdown, no explanation, no code blocks:
{
  "goal": "...",
  "success_criteria": "one sentence describing what must be true for the goal to be met",
  "steps": [
    {
      "step": 1,
      "tool": "tool_name",
      "description": "what this step does",
      "parameters": {},
      "critical": true,
      "depends_on": []
    }
  ]
}
"""


# ════════════════════════════════════════════════════════════════
# Pure helpers (unit-tested offline)
# ════════════════════════════════════════════════════════════════

def _extract_json(text: str) -> dict:
    """Robustly pull a JSON object out of an LLM response."""
    if not text:
        raise ValueError("empty response")
    cleaned = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        return json.loads(cleaned[start:end + 1])
    raise ValueError("no JSON object found in response")


def _find_refs(obj) -> set:
    """All {{stepN}} numbers referenced anywhere in a parameter tree."""
    found = set()
    if isinstance(obj, str):
        found.update(int(m) for m in _REF_RE.findall(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            found.update(_find_refs(v))
    elif isinstance(obj, list):
        for v in obj:
            found.update(_find_refs(v))
    return found


def _strip_invalid_refs(obj, current_step: int):
    """Remove references to non-earlier steps (self/forward refs)."""
    def fix(s: str) -> str:
        def repl(m):
            n = int(m.group(1))
            return m.group(0) if 1 <= n < current_step else ""
        return _REF_RE.sub(repl, s)

    if isinstance(obj, str):
        return fix(obj)
    if isinstance(obj, dict):
        return {k: _strip_invalid_refs(v, current_step) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_invalid_refs(v, current_step) for v in obj]
    return obj


def _normalize_plan(plan: dict, goal: str) -> dict:
    """Validate / repair a raw plan. Raises ValueError if unusable."""
    if not isinstance(plan, dict):
        raise ValueError("plan is not an object")
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("plan has no steps")

    normalized = []
    for raw in steps[:MAX_STEPS]:
        if not isinstance(raw, dict):
            continue
        tool = str(raw.get("tool") or "").strip()
        desc = str(raw.get("description") or "").strip()
        if not tool:
            continue
        if tool == "generated_code":
            tool = "web_search"
            raw = {**raw, "parameters": {"query": (desc or goal)[:200]}}

        num = len(normalized) + 1
        params = raw.get("parameters")
        if not isinstance(params, dict):
            params = {}
        params = _strip_invalid_refs(params, num)

        deps = raw.get("depends_on") or []
        if not isinstance(deps, list):
            deps = []
        deps = {int(d) for d in deps if isinstance(d, (int, float)) and 1 <= int(d) < num}
        deps.update(n for n in _find_refs(params) if 1 <= n < num)

        normalized.append({
            "step":        num,
            "tool":        tool,
            "description": desc,
            "parameters":  params,
            "critical":    bool(raw.get("critical", True)),
            "depends_on":  sorted(deps),
        })

    if not normalized:
        raise ValueError("no usable steps after normalization")

    return {
        "goal":             str(plan.get("goal") or goal),
        "success_criteria": str(plan.get("success_criteria") or goal),
        "steps":            normalized,
    }


def _log_plan(plan: dict, label: str = "Plan") -> None:
    print(f"[Planner] ✅ {label}: {len(plan['steps'])} steps")
    for s in plan["steps"]:
        deps = f" (needs {s['depends_on']})" if s["depends_on"] else ""
        print(f"  Step {s['step']}: [{s['tool']}] {s['description']}{deps}")


# ════════════════════════════════════════════════════════════════
# Public API
# ════════════════════════════════════════════════════════════════

def create_plan(goal: str, context: str = "") -> dict:
    user_input = f"Goal: {goal}"
    if context:
        user_input += f"\n\nContext (long-term memory / prior experience):\n{context}"

    res = ask_ai(
        user_input, system=PLANNER_PROMPT,
        preferred="gemini", temperature=0.2, max_tokens=4096,
    )
    if not res["success"]:
        print(f"[Planner] ⚠️ Planning failed: {res['error']}")
        return _fallback_plan(goal)

    try:
        plan = _normalize_plan(_extract_json(res["text"]), goal)
        _log_plan(plan)
        return plan
    except Exception as e:
        print(f"[Planner] ⚠️ Plan parse failed: {e}")
        return _fallback_plan(goal)


def _fallback_plan(goal: str) -> dict:
    print("[Planner] 🔄 Fallback plan")
    return {
        "goal": goal,
        "success_criteria": goal,
        "steps": [
            {
                "step": 1,
                "tool": "web_search",
                "description": f"Search for: {goal}",
                "parameters": {"query": goal},
                "critical": True,
                "depends_on": [],
            }
        ],
    }


def replan(
    goal: str,
    completed_steps: list,
    failed_step: dict,
    error: str,
    feedback: str = "",
) -> dict:
    completed_summary = "\n".join(
        f"  - Step {s.get('step')} ({s.get('tool')}): DONE" for s in (completed_steps or [])
    )
    prompt = f"""Goal: {goal}

Already completed:
{completed_summary if completed_summary else '  (none)'}

Failed step: [{failed_step.get('tool')}] {failed_step.get('description')}
Error: {error}

Create a REVISED plan for the remaining work only. Do not repeat completed steps."""
    if feedback:
        prompt += f"\n\nAdditional feedback:\n{feedback}"

    res = ask_ai(
        prompt, system=PLANNER_PROMPT,
        preferred="gemini", temperature=0.3, max_tokens=4096,
    )
    if not res["success"]:
        print(f"[Planner] ⚠️ Replan failed: {res['error']}")
        return _fallback_plan(goal)

    try:
        plan = _normalize_plan(_extract_json(res["text"]), goal)
        _log_plan(plan, "Revised plan")
        return plan
    except Exception as e:
        print(f"[Planner] ⚠️ Replan parse failed: {e}")
        return _fallback_plan(goal)
