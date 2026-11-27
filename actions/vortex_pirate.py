import webbrowser
import subprocess
import time
import os
import platform
import requests
import re
from pathlib import Path
from datetime import datetime

OS      = platform.system()
LOG_DIR = Path.home() / "JARVIS_logs" / "vortex_pirate"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

def _log(player, msg: str):
    ts   = datetime.now().strftime("%H:%M:%S")
    line = f"[VORTEX] [{ts}] {msg}"
    print(line)
    if player:
        try:
            player.write_log(line[:300])
        except Exception:
            pass

def _speak(speak_fn, msg: str):
    if speak_fn:
        try:
            speak_fn(msg)
        except Exception:
            pass

# ─────────────────────────────────────────────────────────────────────────────
# BROWSER OPENER — Fixes Linux root sandbox error
# ─────────────────────────────────────────────────────────────────────────────

def _open_url(url: str, browser: str = "brave") -> bool:
    """Open URL — handles Linux root sandbox error automatically."""
    try:
        if OS == "Linux":
            browser_bins = {
                "brave":    ["brave-browser", "brave", "/usr/bin/brave-browser", "/usr/bin/brave"],
                "chrome":   ["google-chrome", "google-chrome-stable", "/usr/bin/google-chrome"],
                "firefox":  ["firefox", "/usr/bin/firefox"],
                "chromium": ["chromium", "chromium-browser"],
            }
            bins = browser_bins.get(browser.lower(), browser_bins["brave"])
            browser_bin = None
            for b in bins:
                result = subprocess.run(["which", b], capture_output=True, text=True)
                if result.returncode == 0:
                    browser_bin = result.stdout.strip()
                    break

            if browser_bin:
                subprocess.Popen(
                    [browser_bin, "--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", url],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
                )
                return True
        webbrowser.open(url)
        return True
    except Exception as e:
        print(f"[VORTEX] Browser error: {e}")
        try: webbrowser.open(url)
        except: pass
        return False

# ─────────────────────────────────────────────────────────────────────────────
# ENGINES: DORKING & TELEGRAM
# ─────────────────────────────────────────────────────────────────────────────

def _dork_search(query: str, category: str, browser: str, player=None) -> str:
    q = query.replace(" ", "+")
    dorks = [
        f'intitle:"index of" (mp4|mkv|avi|zip|rar) "{query}"',
        f'site:drive.google.com "{query}"',
        f'site:mega.nz "{query}"',
        f'site:t.me "{query}"',
        f'"{query}" filetype:mp4'
    ]
    opened = 0
    for dork in dorks[:2]:
        url = f"https://www.google.com/search?q={dork.replace(' ', '+')}"
        if _open_url(url, browser): opened += 1
        time.sleep(0.5)
    return f"Dorking complete. Opened {opened} search tabs."

def _telegram_search(query: str, category: str, browser: str, player=None) -> str:
    q_space = query.replace(" ", "%20")
    channels = {
        "movies": [f"https://t.me/s/FreeMoviesDump?q={q_space}", f"https://t.me/s/moviehubfree?q={q_space}"],
        "games": [f"https://t.me/s/crackedgameshub?q={q_space}", f"https://t.me/s/PCGamesHub?q={q_space}"],
        "adult": [f"https://t.me/s/Leak_World?q={q_space}", f"https://t.me/s/Homemade_Archive?q={q_space}", f"https://t.me/s/Adult_Content_Station?q={q_space}"],
        "courses": [f"https://t.me/s/FreeCourseHub?q={q_space}", f"https://t.me/s/UdemyFreeCourses?q={q_space}"]
    }
    target_channels = channels.get(category, [f"https://t.me/s/search?q={q_space}"])
    opened = 0
    for ch in target_channels[:2]:
        if _open_url(ch, browser): opened += 1
        time.sleep(0.5)
    return f"Telegram scan complete. Opened {opened} channels."

