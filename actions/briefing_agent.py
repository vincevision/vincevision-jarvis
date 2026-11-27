"""
briefing_agent.py — VINCEVISION spoken daily briefing
──────────────────────────────────────────────────────
Ties the assistant together: a "good morning" style briefing composed from
the greeting/date, weather, unread email, system health, and a news headline.
Every section degrades gracefully — if one source fails, the rest still run.

Actions: morning / brief / briefing (default). Optional `sections` list and
`city` (default Nairobi).
"""

import sys
from datetime import datetime
from pathlib import Path


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


DEFAULT_CITY = "Nairobi"
ALL_SECTIONS = ("greeting", "weather", "email", "system", "news")


# ── section providers (each returns a string; failures → "") ────

def greeting_section() -> str:
    now = datetime.now()
    h = now.hour
    part = "morning" if h < 12 else "afternoon" if h < 17 else "evening"
    return (f"Good {part}, sir. It's {now.strftime('%A, %B %d, %Y — %I:%M %p')}.")


def weather_section(city: str = DEFAULT_CITY) -> str:
    try:
        from actions.weather_report import weather_action
        out = weather_action(parameters={"city": city}, player=None)
        return f"Weather in {city}: {out}" if out else ""
    except Exception as e:
        print(f"[Briefing] weather skipped: {e}")
        return ""


def email_section() -> str:
    try:
        from actions.email_agent import email_agent
        out = email_agent(parameters={"action": "unread"}, player=None)
        return f"Email: {out}" if out else ""
    except Exception as e:
        print(f"[Briefing] email skipped: {e}")
        return ""


def system_section() -> str:
    try:
        from actions.system_agent import gather_overview
        d = gather_overview()
        return (f"System: CPU {d['cpu_percent']:.0f}%, RAM {d['memory']['percent']:.0f}%, "
                f"disk {d['disk']['percent']:.0f}% used.")
    except Exception as e:
        print(f"[Briefing] system skipped: {e}")
        return ""


def news_section(topic: str = "top world news today") -> str:
    try:
        from actions.web_search import web_search
        out = web_search(parameters={"query": topic}, player=None)
        if not out:
            return ""
        snippet = str(out).strip().replace("\n", " ")
        return f"News: {snippet[:300]}"
    except Exception as e:
        print(f"[Briefing] news skipped: {e}")
        return ""


_PROVIDERS = {
    "greeting": lambda params: greeting_section(),
    "weather":  lambda params: weather_section(params.get("city", DEFAULT_CITY)),
    "email":    lambda params: email_section(),
    "system":   lambda params: system_section(),
    "news":     lambda params: news_section(params.get("topic", "top world news today")),
}


# ── composition (pure given providers; unit-tested) ─────────────

def build_briefing(sections=None, params=None, providers=None) -> str:
    params = params or {}
    providers = providers or _PROVIDERS
    sections = sections or ALL_SECTIONS
    parts = []
    for name in sections:
        fn = providers.get(name)
        if not fn:
            continue
        try:
            text = fn(params)
        except Exception as e:
            print(f"[Briefing] section '{name}' failed: {e}")
            text = ""
        if text:
            parts.append(text.strip())
    if not parts:
        return "I couldn't assemble a briefing right now, sir."
    return "\n\n".join(parts)


def briefing_agent(parameters: dict, player=None, speak=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "briefing")).lower().strip()
    if action not in ("morning", "brief", "briefing", "full", "daily"):
        return "Say 'brief me' or 'good morning' for your daily briefing, sir."

    sections = params.get("sections")
    if isinstance(sections, str):
        sections = [s.strip() for s in sections.split(",") if s.strip()]
    if not sections:
        sections = list(ALL_SECTIONS)

    text = build_briefing(sections, params)
    if player:
        try:
            player.write_log("[Briefing] delivering daily briefing")
        except Exception:
            pass
    if speak:
        # Speak a concise version (greeting + first line of each section).
        concise = " ".join(p.split("\n")[0] for p in text.split("\n\n"))
        try:
            speak(concise[:600])
        except Exception:
            pass
    return text
