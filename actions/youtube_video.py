# youtube_video.py
"""
YouTube agent tool for JARVIS.
All browser actions go through browser_control so they use the
existing Playwright session (no raw subprocess, no segfault risk).
"""
from __future__ import annotations

import json
import os
import re
import sys
import subprocess
import shutil
import platform
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

_OS = platform.system()

def _is_linux()   -> bool: return _OS == "Linux"
def _is_mac()     -> bool: return _OS == "Darwin"
def _is_windows() -> bool: return _OS == "Windows"


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_YT_VIDEO_FILTER = "EgIQAQ%3D%3D"

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    _TRANSCRIPT_OK = True
except ImportError:
    _TRANSCRIPT_OK = False


# ══════════════════════════════════════════════════════════════════════════
#  BROWSER CONTROL INTEGRATION
#  All navigation goes through browser_control so we reuse the existing
#  Playwright/Brave session — no raw subprocesses, no permission issues.
# ══════════════════════════════════════════════════════════════════════════

def _bc(action: str, player=None, **kwargs) -> str:
    """Thin wrapper around browser_control."""
    try:
        from actions.browser_control import browser_control
        params = {"action": action, "browser": "brave", **kwargs}
        return browser_control(parameters=params, player=player)
    except Exception as e:
        print(f"[YouTube] ⚠️  browser_control failed ({action}): {e}")
        return f"browser_control error: {e}"


def _open_url(url: str, player=None) -> None:
    """Navigate to a URL using the shared Playwright session."""
    result = _bc("go_to", player=player, url=url)
    print(f"[YouTube] 🌐 {result}")


# ══════════════════════════════════════════════════════════════════════════
#  SCRAPING HELPERS  (HTTP only — no browser needed)
# ══════════════════════════════════════════════════════════════════════════

def _scrape_first_video_url(query: str) -> str | None:
    if not _REQUESTS_OK:
        return None
    search_url = (
        f"https://www.youtube.com/results"
        f"?search_query={quote_plus(query)}&sp={_YT_VIDEO_FILTER}"
    )
    try:
        r    = requests.get(search_url, headers=HEADERS, timeout=10)
        html = r.text
        seen: set[str] = set()
        for vid in re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html):
            if vid in seen:
                continue
            seen.add(vid)
            if f"/shorts/{vid}" in html:
                continue
            return f"https://www.youtube.com/watch?v={vid}"
    except Exception as e:
        print(f"[YouTube] ⚠️  scrape_first_video_url: {e}")
    return None


def _extract_video_id(url: str) -> str | None:
    m = re.search(
        r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})", url
    )
    return m.group(1) if m else None


def _is_valid_youtube_url(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url or ""))


def _scrape_video_info(video_id: str) -> dict:
    if not _REQUESTS_OK:
        return {}
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=12)
        html = r.text
        info: dict = {}
        for key, pattern in [
            ("title",    r'"title":\{"runs":\[\{"text":"([^"]+)"'),
            ("channel",  r'"ownerChannelName":"([^"]+)"'),
            ("views",    r'"viewCount":"(\d+)"'),
            ("duration", r'"lengthSeconds":"(\d+)"'),
            ("likes",    r'"label":"([0-9,]+ likes)"'),
        ]:
            m = re.search(pattern, html)
            if m:
                raw = m.group(1)
                if key == "views":    info[key] = f"{int(raw):,}"
                elif key == "duration":
                    s = int(raw); info[key] = f"{s // 60}:{s % 60:02d}"
                else:                 info[key] = raw
        return info
    except Exception as e:
        print(f"[YouTube] ⚠️  scrape_video_info: {e}")
        return {}


