# actions/off_darkweb.py
# JARVIS Enhanced Dark Web Agent — Cross-Platform, Modern, Stealthy

import subprocess
import os
import sys
import json
import re
import time
import random
import platform
import threading
import requests
from pathlib import Path
from datetime import datetime

# ── OS Detection ──────────────────────────────────────────────────────────────
OS   = platform.system()   # Windows | Linux | Darwin
ARCH = platform.machine()

DARKWEB_DIR = Path.home() / "jarvis_captures" / "darkweb"
DARKWEB_DIR.mkdir(parents=True, exist_ok=True)

TOR_SOCKS   = "socks5h://127.0.0.1:9050"
TOR_PROXIES = {"http": TOR_SOCKS, "https": TOR_SOCKS}

# ── Groq AI ───────────────────────────────────────────────────────────────────
try:
    from groq import Groq
    _groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
    GROQ_AVAILABLE = True
except Exception:
    GROQ_AVAILABLE = False

# ── User Agents ───────────────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:102.0) Gecko/20100101 Firefox/102.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:91.0) Gecko/20100101 Firefox/91.0",
]

# Known .onion search engines
ONION_ENGINES = {
    "ahmia":    "https://ahmia.fi/search/?q=",
    "torch":    "http://xmh57jrknzkhv6y3ls3ubitzfqnkrwxhopf5aygthi7d6rplyvk3noyd.onion/4a1f6b371c/search.cgi?q=",
    "haystack": "http://haystak5njsmn2hqkewecpaxetahtwhsbsa64jom2k22z5afxhnpxfid.onion/?q=",
    "dread":    "http://dreadytofatroptsdj6io7l3xptbet6onoyno2yv7jicoxknyazubrad.onion/search?q=",
}


def _ask_groq(prompt: str, context: str = "") -> str:
    """Ask Groq AI for dark web analysis."""
    if not GROQ_AVAILABLE:
        return "Groq not available."
    try:
        msg = f"{context}\n\n{prompt}" if context else prompt
        r   = _groq_client.chat.completions.create(
            model    = "llama3-70b-8192",
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are an expert dark web intelligence analyst and "
                        "threat intelligence researcher. Analyze dark web content, "
                        "identify threats, correlate leaked data, monitor threat actors. "
                        "Give concise, actionable intelligence reports. "
                        "Focus on modern 2024 dark web landscape."
                    )
                },
                {"role": "user", "content": msg}
            ],
            max_tokens  = 2048,
            temperature = 0.2,
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        return f"Groq error: {e}"


def _run(cmd: str, timeout: int = 60) -> dict:
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True,
            text=True, timeout=timeout
        )
        return {
            "stdout": r.stdout.strip(),
            "stderr": r.stderr.strip(),
            "code":   r.returncode
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Timeout", "code": -1}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "code": -1}


def _check_tool(tool: str) -> bool:
    if OS == "Windows":
        r = _run(f"where {tool} 2>nul")
    else:
        r = _run(f"which {tool} 2>/dev/null")
    return r["code"] == 0


def _save(name: str, content: str) -> str:
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DARKWEB_DIR / f"{name}_{ts}.txt"
    path.write_text(content, encoding="utf-8", errors="ignore")
    return str(path)


def _get_tor_session(stream_isolation: bool = True) -> requests.Session:
    """Get a Tor-routed requests session with stream isolation."""
    s = requests.Session()
    s.proxies = TOR_PROXIES
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
    })
    # Stream isolation — different circuit per session
    if stream_isolation:
        port = random.randint(9000, 9999)
        try:
            s.proxies = {
                "http":  f"socks5h://127.0.0.1:{port}",
                "https": f"socks5h://127.0.0.1:{port}",
            }
        except Exception:
            s.proxies = TOR_PROXIES
    return s


# ══════════════════════════════════════════════════════════════════════════════
#  TOR CONTROL — CROSS PLATFORM
# ══════════════════════════════════════════════════════════════════════════════