# ─────────────────────────────────────────────────────────────────────────────
# SOURCE BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _build_sources(category: str, query: str) -> list:
    q = query.strip().replace(" ", "+")
    q_dash = query.strip().replace(" ", "-").lower()

    if category in ("movies", "streaming", "film"):
        return [
            {"name": "VidSrc", "url": f"https://vidsrc.to/embed/movie/{q}"},
            {"name": "Soap2Day", "url": f"https://soap2day.to/search/{q}"},
            {"name": "LookMovie", "url": f"https://lookmovie.foundation/?s={q}"},
            {"name": "123Movies", "url": f"https://ww2.123moviesfree.net/search/?q={q}"},
            {"name": "Cinezone", "url": f"https://cinezone.to/filter?keyword={q}"}
        ]

    elif category in ("games", "game", "crack"):
        return [
            {"name": "FitGirl Repacks", "url": f"https://fitgirl-repacks.site/?s={q}"},
            {"name": "DODI Repacks", "url": f"https://dodi-repacks.site/?s={q}"},
            {"name": "Skidrow Reloaded", "url": f"https://www.skidrowreloaded.com/?s={q}"},
            {"name": "SteamUnlocked", "url": f"https://steamunlocked.net/search/?q={q}"}
        ]

    elif category in ("adult", "xxx", "porn", "18"):
        return [
            {"name": "EroMe (Homemade)", "url": f"https://www.erome.com/search?v=1&q={q}"},
            {"name": "Bunkr (File Dump)", "url": f"https://bunkr.is/search?q={q}"},
            {"name": "Coomer (Creator Leaks)", "url": f"https://coomer.su/posts?q={q}"},
            {"name": "Fapello (Premium Leaks)", "url": f"https://fapello.com/search/{q}/"},
            {"name": "Kemono (Artist Leaks)", "url": f"https://kemono.su/posts?q={q}"},
            {"name": "Thothub (Aggregator)", "url": f"https://thothub.to/?s={q}"},
            {"name": "Simpcity (Forums)", "url": f"https://simpcity.su/search/1/?q={q}"},
            {"name": "SpankBang (Homemade)", "url": f"https://spankbang.com/s/{q}+homemade/"},
            {"name": "xHamster (Amateur)", "url": f"https://xhamster.com/search/{q}?categories=homemade"},
            {"name": "PornHub (Natural)", "url": f"https://www.pornhub.com/video/search?search={q}&category=homemade"},
            {"name": "ThisVid (Raw)", "url": f"https://thisvid.com/search/?q={q}"},
            {"name": "VoyeurHit", "url": f"https://www.voyeurhit.com/search/{q}/"},
            {"name": "DaftSex (Leaks)", "url": f"https://daftsex.com/search/{q}"},
            {"name": "HQPorner", "url": f"https://hqporner.com/search?q={q}"},
            {"name": "SocialMedia Girls", "url": f"https://socialmediagirls.com/search/1/?q={q}"},
            {"name": "xVideos", "url": f"https://www.xvideos.com/?k={q}+homemade"},
            {"name": "XnXX", "url": f"https://www.xnxx.com/search/{q}+amateur"},
            {"name": "Beeg", "url": f"https://beeg.com/search?q={q}"},
            {"name": "PornTrex", "url": f"https://www.porntrex.com/search/{q}/"},
            {"name": "Motherless", "url": f"https://motherless.com/term/{q}"},
            {"name": "Thumbzilla", "url": f"https://www.thumbzilla.com/video/search?q={q}"},
            {"name": "Cumlouder", "url": f"https://www.cumlouder.com/search/{q}/"},
            {"name": "TNAFlix", "url": f"https://www.tnaflix.com/search-video?q={q}"},
            {"name": "Vjav", "url": f"https://vjav.com/search?q={q}"},
            {"name": "DrTuber", "url": f"https://www.drtuber.com/videos/search?q={q}"},
            {"name": "4Tube", "url": f"https://www.4tube.com/search/videos/{q}"},
            {"name": "GotPorn", "url": f"https://www.gotporn.com/videos/search?q={q}"},
            {"name": "WildSkirts", "url": f"https://wildskirts.com/search/{q}/"},
            {"name": "PornerBros", "url": f"https://pornerbros.com/search/{q}/"},
            {"name": "SimplyAnal", "url": f"https://www.simplyanal.com/search?q={q}"}
        ]

    elif category in ("courses", "learning"):
        return [
            {"name": "FreeCourseSite", "url": f"https://freecoursesite.com/?s={q}"},
            {"name": "TutFlix", "url": f"https://tutflix.org/search?q={q}"},
            {"name": "DownloadFreeCourse", "url": f"https://downloadfreecourse.com/?s={q}"}
        ]

    return [{"name": "1337x", "url": f"https://1337x.to/search/{q}/1/"}]

# ─────────────────────────────────────────────────────────────────────────────
# MAIN FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def vortex_pirate(parameters: dict, player=None, speak=None) -> str:
    category = parameters.get("category", "all").lower()
    query = parameters.get("query", "").strip()
    action = parameters.get("action", "open")
    browser = parameters.get("browser", "brave")
    count = int(parameters.get("open_count", 3))

    if not query: return "Sir, specify what you are looking for."
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if action == "dork": return _dork_search(query, category, browser, player)
    if action == "telegram": return _telegram_search(query, category, browser, player)

    if action == "combo":
        _speak(speak, f"Running full combo search for {query}, sir.")
        _dork_search(query, category, browser, player)
        _telegram_search(query, category, browser, player)
        action = "open" # Continue to open regular links

    sources = _build_sources(category, query)
    to_open = sources[:count]
    
    if speak: speak(f"Opening top {len(to_open)} sources for {query}, sir.")

    results = []
    for s in to_open:
        if _open_url(s["url"], browser): results.append(f"✅ {s['name']}")
    
    return f"Vortex Action: {action}\n" + "\n".join(results)

DECLARATION = {
    "name": "vortex_pirate",
    "description": "Extreme pirate engine. Movies, Games, Software, Leaked Courses, and 30+ Adult Homemade/Leaked sources. Actions: open, dork, telegram, combo.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "category": {"type": "STRING", "description": "movies | games | software | adult | courses | all"},
            "query": {"type": "STRING", "description": "Title or name"},
            "action": {"type": "STRING", "description": "open | dork | telegram | combo"},
            "open_count": {"type": "INTEGER", "description": "Number of tabs to open"}
        },
        "required": ["query"]
    }
}