def _scrape_trending(region: str = "US", max_results: int = 8) -> list[dict]:
    if not _REQUESTS_OK:
        return []
    url = f"https://www.youtube.com/feed/trending?gl={region.upper()}"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=12)
        html = r.text
        titles   = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"\}\]', html)
        channels = re.findall(r'"ownerText":\{"runs":\[\{"text":"([^"]+)"', html)
        results: list[dict] = []; seen: set[str] = set()
        for i, title in enumerate(titles):
            if title in seen or len(title) < 5:
                continue
            seen.add(title)
            results.append({
                "rank":    len(results) + 1,
                "title":   title,
                "channel": channels[i] if i < len(channels) else "Unknown",
            })
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        print(f"[YouTube] ⚠️  scrape_trending: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════
#  TRANSCRIPT + AI SUMMARY
# ══════════════════════════════════════════════════════════════════════════

def _get_transcript(video_id: str) -> str | None:
    if not _TRANSCRIPT_OK:
        return None
    try:
        tlist      = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = None
        langs      = ["en","tr","de","fr","es","it","pt","ru","ja","ko","ar","zh"]
        try:
            transcript = tlist.find_manually_created_transcript(langs)
        except Exception:
            pass
        if transcript is None:
            try:
                transcript = tlist.find_generated_transcript(langs)
            except Exception:
                for t in tlist:
                    transcript = t; break
        if transcript is None:
            return None
        fetched = transcript.fetch()
        return " ".join(entry["text"] for entry in fetched)
    except Exception as e:
        print(f"[YouTube] ⚠️  transcript fetch: {e}")
        return None


def _summarize_with_ai(transcript: str, video_url: str) -> str:
    from core.ai_router import ask_ai
    truncated = transcript[:80_000] + ("..." if len(transcript) > 80_000 else "")
    system = (
        "You are JARVIS, an AI assistant. "
        "Summarize YouTube video transcripts clearly and concisely. "
        "Structure: 1-sentence overview, then 3-5 key points. "
        "Be direct. Address the user as 'sir'. "
        "Match the language of the transcript."
    )
    result = ask_ai(
        prompt=f"Please summarize this YouTube video transcript:\n\n{truncated}",
        system=system,
        preferred="groq",
    )
    if result["success"]:
        return result["text"].strip()
    raise Exception(result["error"])


def _save_summary(content: str, video_url: str) -> str:
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    desktop  = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    filepath = desktop / f"youtube_summary_{ts}.txt"
    header   = (
        f"JARVIS — YouTube Summary\n{'─'*50}\n"
        f"URL  : {video_url}\nDate : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"{'─'*50}\n\n"
    )
    filepath.write_text(header + content, encoding="utf-8")
    try:
        opener = (["notepad.exe"] if _is_windows()
                  else ["open", "-t"] if _is_mac()
                  else ["xdg-open"])
        subprocess.Popen(opener + [str(filepath)])
    except Exception as e:
        print(f"[YouTube] ⚠️  open editor: {e}")
    return str(filepath)


# ══════════════════════════════════════════════════════════════════════════
#  ACTION HANDLERS
# ══════════════════════════════════════════════════════════════════════════

def _handle_play(params: dict, player) -> str:
    query = params.get("query", "").strip()
    if not query:
        return "Please tell me what you'd like to watch, sir."

    if player:
        player.write_log(f"[YouTube] 🔍 Searching: {query}")
    print(f"[YouTube] 🔍 Scraping first non-Shorts video for: {query}")

    video_url = _scrape_first_video_url(query)

    if video_url:
        print(f"[YouTube] ▶️  Opening: {video_url}")
        _open_url(video_url, player=player)
        return f"Playing '{query}' on YouTube, sir."

    # Fallback: open filtered search page via browser_control
    print("[YouTube] ⚠️  Scrape failed — opening search results page")
    fallback = (
        f"https://www.youtube.com/results"
        f"?search_query={quote_plus(query)}&sp={_YT_VIDEO_FILTER}"
    )
    _open_url(fallback, player=player)
    return f"Opened YouTube search for '{query}', sir. Please select a video."


def _handle_search(params: dict, player) -> str:
    """Open YouTube search results for a query."""
    query = params.get("query", "").strip()
    if not query:
        return "Please provide a search query, sir."
    url = (
        f"https://www.youtube.com/results"
        f"?search_query={quote_plus(query)}&sp={_YT_VIDEO_FILTER}"
    )
    if player:
        player.write_log(f"[YouTube] 🔍 Search: {query}")
    _open_url(url, player=player)
    return f"Showing YouTube search results for '{query}', sir."


def _handle_open_url(params: dict, player) -> str:
    """Open a specific YouTube URL directly."""
    url = params.get("url", "").strip()
    if not url or not _is_valid_youtube_url(url):
        return "Please provide a valid YouTube URL, sir."
    if player:
        player.write_log(f"[YouTube] 🔗 Opening: {url}")
    _open_url(url, player=player)
    return f"Opened: {url}"


def _handle_summarize(params: dict, player, speak) -> str:
    if not _TRANSCRIPT_OK:
        return (
            "youtube-transcript-api is not installed, sir. "
            "Run: pip install youtube-transcript-api"
        )

    # URL comes from params (JARVIS passes it) or from the current browser page
    url = params.get("url", "").strip()

    if not url:
        # Try to get current page URL from browser_control
        try:
            from actions.browser_control import browser_control
            url = browser_control(
                parameters={"action": "get_url", "browser": "brave"},
                player=player,
            ).strip()
            if not _is_valid_youtube_url(url):
                url = ""
        except Exception:
            url = ""

    if not url or not _is_valid_youtube_url(url):
        return (
            "Please open a YouTube video first, or pass the URL as a parameter, sir."
        )

    video_id = _extract_video_id(url)
    if not video_id:
        return "Could not extract video ID from that URL, sir."

    if player:
        player.write_log(f"[YouTube] 📝 Summarizing: {url}")
    if speak:
        speak("Fetching the transcript now, sir. One moment.")

    transcript = _get_transcript(video_id)
    if not transcript:
        return "I couldn't retrieve a transcript for that video, sir."

    if speak:
        speak("Transcript retrieved. Generating summary now.")

    try:
        summary = _summarize_with_ai(transcript, url)
    except Exception as e:
        return f"Summary generation failed, sir: {e}"

    if speak:
        speak(summary)

    if params.get("save", False):
        saved = _save_summary(summary, url)
        return f"Summary saved to Desktop: {saved}\n\n{summary}"

    return summary


def _handle_get_info(params: dict, player, speak) -> str:
    url = params.get("url", "").strip()

    if not url:
        # Try current browser page
        try:
            from actions.browser_control import browser_control
            url = browser_control(
                parameters={"action": "get_url", "browser": "brave"},
                player=player,
            ).strip()
            if not _is_valid_youtube_url(url):
                url = ""
        except Exception:
            url = ""

    if not url or not _is_valid_youtube_url(url):
        return "Please open a YouTube video first, or provide a URL, sir."

    video_id = _extract_video_id(url)
    if not video_id:
        return "Could not extract video ID, sir."

    if player:
        player.write_log(f"[YouTube] ℹ️  Info: {url}")

    info = _scrape_video_info(video_id)
    if not info:
        return "Could not retrieve video information, sir."

    lines  = [f"{k.capitalize()}: {info[k]}"
              for k in ("title","channel","views","duration","likes") if k in info]
    result = "\n".join(lines)

    if speak:
        speak(f"Here's the video info, sir. {result.replace(chr(10), '. ')}")

    return result


def _handle_trending(params: dict, player, speak) -> str:
    region = params.get("region", "US").upper()
    if player:
        player.write_log(f"[YouTube] 📈 Trending: {region}")

    trending = _scrape_trending(region=region, max_results=8)
    if not trending:
        return f"Could not fetch trending videos for region {region}, sir."

    lines  = [f"Top trending in {region}:"]
    lines += [f"{v['rank']}. {v['title']} — {v['channel']}" for v in trending]
    result = "\n".join(lines)

    if speak:
        top3   = trending[:3]
        spoken = "Here are the top trending videos, sir. " + ". ".join(
            f"Number {v['rank']}: {v['title']} by {v['channel']}" for v in top3
        )
        speak(spoken)

    return result


def _handle_pause(params: dict, player) -> str:
    """Press K (YouTube keyboard shortcut for play/pause)."""
    _bc("press", player=player, key="k")
    return "Toggled playback, sir."


def _handle_skip(params: dict, player) -> str:
    """Skip forward/backward using YouTube keyboard shortcuts."""
    direction = params.get("direction", "forward").lower()
    seconds   = int(params.get("seconds", 10))
    # YouTube: L = +10s, J = -10s, arrow keys = ±5s
    if direction == "forward":
        key = "l" if seconds >= 10 else "ArrowRight"
    else:
        key = "j" if seconds >= 10 else "ArrowLeft"
    _bc("press", player=player, key=key)
    return f"Skipped {direction} {seconds}s, sir."


def _handle_fullscreen(params: dict, player) -> str:
    """Toggle fullscreen with F key."""
    _bc("press", player=player, key="f")
    return "Toggled fullscreen, sir."


def _handle_mute_video(params: dict, player) -> str:
    """Mute/unmute video with M key."""
    _bc("press", player=player, key="m")
    return "Toggled video mute, sir."


# ══════════════════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════

_ACTION_MAP = {
    "play":       (_handle_play,       False),  # (handler, needs_speak)
    "search":     (_handle_search,     False),
    "open_url":   (_handle_open_url,   False),
    "summarize":  (_handle_summarize,  True),
    "get_info":   (_handle_get_info,   True),
    "trending":   (_handle_trending,   True),
    "pause":      (_handle_pause,      False),
    "skip":       (_handle_skip,       False),
    "fullscreen": (_handle_fullscreen, False),
    "mute_video": (_handle_mute_video, False),
}


def youtube_video(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    params = parameters or {}
    action = params.get("action", "play").lower().strip()

    if player:
        player.write_log(f"[YouTube] Action: {action}")
    print(f"[YouTube] ▶️  Action: {action}  Params: {params}")

    entry = _ACTION_MAP.get(action)
    if entry is None:
        return (
            f"Unknown YouTube action: '{action}'. "
            f"Available: {', '.join(_ACTION_MAP)}."
        )

    handler, needs_speak = entry
    try:
        if needs_speak:
            return handler(params, player, speak) or "Done."
        return handler(params, player) or "Done."
    except Exception as e:
        import traceback; traceback.print_exc()
        return f"YouTube {action} failed, sir: {e}"