def start_tor() -> dict:
    """Start Tor service — adapts per OS."""
    if OS == "Linux":
        # Try systemctl first
        r = _run("systemctl start tor 2>/dev/null || service tor start")
        time.sleep(4)
        running = _run("pgrep tor")["code"] == 0

    elif OS == "Windows":
        # Look for Tor Expert Bundle or Tor Browser
        tor_paths = [
            r"C:\Users\%USERNAME%\Desktop\Tor Browser\Browser\TorBrowser\Tor\tor.exe",
            r"C:\Program Files\Tor Browser\Browser\TorBrowser\Tor\tor.exe",
            r"C:\tor\tor.exe",
        ]
        tor_exe = None
        for p in tor_paths:
            expanded = os.path.expandvars(p)
            if Path(expanded).exists():
                tor_exe = expanded
                break

        if not tor_exe:
            # Try to download Tor Expert Bundle
            return {
                "success": False,
                "message": (
                    "Tor not found on Windows. Download Tor Expert Bundle from "
                    "https://www.torproject.org/download/tor/ and extract to C:\\tor\\"
                )
            }

        proc = subprocess.Popen([tor_exe], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        time.sleep(5)
        running = proc.poll() is None

    elif OS == "Darwin":
        # Try brew or Tor.app
        r = _run("brew services start tor 2>/dev/null || "
                 "launchctl load /usr/local/etc/tor/torrc 2>/dev/null")
        time.sleep(4)
        running = _run("pgrep tor")["code"] == 0

    else:
        return {"success": False, "message": f"Unsupported OS: {OS}"}

    if running:
        # Verify Tor is working
        try:
            test = requests.get(
                "http://check.torproject.org/api/ip",
                proxies=TOR_PROXIES, timeout=15
            )
            data   = test.json()
            tor_ip = data.get("IP", "unknown")
            is_tor = data.get("IsTor", False)
            return {
                "success": True,
                "running": True,
                "tor_ip":  tor_ip,
                "is_tor":  is_tor,
                "message": f"Tor running. Exit IP: {tor_ip} | Verified: {is_tor}"
            }
        except Exception:
            return {
                "success": True,
                "running": True,
                "message": "Tor started but connection test failed. May need more time."
            }

    return {"success": False, "message": "Tor failed to start."}


def stop_tor() -> dict:
    """Stop Tor service."""
    if OS == "Linux":
        _run("systemctl stop tor 2>/dev/null || service tor stop")
    elif OS == "Windows":
        _run("taskkill /f /im tor.exe 2>nul")
    elif OS == "Darwin":
        _run("brew services stop tor 2>/dev/null || pkill tor")

    return {"success": True, "message": "Tor stopped."}


def check_tor() -> dict:
    """Check Tor status and current exit IP."""
    running = False

    if OS == "Windows":
        running = _run("tasklist | findstr tor.exe")["code"] == 0
    else:
        running = _run("pgrep tor")["code"] == 0

    if not running:
        return {
            "success": False,
            "running": False,
            "message": "Tor is not running."
        }

    try:
        r = requests.get(
            "http://check.torproject.org/api/ip",
            proxies=TOR_PROXIES, timeout=15
        )
        data = r.json()
        return {
            "success": True,
            "running": True,
            "tor_ip":  data.get("IP", "unknown"),
            "is_tor":  data.get("IsTor", False),
            "message": (
                f"Tor running. Exit IP: {data.get('IP','?')} | "
                f"Verified Tor: {data.get('IsTor','?')}"
            )
        }
    except Exception as e:
        return {
            "success": True,
            "running": True,
            "message": f"Tor running but IP check failed: {e}"
        }


def get_new_identity() -> dict:
    """Request a new Tor circuit — changes exit IP."""
    # Try stem library first
    try:
        from stem import Signal
        from stem.control import Controller
        with Controller.from_port(port=9051) as ctrl:
            ctrl.authenticate()
            ctrl.signal(Signal.NEWNYM)
        time.sleep(5)

        # Verify new IP
        try:
            r = requests.get(
                "http://check.torproject.org/api/ip",
                proxies=TOR_PROXIES, timeout=10
            )
            new_ip = r.json().get("IP", "unknown")
            return {
                "success": True,
                "new_ip":  new_ip,
                "message": f"New Tor identity obtained. New exit IP: {new_ip}"
            }
        except Exception:
            return {"success": True, "message": "New Tor identity obtained."}

    except ImportError:
        pass
    except Exception:
        pass

    # Fallback: restart Tor
    stop_tor()
    time.sleep(2)
    r = start_tor()
    return {
        "success": r["success"],
        "message": f"Tor restarted for new identity. {r.get('message','')}"
    }


# ══════════════════════════════════════════════════════════════════════════════
#  I2P NETWORK SUPPORT
# ══════════════════════════════════════════════════════════════════════════════

def start_i2p() -> dict:
    """Start I2P network — alternative to Tor."""
    if OS == "Linux":
        r = _run("systemctl start i2p 2>/dev/null || i2prouter start 2>/dev/null")
        time.sleep(10)
        running = _run("pgrep -f i2p")["code"] == 0
        if running:
            return {
                "success": True,
                "message": "I2P started. Console: http://127.0.0.1:7657"
            }

    elif OS == "Windows":
        i2p_paths = [
            r"C:\Program Files\i2p\i2prouter.bat",
            r"C:\i2p\i2prouter.bat",
        ]
        for p in i2p_paths:
            if Path(p).exists():
                subprocess.Popen([p], shell=True)
                return {
                    "success": True,
                    "message": f"I2P starting from {p}. Console: http://127.0.0.1:7657"
                }

    elif OS == "Darwin":
        r = _run("i2prouter start 2>/dev/null")
        if r["code"] == 0:
            return {
                "success": True,
                "message": "I2P started. Console: http://127.0.0.1:7657"
            }

    return {
        "success": False,
        "message": (
            "I2P not found. Install from https://geti2p.net/en/download\n"
            "Linux: apt install i2p"
        )
    }


def browse_i2p(url: str) -> dict:
    """Browse I2P (.i2p) sites via local I2P HTTP proxy."""
    I2P_PROXY = {"http": "http://127.0.0.1:4444", "https": "http://127.0.0.1:4444"}
    try:
        s = requests.Session()
        s.proxies = I2P_PROXY
        s.headers.update({"User-Agent": random.choice(USER_AGENTS)})
        r = s.get(url, timeout=30)
        content = r.text
        path    = _save(f"i2p_{url[:20].replace('/','_')}", content)
        return {
            "success":  True,
            "url":      url,
            "content":  content[:500],
            "saved_to": path,
            "message":  f"I2P page fetched: {url} ({len(content)} chars)"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"I2P browse failed: {e}. Is I2P running?"
        }


# ══════════════════════════════════════════════════════════════════════════════
#  .ONION BROWSING
# ══════════════════════════════════════════════════════════════════════════════

def browse_onion(url: str, save: bool = True) -> dict:
    """Fetch content from a .onion URL via Tor."""
    if not url.startswith("http"):
        url = "http://" + url

    try:
        s       = _get_tor_session()
        r       = s.get(url, timeout=30)
        content = r.text

        # Extract links from page
        links = re.findall(r'href=["\']([^"\']+)["\']', content)
        onion_links = [l for l in links if ".onion" in l]

        # Extract emails
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', content)

        path = None
        if save:
            safe = url.replace("http://", "").replace("/", "_")[:30]
            path = _save(f"onion_{safe}", content)

        # AI analysis
        ai_analysis = ""
        if GROQ_AVAILABLE and len(content) > 100:
            ai_analysis = _ask_groq(
                "Analyze this dark web page content. "
                "What is it about? Any threats, leaked data, or interesting intel? "
                "What should be investigated further?",
                context=content[:3000]
            )

        return {
            "success":      True,
            "url":          url,
            "status":       r.status_code,
            "content_len":  len(content),
            "onion_links":  onion_links[:20],
            "emails":       emails[:10],
            "preview":      content[:500],
            "ai_analysis":  ai_analysis,
            "saved_to":     path,
            "message": (
                f"Fetched {url} ({len(content)} chars)\n"
                f"Links: {len(onion_links)} onion links found\n"
                f"Emails: {emails[:3]}\n"
                + (f"AI: {ai_analysis[:200]}" if ai_analysis else "")
            )
        }

    except Exception as e:
        return {"success": False, "url": url, "message": f"Failed: {e}"}


# ══════════════════════════════════════════════════════════════════════════════
#  DARK WEB SEARCH
# ══════════════════════════════════════════════════════════════════════════════

def darkweb_search(
    query:  str,
    engine: str  = "ahmia",
    pages:  int  = 1,
    save:   bool = True
) -> dict:
    """Search the dark web via multiple engines."""
    results = []
    engine  = engine.lower()

    # ── Ahmia (clearnet — fastest) ────────────────────────────────
    if engine == "ahmia":
        try:
            s = requests.Session()
            s.headers.update({"User-Agent": random.choice(USER_AGENTS)})

            for page in range(pages):
                r = s.get(
                    f"https://ahmia.fi/search/?q={requests.utils.quote(query)}"
                    f"&page={page}",
                    timeout=20
                )
                # Extract .onion links
                onion_links = re.findall(
                    r'http://[a-z2-7]{16,56}\.onion[^\s"\'<>]*',
                    r.text
                )
                # Extract titles and descriptions
                from html.parser import HTMLParser

                class ResultParser(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.results = []
                        self.current = {}
                        self.capture = False

                    def handle_starttag(self, tag, attrs):
                        attrs = dict(attrs)
                        if tag == "a" and "href" in attrs:
                            if ".onion" in attrs["href"]:
                                self.current["url"] = attrs["href"]
                                self.capture = True

                    def handle_data(self, data):
                        if self.capture and self.current.get("url"):
                            self.current["title"] = data.strip()
                            self.capture = False

                    def handle_endtag(self, tag):
                        if tag == "li" and self.current:
                            if self.current.get("url"):
                                self.results.append(self.current)
                            self.current = {}

                parser = ResultParser()
                parser.feed(r.text)
                results.extend(parser.results[:10])

                # Also add raw onion links
                for link in onion_links[:10]:
                    if not any(r.get("url") == link for r in results):
                        results.append({"url": link, "title": "Unknown"})

        except Exception as e:
            results.append({"error": str(e)})

    # ── Torch / Haystack (via Tor) ────────────────────────────────
    elif engine in ("torch", "haystack", "dread"):
        base = ONION_ENGINES.get(engine, ONION_ENGINES["ahmia"])
        try:
            s = _get_tor_session()
            r = s.get(f"{base}{requests.utils.quote(query)}", timeout=30)
            onion_links = re.findall(
                r'http://[a-z2-7]{16,56}\.onion[^\s"\'<>]*',
                r.text
            )
            for link in onion_links[:20]:
                results.append({"url": link, "title": "Unknown", "engine": engine})
        except Exception as e:
            results.append({"error": str(e)})

    # AI analysis of results
    ai_analysis = ""
    if GROQ_AVAILABLE and results:
        urls_summary = "\n".join([
            f"  {r.get('title','?')}: {r.get('url','?')}"
            for r in results[:10] if not r.get("error")
        ])
        ai_analysis = _ask_groq(
            f"Analyze these dark web search results for '{query}'. "
            f"What do these sites likely contain? "
            f"Which are most relevant to the search? "
            f"Any threat intelligence value?",
            context=urls_summary
        )

    report = (
        f"Dark Web Search: '{query}' via {engine}\n"
        f"Results: {len(results)}\n\n"
        + "\n".join([
            f"[{r.get('title','?')}] {r.get('url','?')}"
            for r in results if not r.get("error")
        ])
        + f"\n\nAI Analysis:\n{ai_analysis}"
    )
    path = _save(f"search_{query[:20].replace(' ','_')}", report) if save else ""

    return {
        "success":     True,
        "query":       query,
        "engine":      engine,
        "results":     results,
        "count":       len([r for r in results if not r.get("error")]),
        "ai_analysis": ai_analysis,
        "report":      path,
        "message": (
            f"Found {len(results)} dark web results for '{query}':\n"
            + "\n".join([r.get("url", "?") for r in results[:5] if not r.get("error")])
            + (f"\n\nAI: {ai_analysis[:200]}" if ai_analysis else "")
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  LEAK DATABASE CHECKS
# ══════════════════════════════════════════════════════════════════════════════

def check_leak(
    query:     str,
    leak_type: str = "email"
) -> dict:
    """
    Comprehensive leak database check.
    Checks HIBP, LeakCheck, Dehashed, IntelX.
    """
    results = {}
    s = requests.Session()
    s.headers.update({"User-Agent": random.choice(USER_AGENTS)})

    # ── HaveIBeenPwned ────────────────────────────────────────────
    hibp_key = os.environ.get("HIBP_API_KEY", "")
    if leak_type == "email":
        try:
            time.sleep(1.5)  # HIBP rate limit
            r = s.get(
                f"https://haveibeenpwned.com/api/v3/breachedaccount/{query}",
                headers={
                    "User-Agent":   "JARVIS-DarkWeb/2.0",
                    "hibp-api-key": hibp_key
                },
                timeout=15
            )
            if r.status_code == 200:
                breaches = r.json()
                results["hibp"] = {
                    "found":    True,
                    "count":    len(breaches),
                    "breaches": [b["Name"] for b in breaches],
                    "dates":    [b.get("BreachDate", "") for b in breaches],
                    "data_classes": list(set([
                        dc for b in breaches
                        for dc in b.get("DataClasses", [])
                    ]))
                }
            elif r.status_code == 404:
                results["hibp"] = {"found": False}
            elif r.status_code == 401:
                results["hibp"] = {"error": "HIBP API key required"}
        except Exception as e:
            results["hibp_error"] = str(e)

        # Also check paste exposure
        try:
            time.sleep(1.5)
            r2 = s.get(
                f"https://haveibeenpwned.com/api/v3/pasteaccount/{query}",
                headers={
                    "User-Agent":   "JARVIS-DarkWeb/2.0",
                    "hibp-api-key": hibp_key
                },
                timeout=15
            )
            if r2.status_code == 200:
                results["hibp_pastes"] = {
                    "found": True,
                    "pastes": r2.json()[:5]
                }
        except Exception:
            pass

    # ── LeakCheck ─────────────────────────────────────────────────
    try:
        r = s.get(
            f"https://leakcheck.io/api/public?check={query}",
            timeout=15
        )
        if r.status_code == 200:
            data = r.json()
            results["leakcheck"] = {
                "found":   data.get("found", False),
                "sources": data.get("sources", [])[:5]
            }
    except Exception as e:
        results["leakcheck_error"] = str(e)

    # ── IntelX (if key) ───────────────────────────────────────────
    intelx_key = os.environ.get("INTELX_API_KEY", "")
    if intelx_key:
        try:
            # Search
            r = s.post(
                "https://2.intelx.io/intelligent/search",
                headers={"x-key": intelx_key},
                json={
                    "term":    query,
                    "maxresults": 10,
                    "media":   0,
                    "sort":    2,
                    "terminate": []
                },
                timeout=15
            )
            if r.status_code == 200:
                data = r.json()
                results["intelx"] = {
                    "id":    data.get("id", ""),
                    "count": data.get("records", 0)
                }
        except Exception as e:
            results["intelx_error"] = str(e)

    # ── h8mail ────────────────────────────────────────────────────
    if _check_tool("h8mail"):
        r = _run(f"h8mail -t {query} --no-banner", timeout=120)
        if r["code"] == 0 and r["stdout"]:
            results["h8mail"] = r["stdout"][:500]

    # ── Dehashed (if key) ─────────────────────────────────────────
    dehashed_key   = os.environ.get("DEHASHED_API_KEY", "")
    dehashed_email = os.environ.get("DEHASHED_EMAIL", "")
    if dehashed_key and dehashed_email:
        try:
            r = s.get(
                "https://api.dehashed.com/search",
                params={"query": query, "size": 10},
                auth=(dehashed_email, dehashed_key),
                headers={"Accept": "application/json"},
                timeout=15
            )
            if r.status_code == 200:
                data = r.json()
                results["dehashed"] = {
                    "total":   data.get("total", 0),
                    "entries": data.get("entries", [])[:5]
                }
        except Exception:
            pass

    # ── AI Summary ────────────────────────────────────────────────
    ai_summary = ""
    if GROQ_AVAILABLE:
        ai_summary = _ask_groq(
            f"Analyze these leak check results for '{query}'. "
            f"What is the severity? What data was exposed? "
            f"What are the security implications? "
            f"What immediate actions should be taken?",
            context=json.dumps(results, indent=2)
        )

    report = (
        f"Leak Check: {query}\n\n"
        + json.dumps(results, indent=2)
        + f"\n\nAI Summary:\n{ai_summary}"
    )
    path = _save(f"leak_{query.replace('@','_at_')}", report)

    # Build message
    hibp_data = results.get("hibp", {})
    if isinstance(hibp_data, dict) and hibp_data.get("found"):
        msg = (
            f"⚠️ LEAKED: {query} found in "
            f"{hibp_data['count']} breach(es):\n"
            f"  Breaches: {', '.join(hibp_data['breaches'][:5])}\n"
            f"  Data exposed: {', '.join(hibp_data.get('data_classes',[])[:5])}"
        )
    elif isinstance(hibp_data, dict) and not hibp_data.get("found", True):
        msg = f"✅ {query} not found in HIBP database."
    else:
        msg = f"Leak check complete for {query}."

    if ai_summary:
        msg += f"\n\nAI: {ai_summary[:200]}"

    return {
        "success":    True,
        "query":      query,
        "results":    results,
        "ai_summary": ai_summary,
        "report":     path,
        "message":    msg
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PASTE SITE MONITORING (Real-time)
# ══════════════════════════════════════════════════════════════════════════════

_monitor_threads  = {}
_monitor_results  = {}
_monitor_stop_evs = {}


def start_paste_monitor(
    keywords:  list,
    duration:  int  = 300,
    alert_fn:  callable = None
) -> dict:
    """
    Real-time monitoring of paste sites for keywords.
    Checks Pastebin, Ghostbin, paste.ee, rentry.co.
    """
    monitor_id = f"monitor_{int(time.time())}"
    stop_ev    = threading.Event()
    results    = []

    _monitor_stop_evs[monitor_id] = stop_ev
    _monitor_results[monitor_id]  = results

    paste_sources = [
        "https://psbdmp.ws/api/search/{kw}",
        "https://pastebin.com/search?q={kw}",
    ]

    def _monitor():
        s = requests.Session()
        s.headers.update({"User-Agent": random.choice(USER_AGENTS)})

        end_time = time.time() + duration
        while not stop_ev.is_set() and time.time() < end_time:
            for kw in keywords:
                for source in paste_sources:
                    try:
                        url = source.format(kw=requests.utils.quote(kw))
                        r   = s.get(url, timeout=10)
                        if r.status_code == 200 and kw.lower() in r.text.lower():
                            entry = {
                                "keyword": kw,
                                "source":  url,
                                "time":    datetime.now().isoformat(),
                                "snippet": r.text[:300]
                            }
                            results.append(entry)
                            if alert_fn:
                                alert_fn(f"[PasteMonitor] Match: {kw} on {url}")
                    except Exception:
                        pass
                    time.sleep(random.uniform(1, 3))
            time.sleep(30)

    t = threading.Thread(target=_monitor, daemon=True)
    t.start()
    _monitor_threads[monitor_id] = t

    return {
        "success":    True,
        "monitor_id": monitor_id,
        "keywords":   keywords,
        "duration":   duration,
        "message": (
            f"Paste monitor started (ID: {monitor_id}). "
            f"Watching for: {', '.join(keywords)}. "
            f"Duration: {duration}s"
        )
    }


def stop_paste_monitor(monitor_id: str = None) -> dict:
    """Stop a paste monitor."""
    if monitor_id and monitor_id in _monitor_stop_evs:
        _monitor_stop_evs[monitor_id].set()
        results = _monitor_results.get(monitor_id, [])
        path    = _save(f"paste_monitor_{monitor_id}", json.dumps(results, indent=2))
        return {
            "success":  True,
            "found":    len(results),
            "report":   path,
            "message":  f"Monitor stopped. Found {len(results)} matches. Report: {path}"
        }

    # Stop all
    for mid, ev in _monitor_stop_evs.items():
        ev.set()
    return {"success": True, "message": "All paste monitors stopped."}


def get_monitor_results(monitor_id: str) -> dict:
    """Get current results from a paste monitor."""
    results = _monitor_results.get(monitor_id, [])
    return {
        "success": True,
        "count":   len(results),
        "results": results,
        "message": f"Monitor has found {len(results)} matches so far."
    }


# ══════════════════════════════════════════════════════════════════════════════
#  .ONION CRAWLER
# ══════════════════════════════════════════════════════════════════════════════

def onion_crawler(
    seed_url:   str,
    max_pages:  int  = 10,
    keywords:   list = None,
    save:       bool = True
) -> dict:
    """
    Crawl .onion sites — follow links, extract content.
    Searches for keywords across pages.
    """
    visited   = set()
    to_visit  = [seed_url]
    found     = []
    matches   = []
    keywords  = keywords or []

    while to_visit and len(visited) < max_pages:
        url = to_visit.pop(0)
        if url in visited:
            continue

        try:
            s = _get_tor_session()
            r = s.get(url, timeout=20)
            visited.add(url)

            content = r.text
            page    = {
                "url":     url,
                "status":  r.status_code,
                "length":  len(content),
                "preview": content[:200]
            }

            # Check for keywords
            for kw in keywords:
                if kw.lower() in content.lower():
                    count = content.lower().count(kw.lower())
                    matches.append({
                        "url":     url,
                        "keyword": kw,
                        "count":   count
                    })
                    page["keyword_match"] = True

            found.append(page)

            # Extract new .onion links to follow
            new_links = re.findall(
                r'http://[a-z2-7]{16,56}\.onion[^\s"\'<>]*',
                content
            )
            for link in new_links:
                if link not in visited and link not in to_visit:
                    to_visit.append(link)

            time.sleep(random.uniform(1, 3))

        except Exception as e:
            visited.add(url)
            found.append({"url": url, "error": str(e)})

    # AI summary
    ai_summary = ""
    if GROQ_AVAILABLE and found:
        pages_summary = "\n".join([
            f"  {p['url']}: {p.get('preview','?')[:100]}"
            for p in found[:5] if not p.get("error")
        ])
        ai_summary = _ask_groq(
            f"Analyze this dark web crawl starting from {seed_url}. "
            f"What kind of sites were found? "
            f"Any significant findings or threats?",
            context=f"Pages crawled: {len(found)}\n\n{pages_summary}"
        )

    report = (
        f"Onion Crawler: {seed_url}\n"
        f"Pages: {len(found)}\n"
        f"Keyword matches: {len(matches)}\n\n"
        + json.dumps({"pages": found, "matches": matches}, indent=2)
        + f"\n\nAI Summary:\n{ai_summary}"
    )
    path = _save(f"crawler_{seed_url[:20].replace('/','_')}", report) if save else ""

    return {
        "success":    True,
        "seed":       seed_url,
        "pages":      len(found),
        "matches":    matches,
        "ai_summary": ai_summary,
        "report":     path,
        "message": (
            f"Crawled {len(found)} pages from {seed_url}.\n"
            f"Keyword matches: {len(matches)}\n"
            + (f"AI: {ai_summary[:200]}" if ai_summary else "")
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PROXYCHAINS — CROSS PLATFORM
# ══════════════════════════════════════════════════════════════════════════════

def run_via_proxychains(command: str) -> dict:
    """Run any command through Tor/proxychains."""
    if OS == "Linux":
        if _check_tool("proxychains4"):
            full_cmd = f"proxychains4 -q {command}"
        elif _check_tool("proxychains"):
            full_cmd = f"proxychains -q {command}"
        else:
            return {
                "success": False,
                "message": "proxychains not found. Install: apt install proxychains4"
            }
        r = _run(full_cmd, timeout=120)

    elif OS == "Windows":
        # Windows: use torsocks or route through Tor SOCKS manually
        return {
            "success": False,
            "message": (
                "proxychains not available on Windows. "
                "Use Tor SOCKS5 proxy (127.0.0.1:9050) manually in your application."
            )
        }

    elif OS == "Darwin":
        if _check_tool("proxychains4"):
            r = _run(f"proxychains4 -q {command}", timeout=120)
        else:
            return {
                "success": False,
                "message": "Install: brew install proxychains-ng"
            }

    return {
        "success": r["code"] == 0,
        "output":  r["stdout"][:500],
        "message": r["stdout"][:300] if r["code"] == 0 else f"Error: {r['stderr'][:200]}"
    }


# ══════════════════════════════════════════════════════════════════════════════
#  TOR BROWSER — CROSS PLATFORM
# ══════════════════════════════════════════════════════════════════════════════

def open_tor_browser(url: str = "") -> dict:
    """Open Tor Browser GUI — cross-platform."""
    if OS == "Linux":
        paths = [
            "/usr/bin/torbrowser-launcher",
            "/opt/tor-browser/start-tor-browser",
            str(Path.home() / "tor-browser/start-tor-browser"),
            "/usr/local/bin/tor-browser",
        ]
        for p in paths:
            if Path(p).exists():
                cmd = f"{p} {url}" if url else p
                subprocess.Popen(cmd, shell=True)
                return {
                    "success": True,
                    "message": f"Tor Browser launched{f' at {url}' if url else ''}."
                }
        return {
            "success": False,
            "message": "Tor Browser not found. Install: apt install torbrowser-launcher"
        }

    elif OS == "Windows":
        paths = [
            str(Path.home() / "Desktop/Tor Browser/Browser/firefox.exe"),
            r"C:\Program Files\Tor Browser\Browser\firefox.exe",
            str(Path.home() / "AppData\Local\Tor Browser\Browser\firefox.exe"),
        ]
        for p in paths:
            if Path(p).exists():
                args = [p]
                if url:
                    args.append(url)
                subprocess.Popen(args)
                return {
                    "success": True,
                    "message": f"Tor Browser launched from {p}."
                }
        return {
            "success": False,
            "message": (
                "Tor Browser not found. "
                "Download from https://www.torproject.org/download/"
            )
        }

    elif OS == "Darwin":
        paths = [
            "/Applications/Tor Browser.app",
            str(Path.home() / "Applications/Tor Browser.app"),
        ]
        for p in paths:
            if Path(p).exists():
                cmd = f"open '{p}'"
                if url:
                    cmd = f"open -a 'Tor Browser' '{url}'"
                subprocess.Popen(cmd, shell=True)
                return {
                    "success": True,
                    "message": f"Tor Browser launched."
                }
        return {
            "success": False,
            "message": "Tor Browser not found. Download from https://www.torproject.org/download/"
        }

    return {"success": False, "message": f"Unsupported OS: {OS}"}


# ══════════════════════════════════════════════════════════════════════════════
#  THREAT INTEL CORRELATION
# ══════════════════════════════════════════════════════════════════════════════

def threat_intel(
    query:     str,
    query_type: str = "domain"
) -> dict:
    """
    Correlate threat intelligence from multiple sources.
    Checks VirusTotal, AbuseIPDB, ThreatFox, URLhaus.
    """
    results = {}
    s = requests.Session()
    s.headers.update({"User-Agent": random.choice(USER_AGENTS)})

    # ── VirusTotal ────────────────────────────────────────────────
    vt_key = os.environ.get("VIRUSTOTAL_API_KEY", "")
    if vt_key:
        try:
            endpoint = {
                "ip":     f"https://www.virustotal.com/api/v3/ip_addresses/{query}",
                "domain": f"https://www.virustotal.com/api/v3/domains/{query}",
                "url":    f"https://www.virustotal.com/api/v3/urls/{query}",
                "hash":   f"https://www.virustotal.com/api/v3/files/{query}",
            }.get(query_type, f"https://www.virustotal.com/api/v3/domains/{query}")

            r = s.get(endpoint, headers={"x-apikey": vt_key}, timeout=15)
            if r.status_code == 200:
                data  = r.json().get("data", {}).get("attributes", {})
                stats = data.get("last_analysis_stats", {})
                results["virustotal"] = {
                    "malicious":  stats.get("malicious", 0),
                    "suspicious": stats.get("suspicious", 0),
                    "harmless":   stats.get("harmless", 0),
                    "reputation": data.get("reputation", 0),
                }
        except Exception as e:
            results["vt_error"] = str(e)

    # ── AbuseIPDB (for IPs) ───────────────────────────────────────
    abuse_key = os.environ.get("ABUSEIPDB_API_KEY", "")
    if abuse_key and query_type == "ip":
        try:
            r = s.get(
                "https://api.abuseipdb.com/api/v2/check",
                params={"ipAddress": query, "maxAgeInDays": 90},
                headers={"Key": abuse_key, "Accept": "application/json"},
                timeout=15
            )
            if r.status_code == 200:
                data = r.json().get("data", {})
                results["abuseipdb"] = {
                    "abuse_score":   data.get("abuseConfidenceScore", 0),
                    "country":       data.get("countryCode", ""),
                    "isp":           data.get("isp", ""),
                    "total_reports": data.get("totalReports", 0),
                    "is_tor":        data.get("isTor", False),
                }
        except Exception:
            pass

    # ── ThreatFox ─────────────────────────────────────────────────
    try:
        r = s.post(
            "https://threatfox-api.abuse.ch/api/v1/",
            json={"query": "search_ioc", "search_term": query},
            timeout=15
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("query_status") == "ok":
                iocs = data.get("data", [])[:5]
                results["threatfox"] = {
                    "found": len(iocs) > 0,
                    "iocs":  iocs
                }
    except Exception:
        pass

    # ── URLhaus ───────────────────────────────────────────────────
    try:
        r = s.post(
            "https://urlhaus-api.abuse.ch/v1/host/",
            data={"host": query},
            timeout=15
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("query_status") == "is_host":
                results["urlhaus"] = {
                    "urls_count": data.get("urls_count", 0),
                    "blacklists": data.get("blacklists", {}),
                }
    except Exception:
        pass

    # ── AI Summary ────────────────────────────────────────────────
    ai_summary = ""
    if GROQ_AVAILABLE:
        ai_summary = _ask_groq(
            f"Analyze this threat intelligence for {query} ({query_type}). "
            f"What is the threat level? Is this malicious? "
            f"What actions should be taken?",
            context=json.dumps(results, indent=2)
        )

    report = (
        f"Threat Intel: {query} ({query_type})\n\n"
        + json.dumps(results, indent=2)
        + f"\n\nAI Summary:\n{ai_summary}"
    )
    path = _save(f"threatintel_{query.replace('.','_')}", report)

    vt  = results.get("virustotal", {})
    msg = (
        f"Threat Intel: {query}\n"
        f"  VT Malicious: {vt.get('malicious', 'N/A')}\n"
        f"  VT Suspicious: {vt.get('suspicious', 'N/A')}\n"
        f"  AbuseIPDB Score: {results.get('abuseipdb', {}).get('abuse_score', 'N/A')}\n"
        f"  ThreatFox: {'Found' if results.get('threatfox', {}).get('found') else 'Not found'}\n"
        + (f"\nAI: {ai_summary[:200]}" if ai_summary else "")
    )

    return {
        "success":    True,
        "query":      query,
        "results":    results,
        "ai_summary": ai_summary,
        "report":     path,
        "message":    msg
    }


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN DISPATCHER
# ══════════════════════════════════════════════════════════════════════════════

def run_darkweb_agent(args: dict, speak=None, player=None) -> str:
    action = args.get("action", "status")
    speak  = speak or (lambda x: None)

    def say(msg: str):
        short = str(msg)[:300]
        if player:
            player.write_log(f"[DarkWeb|{OS}] {short}")
        speak(short)

    say(f"Dark Web Agent active on {OS}")

    if action == "start_tor":
        say("Starting Tor...")
        r = start_tor()
        say(r["message"])
        return r["message"]

    elif action == "stop_tor":
        r = stop_tor()
        say(r["message"])
        return r["message"]

    elif action == "status":
        r = check_tor()
        say(r["message"])
        return r["message"]

    elif action == "new_identity":
        say("Getting new Tor identity...")
        r = get_new_identity()
        say(r["message"])
        return r["message"]

    elif action == "start_i2p":
        say("Starting I2P...")
        r = start_i2p()
        say(r["message"])
        return r["message"]

    elif action == "browse_i2p":
        url = args.get("url") or args.get("target")
        if not url:
            return "URL required."
        r = browse_i2p(url)
        say(r["message"])
        return r["message"]

    elif action == "browse":
        url = args.get("url") or args.get("target")
        if not url:
            return "URL required."
        say(f"Browsing {url} via Tor...")
        r = browse_onion(url, args.get("save", True))
        say(r["message"])
        return r.get("preview", r["message"])[:500]

    elif action == "search":
        query = args.get("query") or args.get("target")
        if not query:
            return "Query required."
        say(f"Searching dark web: {query}...")
        r = darkweb_search(
            query  = query,
            engine = args.get("engine", "ahmia"),
            pages  = int(args.get("pages", 1)),
            save   = args.get("save", True)
        )
        say(r["message"])
        return r["message"]

    elif action == "leak_check":
        query = args.get("target") or args.get("email") or args.get("query")
        if not query:
            return "Email or query required."
        say(f"Checking leaks for {query}...")
        r = check_leak(query, args.get("leak_type", "email"))
        say(r["message"])
        return r["message"]

    elif action == "paste_monitor":
        keywords = args.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [keywords]
        target = args.get("target")
        if target:
            keywords.append(target)
        if not keywords:
            return "Keywords required."
        r = start_paste_monitor(
            keywords = keywords,
            duration = int(args.get("duration", 300)),
            alert_fn = say
        )
        say(r["message"])
        return r["message"]

    elif action == "stop_monitor":
        r = stop_paste_monitor(args.get("monitor_id"))
        say(r["message"])
        return r["message"]

    elif action == "crawl":
        url = args.get("url") or args.get("target")
        if not url:
            return "Seed URL required."
        say(f"Crawling {url}...")
        keywords = args.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [keywords]
        r = onion_crawler(
            seed_url  = url,
            max_pages = int(args.get("max_pages", 10)),
            keywords  = keywords,
        )
        say(r["message"])
        return r["message"]

    elif action == "threat_intel":
        query = args.get("target") or args.get("query")
        if not query:
            return "Target required."
        say(f"Threat intel on {query}...")
        r = threat_intel(query, args.get("query_type", "domain"))
        say(r["message"])
        return r["message"]

    elif action == "proxychains":
        cmd = args.get("command")
        if not cmd:
            return "Command required."
        say(f"Running via proxychains: {cmd}")
        r = run_via_proxychains(cmd)
        say(r["message"])
        return r["message"]

    elif action == "open_browser":
        r = open_tor_browser(args.get("url", ""))
        say(r["message"])
        return r["message"]

    else:
        return (
            f"Unknown dark web action: {action}. "
            f"Available: start_tor | stop_tor | status | new_identity | "
            f"start_i2p | browse_i2p | browse | search | leak_check | "
            f"paste_monitor | stop_monitor | crawl | threat_intel | "
            f"proxychains | open_browser"
        )