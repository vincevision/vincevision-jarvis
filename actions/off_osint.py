# actions/off_osint.py
# JARVIS Enhanced OSINT Agent — Cross-Platform, Modern, AI-Powered

import subprocess
import os
import sys
import json
import re
import time
import random
import platform
import requests
import threading
from pathlib import Path
from datetime import datetime

# ── OS Detection ──────────────────────────────────────────────────────────────
OS   = platform.system()   # Windows | Linux | Darwin
ARCH = platform.machine()

OSINT_DIR = Path.home() / "jarvis_captures" / "osint"
OSINT_DIR.mkdir(parents=True, exist_ok=True)

# ── Groq AI ───────────────────────────────────────────────────────────────────
try:
    from groq import Groq
    _groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
    GROQ_AVAILABLE = True
except Exception:
    GROQ_AVAILABLE = False

# ── Random User Agents (Stealth) ──────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
]

def _random_ua() -> str:
    return random.choice(USER_AGENTS)

def _random_delay():
    """Random delay to avoid rate limiting."""
    time.sleep(random.uniform(0.5, 2.0))


def _ask_groq(prompt: str, context: str = "") -> str:
    """Ask Groq AI for OSINT analysis."""
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
                        "You are an expert OSINT analyst and intelligence officer. "
                        "Analyze data, find connections, identify patterns, "
                        "build target profiles, correlate breaches. "
                        "Give structured, actionable intelligence reports. "
                        "Use modern 2024 OSINT techniques."
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


def _run(cmd: str, timeout: int = 120) -> dict:
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
        return {"stdout": "", "stderr": f"Timeout after {timeout}s", "code": -1}
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
    path = OSINT_DIR / f"{name}_{ts}.txt"
    path.write_text(content, encoding="utf-8", errors="ignore")
    return str(path)


def _get_session() -> requests.Session:
    """Get a requests session with random UA and Tor if available."""
    s = requests.Session()
    s.headers.update({"User-Agent": _random_ua()})
    # Try Tor
    try:
        s.proxies = {
            "http":  "socks5h://127.0.0.1:9050",
            "https": "socks5h://127.0.0.1:9050"
        }
        s.get("http://check.torproject.org/api/ip", timeout=5)
    except Exception:
        s.proxies = {}
    return s


# ══════════════════════════════════════════════════════════════════════════════
#  SHERLOCK — USERNAME SEARCH
# ══════════════════════════════════════════════════════════════════════════════

def sherlock_search(username: str, sites: str = "") -> dict:
    """Search username across 400+ social networks."""
    found     = []
    not_found = 0

    if _check_tool("sherlock"):
        cmd = f"sherlock {username} --print-found --timeout 10 --no-color"
        if sites:
            cmd += f" --site {sites}"
        r = _run(cmd, timeout=300)
        for line in r["stdout"].splitlines():
            if "[+]" in line:
                url = line.split("[+]")[-1].strip()
                found.append(url)
            elif "[-]" in line:
                not_found += 1

    else:
        # Fallback: manual check on top platforms
        platforms = {
            "github":    f"https://github.com/{username}",
            "twitter":   f"https://twitter.com/{username}",
            "instagram": f"https://instagram.com/{username}",
            "reddit":    f"https://reddit.com/user/{username}",
            "linkedin":  f"https://linkedin.com/in/{username}",
            "tiktok":    f"https://tiktok.com/@{username}",
            "youtube":   f"https://youtube.com/@{username}",
            "pinterest":  f"https://pinterest.com/{username}",
            "twitch":    f"https://twitch.tv/{username}",
            "steam":     f"https://steamcommunity.com/id/{username}",
            "medium":    f"https://medium.com/@{username}",
            "gitlab":    f"https://gitlab.com/{username}",
        }
        s = _get_session()
        for platform_name, url in platforms.items():
            try:
                _random_delay()
                resp = s.get(url, timeout=10, allow_redirects=True)
                if resp.status_code == 200:
                    found.append(url)
                else:
                    not_found += 1
            except Exception:
                not_found += 1

    # AI analysis
    ai_summary = ""
    if found and GROQ_AVAILABLE:
        ai_summary = _ask_groq(
            f"Analyze these social media profiles for username '{username}'. "
            f"What can we determine about this person? "
            f"What other platforms should we check? "
            f"What OSINT techniques would be most effective next?",
            context="\n".join(found[:20])
        )

    report = (
        f"Sherlock Search: {username}\n"
        f"Found: {len(found)} platforms\n\n"
        + "\n".join(found)
        + f"\n\nAI Analysis:\n{ai_summary}"
    )
    path = _save(f"sherlock_{username}", report)

    return {
        "success":       True,
        "username":      username,
        "found":         found,
        "found_count":   len(found),
        "not_found":     not_found,
        "ai_summary":    ai_summary,
        "report":        path,
        "message": (
            f"Found '{username}' on {len(found)} platforms:\n"
            + "\n".join(found[:10])
            + (f"\n\nAI: {ai_summary[:200]}" if ai_summary else "")
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  THEHARVESTER — EMAIL & SUBDOMAIN HARVEST
# ══════════════════════════════════════════════════════════════════════════════

def theharvester(
    domain:  str,
    sources: str = "google,bing,linkedin,twitter,duckduckgo,yahoo",
    limit:   int = 500
) -> dict:
    """Harvest emails, subdomains, IPs from public sources."""
    emails     = []
    subdomains = []
    hosts      = []
    ips        = []

    if _check_tool("theHarvester") or _check_tool("theharvester"):
        tool     = "theHarvester" if _check_tool("theHarvester") else "theharvester"
        out_file = str(OSINT_DIR / f"harvester_{domain}")
        cmd = (
            f"{tool} -d {domain} "
            f"-b {sources} "
            f"-l {limit} "
            f"-f {out_file}"
        )
        r = _run(cmd, timeout=300)

        for line in r["stdout"].splitlines():
            line = line.strip()
            if "@" in line and "." in line and len(line) < 100:
                emails.append(line)
            elif domain in line and "." in line and " " not in line:
                subdomains.append(line)
            elif re.match(r"\d+\.\d+\.\d+\.\d+", line):
                ips.append(line)

    else:
        # Fallback: Google dorks via requests
        s = _get_session()

        # Email harvest
        try:
            _random_delay()
            r = s.get(
                f"https://www.google.com/search?q=site:{domain}+%40{domain}&num=50",
                timeout=15
            )
            emails_found = re.findall(
                r'[a-zA-Z0-9._%+-]+@' + re.escape(domain),
                r.text
            )
            emails.extend(list(set(emails_found)))
        except Exception:
            pass

        # Subdomain via crt.sh
        try:
            _random_delay()
            r = s.get(
                f"https://crt.sh/?q=%.{domain}&output=json",
                timeout=20
            )
            if r.status_code == 200:
                data = r.json()
                for entry in data:
                    name = entry.get("name_value", "")
                    for sub in name.splitlines():
                        sub = sub.strip().lstrip("*.")
                        if domain in sub and sub not in subdomains:
                            subdomains.append(sub)
        except Exception:
            pass

    # Deduplicate
    emails     = list(set(emails))[:50]
    subdomains = list(set(subdomains))[:100]
    ips        = list(set(ips))[:30]

    # AI correlation
    ai_analysis = ""
    if GROQ_AVAILABLE and (emails or subdomains):
        ai_analysis = _ask_groq(
            f"Analyze this OSINT data for {domain}. "
            f"What are the most interesting findings? "
            f"Which emails look like admin/IT accounts? "
            f"What attack vectors does this expose? "
            f"What should we investigate next?",
            context=(
                f"Domain: {domain}\n"
                f"Emails ({len(emails)}): {', '.join(emails[:10])}\n"
                f"Subdomains ({len(subdomains)}): {', '.join(subdomains[:10])}\n"
                f"IPs: {', '.join(ips[:5])}"
            )
        )

    report = (
        f"TheHarvester — {domain}\n"
        f"{'='*50}\n\n"
        f"Emails ({len(emails)}):\n" + "\n".join(emails) +
        f"\n\nSubdomains ({len(subdomains)}):\n" + "\n".join(subdomains) +
        f"\n\nIPs ({len(ips)}):\n" + "\n".join(ips) +
        f"\n\nAI Analysis:\n{ai_analysis}"
    )
    path = _save(f"harvester_{domain}", report)

    return {
        "success":     True,
        "domain":      domain,
        "emails":      emails,
        "subdomains":  subdomains,
        "ips":         ips,
        "ai_analysis": ai_analysis,
        "report":      path,
        "message": (
            f"Harvested from {domain}:\n"
            f"  Emails: {len(emails)}\n"
            f"  Subdomains: {len(subdomains)}\n"
            f"  IPs: {len(ips)}\n"
            f"Top emails: {', '.join(emails[:5])}\n"
            + (f"\nAI: {ai_analysis[:200]}" if ai_analysis else "")
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  GOOGLE DORKS
# ══════════════════════════════════════════════════════════════════════════════

def google_dorks(
    target:    str,
    dork_type: str = "all"
) -> dict:
    """
    Generate and optionally run Google dork searches.
    Finds exposed files, login pages, cameras, databases, etc.
    """
    dorks = {
        "files": [
            f"site:{target} filetype:pdf",
            f"site:{target} filetype:xls OR filetype:xlsx",
            f"site:{target} filetype:doc OR filetype:docx",
            f"site:{target} filetype:sql",
            f"site:{target} filetype:log",
            f"site:{target} filetype:env",
            f"site:{target} filetype:config",
            f"site:{target} filetype:bak",
            f"site:{target} filetype:xml",
        ],
        "login": [
            f"site:{target} inurl:login",
            f"site:{target} inurl:admin",
            f"site:{target} inurl:panel",
            f"site:{target} inurl:dashboard",
            f"site:{target} inurl:wp-admin",
            f"site:{target} inurl:phpmyadmin",
            f"site:{target} inurl:cpanel",
        ],
        "sensitive": [
            f"site:{target} intext:password",
            f"site:{target} intext:username intext:password",
            f"site:{target} intext:\"api_key\"",
            f"site:{target} intext:\"secret_key\"",
            f"site:{target} intext:\"AWS_ACCESS_KEY\"",
            f"site:{target} intext:\"mongodb://\"",
            f"site:{target} intext:\"db_password\"",
        ],
        "exposed": [
            f"site:{target} intitle:\"index of\"",
            f"site:{target} intitle:\"Directory listing\"",
            f"site:{target} inurl:.git",
            f"site:{target} inurl:.env",
            f"site:{target} inurl:backup",
            f"site:{target} inurl:config",
        ],
        "cameras": [
            f"site:{target} inurl:view/index.shtml",
            f"site:{target} inurl:ViewerFrame",
            f"site:{target} intitle:\"Network Camera\"",
        ],
        "subdomains": [
            f"site:*.{target}",
            f"site:*.*.{target}",
        ],
        "github": [
            f"site:github.com {target} password",
            f"site:github.com {target} api_key",
            f"site:github.com {target} secret",
            f"site:github.com {target} token",
        ],
        "pastebin": [
            f"site:pastebin.com {target}",
            f"site:paste.ee {target}",
            f"site:ghostbin.com {target}",
        ],
    }

    # Select dork type
    if dork_type == "all":
        selected = {}
        for k, v in dorks.items():
            selected[k] = v
    elif dork_type in dorks:
        selected = {dork_type: dorks[dork_type]}
    else:
        return {
            "success": False,
            "message": f"Unknown dork type. Available: {', '.join(dorks.keys())}, all"
        }

    # Format all dorks
    all_dorks = []
    for category, dork_list in selected.items():
        for dork in dork_list:
            all_dorks.append({
                "category": category,
                "dork":     dork,
                "url":      f"https://www.google.com/search?q={requests.utils.quote(dork)}"
            })

    report = f"Google Dorks for: {target}\n\n"
    for d in all_dorks:
        report += f"[{d['category']}] {d['dork']}\n"
        report += f"  URL: {d['url']}\n\n"

    path = _save(f"dorks_{target.replace('.','_')}", report)

    # AI: which dorks are most likely to find something
    ai_priority = ""
    if GROQ_AVAILABLE:
        dork_list_str = "\n".join([d["dork"] for d in all_dorks])
        ai_priority = _ask_groq(
            f"Which of these Google dorks are most likely to find "
            f"sensitive information for {target}? Rank top 5 and explain why.",
            context=dork_list_str
        )

    return {
        "success":    True,
        "target":     target,
        "dorks":      all_dorks,
        "count":      len(all_dorks),
        "ai_priority": ai_priority,
        "report":     path,
        "message": (
            f"Generated {len(all_dorks)} dorks for {target}.\n"
            f"Report: {path}\n"
            + (f"\nAI Priority: {ai_priority[:300]}" if ai_priority else "")
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  GITHUB OSINT — LEAKED SECRETS
# ══════════════════════════════════════════════════════════════════════════════

def github_osint(
    query:    str,
    search_type: str = "code"
) -> dict:
    """
    Search GitHub for leaked credentials, API keys, secrets.
    Uses GitHub search API.
    """
    results  = []
    findings = []

    # Patterns to look for
    secret_patterns = [
        r'api[_-]?key\s*[=:]\s*["\']?([A-Za-z0-9_\-]{20,})',
        r'secret[_-]?key\s*[=:]\s*["\']?([A-Za-z0-9_\-]{20,})',
        r'password\s*[=:]\s*["\']?([A-Za-z0-9_\-!@#$%]{8,})',
        r'token\s*[=:]\s*["\']?([A-Za-z0-9_\-]{20,})',
        r'AWS_ACCESS_KEY_ID\s*[=:]\s*([A-Z0-9]{20})',
        r'AWS_SECRET_ACCESS_KEY\s*[=:]\s*([A-Za-z0-9+/]{40})',
        r'(ghp_[A-Za-z0-9]{36})',   # GitHub PAT
        r'(ghs_[A-Za-z0-9]{36})',   # GitHub Actions token
        r'(sk-[A-Za-z0-9]{48})',    # OpenAI API key
        r'(AIza[A-Za-z0-9\-_]{35})', # Google API key
    ]

    try:
        s = _get_session()
        gh_token = os.environ.get("GITHUB_TOKEN", "")
        if gh_token:
            s.headers.update({"Authorization": f"token {gh_token}"})

        # Search GitHub code
        search_queries = [
            f"{query} password",
            f"{query} api_key",
            f"{query} secret",
            f"{query} token",
            f"{query} database",
        ]

        for sq in search_queries[:3]:
            _random_delay()
            r = s.get(
                "https://api.github.com/search/code",
                params={
                    "q":        sq,
                    "per_page": 10,
                    "sort":     "indexed"
                },
                timeout=15
            )
            if r.status_code == 200:
                data  = r.json()
                items = data.get("items", [])
                for item in items:
                    result = {
                        "repo":    item.get("repository", {}).get("full_name", ""),
                        "file":    item.get("path", ""),
                        "url":     item.get("html_url", ""),
                        "query":   sq,
                    }
                    results.append(result)

                    # Fetch file content to scan for secrets
                    try:
                        _random_delay()
                        raw_url = item.get("html_url", "").replace(
                            "github.com", "raw.githubusercontent.com"
                        ).replace("/blob/", "/")
                        raw_r = s.get(raw_url, timeout=10)
                        if raw_r.status_code == 200:
                            content = raw_r.text
                            for pattern in secret_patterns:
                                matches = re.findall(pattern, content, re.IGNORECASE)
                                for match in matches:
                                    findings.append({
                                        "repo":    result["repo"],
                                        "file":    result["file"],
                                        "url":     result["url"],
                                        "secret":  match[:50] + "..." if len(match) > 50 else match
                                    })
                    except Exception:
                        pass

            elif r.status_code == 403:
                break  # Rate limited

    except Exception as e:
        pass

    # Also search via dork
    dork_results = []
    for sq in [f"site:github.com {query} password", f"site:github.com {query} api_key"]:
        dork_results.append({
            "dork": sq,
            "url":  f"https://www.google.com/search?q={requests.utils.quote(sq)}"
        })

    # AI analysis
    ai_analysis = ""
    if GROQ_AVAILABLE and (results or findings):
        summary = f"Found {len(results)} files, {len(findings)} potential secrets"
        ai_analysis = _ask_groq(
            f"Analyze these GitHub OSINT findings for '{query}'. "
            f"What are the most critical secrets found? "
            f"What is the potential impact? "
            f"What should be investigated next?",
            context=summary + "\n\nFindings:\n" + json.dumps(findings[:5], indent=2)
        )

    report = (
        f"GitHub OSINT: {query}\n\n"
        f"Files Found: {len(results)}\n"
        f"Secrets Found: {len(findings)}\n\n"
        f"Secrets:\n" + json.dumps(findings, indent=2) +
        f"\n\nFiles:\n" + json.dumps(results, indent=2) +
        f"\n\nAI Analysis:\n{ai_analysis}"
    )
    path = _save(f"github_{query.replace(' ','_')[:20]}", report)

    return {
        "success":     True,
        "query":       query,
        "files":       results,
        "secrets":     findings,
        "dork_urls":   dork_results,
        "ai_analysis": ai_analysis,
        "report":      path,
        "message": (
            f"GitHub OSINT for '{query}':\n"
            f"  Files: {len(results)}\n"
            f"  Secrets found: {len(findings)}\n"
            + ("\n".join([f"  [{f['repo']}] {f['secret']}" for f in findings[:5]]))
            + (f"\nAI: {ai_analysis[:200]}" if ai_analysis else "")
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  IMAGE METADATA OSINT (EXIF)
# ══════════════════════════════════════════════════════════════════════════════

def image_metadata(file_path: str) -> dict:
    """Extract EXIF metadata from images — can reveal GPS, device info, etc."""
    path = Path(file_path)
    if not path.exists():
        return {"success": False, "message": f"File not found: {file_path}"}

    metadata = {}

    # Try exiftool (most complete)
    if _check_tool("exiftool"):
        r = _run(f"exiftool -j '{file_path}'")
        if r["code"] == 0:
            try:
                data = json.loads(r["stdout"])
                if data:
                    metadata = data[0]
            except Exception:
                metadata = {"raw": r["stdout"]}

    # Try Pillow as fallback
    if not metadata:
        try:
            from PIL import Image
            from PIL.ExifTags import TAGS, GPSTAGS
            img  = Image.open(file_path)
            exif = img._getexif()
            if exif:
                for tag_id, value in exif.items():
                    tag = TAGS.get(tag_id, tag_id)
                    metadata[str(tag)] = str(value)
        except Exception:
            pass

    # Extract GPS coordinates
    gps_info = {}
    lat, lon  = None, None
    for key, val in metadata.items():
        if "GPS" in str(key):
            gps_info[key] = val
        if "GPSLatitude" in str(key) and "Ref" not in str(key):
            lat = str(val)
        if "GPSLongitude" in str(key) and "Ref" not in str(key):
            lon = str(val)

    # Build Google Maps link if we have coords
    maps_link = ""
    if lat and lon:
        maps_link = f"https://maps.google.com/?q={lat},{lon}"

    # AI analysis
    ai_analysis = ""
    if GROQ_AVAILABLE and metadata:
        interesting = {k: v for k, v in metadata.items()
                      if any(kw in str(k).lower()
                             for kw in ["gps", "make", "model", "software",
                                       "date", "author", "creator", "location"])}
        ai_analysis = _ask_groq(
            "Analyze this image metadata for OSINT value. "
            "What can we determine about the person/device/location? "
            "What are the most significant findings?",
            context=json.dumps(interesting, indent=2)
        )

    report = (
        f"Image Metadata: {file_path}\n\n"
        + json.dumps(metadata, indent=2)
        + f"\n\nGPS: {maps_link or 'Not found'}"
        + f"\n\nAI Analysis:\n{ai_analysis}"
    )
    path_out = _save(f"exif_{path.name}", report)

    return {
        "success":     True,
        "file":        file_path,
        "metadata":    metadata,
        "gps":         gps_info,
        "maps_link":   maps_link,
        "ai_analysis": ai_analysis,
        "report":      path_out,
        "message": (
            f"Extracted {len(metadata)} metadata fields from {path.name}.\n"
            + (f"GPS Location: {maps_link}\n" if maps_link else "")
            + (f"AI: {ai_analysis[:200]}" if ai_analysis else "")
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PASTEBIN MONITORING
# ══════════════════════════════════════════════════════════════════════════════

def pastebin_monitor(
    keywords:  list,
    duration:  int  = 60,
    save:      bool = True
) -> dict:
    """Monitor Pastebin and similar sites for keywords."""
    found   = []
    stop_ev = threading.Event()

    paste_apis = [
        "https://psbdmp.ws/api/search/{keyword}",
        "https://pastebin.com/search?q={keyword}",
    ]

    def monitor_loop():
        s = _get_session()
        while not stop_ev.is_set():
            for keyword in keywords:
                for api in paste_apis:
                    try:
                        url = api.format(keyword=keyword)
                        r   = s.get(url, timeout=10)
                        if r.status_code == 200 and keyword.lower() in r.text.lower():
                            found.append({
                                "keyword": keyword,
                                "url":     url,
                                "time":    datetime.now().isoformat(),
                                "snippet": r.text[:200]
                            })
                    except Exception:
                        pass
                    _random_delay()
            time.sleep(30)

    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()
    time.sleep(min(duration, 60))
    stop_ev.set()

    report = json.dumps(found, indent=2)
    path   = _save(f"pastebin_monitor", report) if save else ""

    return {
        "success":  True,
        "keywords": keywords,
        "found":    found,
        "count":    len(found),
        "report":   path,
        "message": (
            f"Pastebin monitor: {len(found)} matches for {keywords}.\n"
            + "\n".join([f"  [{f['keyword']}] {f['url']}" for f in found[:5]])
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  EMAIL OSINT
# ══════════════════════════════════════════════════════════════════════════════

def email_osint(email: str) -> dict:
    """Comprehensive email OSINT — breaches, platforms, validity."""
    results = {}
    s = _get_session()

    # ── HIBP breach check ─────────────────────────────────────────
    try:
        _random_delay()
        r = s.get(
            f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}",
            headers={
                "User-Agent":   "JARVIS-OSINT/2.0",
                "hibp-api-key": os.environ.get("HIBP_API_KEY", "")
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
                "types":    [b.get("DataClasses", []) for b in breaches[:3]]
            }
        elif r.status_code == 404:
            results["hibp"] = {"found": False}
    except Exception as e:
        results["hibp_error"] = str(e)

    # ── Holehe — platform check ───────────────────────────────────
    if _check_tool("holehe"):
        r = _run(f"holehe {email} --only-used --no-color", timeout=120)
        found_platforms = [
            l.strip() for l in r["stdout"].splitlines()
            if "[+]" in l
        ]
        results["holehe"] = found_platforms

    # ── h8mail ────────────────────────────────────────────────────
    if _check_tool("h8mail"):
        r = _run(f"h8mail -t {email} --no-banner", timeout=120)
        results["h8mail"] = r["stdout"][:500]

    # ── Email format validation ───────────────────────────────────
    domain = email.split("@")[-1]
    mx_r   = _run(f"dig MX {domain} +short", timeout=10)
    results["mx_records"]  = mx_r["stdout"].splitlines()[:5]
    results["domain"]      = domain
    results["domain_valid"] = len(results["mx_records"]) > 0

    # ── Gravatar check ────────────────────────────────────────────
    import hashlib
    email_hash = hashlib.md5(email.lower().encode()).hexdigest()
    gravatar   = f"https://www.gravatar.com/avatar/{email_hash}?d=404"
    try:
        g = s.get(gravatar, timeout=5)
        results["gravatar"] = g.status_code == 200
        if g.status_code == 200:
            results["gravatar_url"] = gravatar
    except Exception:
        results["gravatar"] = False

    # ── AI profile build ─────────────────────────────────────────
    ai_profile = ""
    if GROQ_AVAILABLE:
        ai_profile = _ask_groq(
            f"Build an intelligence profile for email: {email}\n"
            f"Based on this data, what can we determine about the person?\n"
            f"What are the security implications of these breaches?\n"
            f"What should be investigated next?",
            context=json.dumps(results, indent=2)
        )

    report = (
        f"Email OSINT: {email}\n\n"
        + json.dumps(results, indent=2)
        + f"\n\nAI Profile:\n{ai_profile}"
    )
    path = _save(f"email_{email.replace('@','_at_')}", report)

    hibp = results.get("hibp", {})
    if isinstance(hibp, dict) and hibp.get("found"):
        breach_summary = (
            f"⚠️ Found in {hibp['count']} breach(es): "
            f"{', '.join(hibp['breaches'][:5])}"
        )
    else:
        breach_summary = "✅ Not found in known breaches."

    return {
        "success":    True,
        "email":      email,
        "results":    results,
        "ai_profile": ai_profile,
        "report":     path,
        "message": (
            f"Email OSINT: {email}\n"
            f"{breach_summary}\n"
            f"Platforms: {len(results.get('holehe', []))}\n"
            f"Gravatar: {'Yes' if results.get('gravatar') else 'No'}\n"
            + (f"\nAI: {ai_profile[:200]}" if ai_profile else "")
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PERSON SEARCH
# ══════════════════════════════════════════════════════════════════════════════

def person_search(
    name:     str,
    location: str = "",
    username: str = "",
    email:    str = "",
    phone:    str = ""
) -> dict:
    """Comprehensive person OSINT — aggregates all available data."""
    profile  = {"name": name, "data": {}}
    timeline = []

    if username:
        timeline.append(f"Searching username: {username}")
        r = sherlock_search(username)
        profile["data"]["social_media"] = r["found"]
        timeline.append(f"Found on {r['found_count']} platforms")

    if email:
        timeline.append(f"Searching email: {email}")
        r = email_osint(email)
        profile["data"]["email_osint"] = r["results"]
        timeline.append(f"Email breaches: {r['results'].get('hibp', {})}")

    # Google dorks for name
    dork_queries = [
        f"\"{name}\" site:linkedin.com",
        f"\"{name}\" site:facebook.com",
        f"\"{name}\" \"{location}\"" if location else f"\"{name}\" contact",
        f"\"{name}\" resume OR cv filetype:pdf",
        f"\"{name}\" phone OR email",
    ]
    profile["data"]["dork_queries"] = dork_queries
    timeline.append("Generated Google dork queries")

    # Phone OSINT
    if phone:
        try:
            import phonenumbers
            parsed = phonenumbers.parse(phone)
            valid  = phonenumbers.is_valid_number(parsed)
            region = phonenumbers.region_code_for_number(parsed)
            carrier_name = ""
            try:
                from phonenumbers import carrier
                carrier_name = carrier.name_for_number(parsed, "en")
            except Exception:
                pass
            profile["data"]["phone"] = {
                "number":  phone,
                "valid":   valid,
                "region":  region,
                "carrier": carrier_name
            }
            timeline.append(f"Phone: {region} {carrier_name}")
        except Exception as e:
            profile["data"]["phone"] = {"error": str(e)}

    # AI profile compilation
    ai_profile = ""
    if GROQ_AVAILABLE:
        ai_profile = _ask_groq(
            f"Build a comprehensive intelligence profile for: {name}\n"
            f"Location hint: {location}\n"
            f"What are the key findings?\n"
            f"What attack vectors exist for social engineering?\n"
            f"What additional OSINT should be gathered?",
            context=json.dumps(profile["data"], indent=2)
        )

    report = (
        f"Person OSINT: {name}\n"
        f"{'='*50}\n\n"
        f"Timeline:\n" + "\n".join([f"  - {t}" for t in timeline]) +
        f"\n\nData:\n" + json.dumps(profile, indent=2) +
        f"\n\nAI Profile:\n{ai_profile}"
    )
    path = _save(f"person_{name.replace(' ','_')}", report)

    return {
        "success":    True,
        "name":       name,
        "profile":    profile,
        "timeline":   timeline,
        "ai_profile": ai_profile,
        "report":     path,
        "message": (
            f"Person OSINT: {name}\n"
            f"Data points: {len(profile['data'])}\n"
            f"Timeline: {len(timeline)} steps\n"
            f"Report: {path}\n"
            + (f"\nAI: {ai_profile[:300]}" if ai_profile else "")
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  IP & DOMAIN RECON
# ══════════════════════════════════════════════════════════════════════════════

def ip_recon(target: str) -> dict:
    """Deep IP/domain reconnaissance."""
    results = {}
    s = _get_session()

    # ── Basic DNS ─────────────────────────────────────────────────
    if OS != "Windows":
        results["a_record"]   = _run(f"dig A {target} +short", timeout=10)["stdout"]
        results["mx_record"]  = _run(f"dig MX {target} +short", timeout=10)["stdout"]
        results["ns_record"]  = _run(f"dig NS {target} +short", timeout=10)["stdout"]
        results["txt_record"] = _run(f"dig TXT {target} +short", timeout=10)["stdout"]
        results["whois"]      = _run(f"whois {target}", timeout=20)["stdout"][:500]
    else:
        results["nslookup"] = _run(f"nslookup {target}")["stdout"][:300]
        results["whois"]    = _run(f"whois {target}")["stdout"][:300]

    # ── Shodan (if API key) ───────────────────────────────────────
    shodan_key = os.environ.get("SHODAN_API_KEY", "")
    if shodan_key:
        try:
            _random_delay()
            r = s.get(
                f"https://api.shodan.io/shodan/host/{target}",
                params={"key": shodan_key},
                timeout=15
            )
            if r.status_code == 200:
                data = r.json()
                results["shodan"] = {
                    "ports":   data.get("ports", []),
                    "vulns":   data.get("vulns", []),
                    "org":     data.get("org", ""),
                    "country": data.get("country_name", ""),
                    "isp":     data.get("isp", ""),
                    "os":      data.get("os", ""),
                }
        except Exception:
            pass

    # ── IPInfo ────────────────────────────────────────────────────
    try:
        _random_delay()
        r = s.get(f"https://ipinfo.io/{target}/json", timeout=10)
        if r.status_code == 200:
            results["ipinfo"] = r.json()
    except Exception:
        pass

    # ── VirusTotal ────────────────────────────────────────────────
    vt_key = os.environ.get("VIRUSTOTAL_API_KEY", "")
    if vt_key:
        try:
            _random_delay()
            r = s.get(
                f"https://www.virustotal.com/api/v3/domains/{target}",
                headers={"x-apikey": vt_key},
                timeout=15
            )
            if r.status_code == 200:
                data = r.json().get("data", {}).get("attributes", {})
                results["virustotal"] = {
                    "malicious":  data.get("last_analysis_stats", {}).get("malicious", 0),
                    "suspicious": data.get("last_analysis_stats", {}).get("suspicious", 0),
                    "categories": data.get("categories", {}),
                }
        except Exception:
            pass

    # ── Subdomain enumeration ─────────────────────────────────────
    subdomains = []
    try:
        _random_delay()
        r = s.get(
            f"https://crt.sh/?q=%.{target}&output=json",
            timeout=20
        )
        if r.status_code == 200:
            data = r.json()
            for entry in data:
                name = entry.get("name_value", "")
                for sub in name.splitlines():
                    sub = sub.strip().lstrip("*.")
                    if target in sub and sub not in subdomains:
                        subdomains.append(sub)
    except Exception:
        pass

    results["subdomains"] = subdomains[:30]

    # ── AI analysis ───────────────────────────────────────────────
    ai_analysis = ""
    if GROQ_AVAILABLE:
        ai_analysis = _ask_groq(
            f"Analyze this reconnaissance data for {target}. "
            f"What are the most interesting findings? "
            f"What vulnerabilities or attack vectors exist? "
            f"What should be investigated next?",
            context=json.dumps(results, indent=2)[:3000]
        )

    report = (
        f"IP/Domain Recon: {target}\n\n"
        + json.dumps(results, indent=2)
        + f"\n\nAI Analysis:\n{ai_analysis}"
    )
    path = _save(f"iprecon_{target.replace('.','_')}", report)

    return {
        "success":     True,
        "target":      target,
        "results":     results,
        "subdomains":  subdomains,
        "ai_analysis": ai_analysis,
        "report":      path,
        "message": (
            f"Recon on {target}:\n"
            f"  Subdomains: {len(subdomains)}\n"
            f"  Shodan ports: {results.get('shodan', {}).get('ports', [])}\n"
            f"  Shodan vulns: {results.get('shodan', {}).get('vulns', [])}\n"
            f"  Location: {results.get('ipinfo', {}).get('city', '')}, "
            f"{results.get('ipinfo', {}).get('country', '')}\n"
            + (f"\nAI: {ai_analysis[:200]}" if ai_analysis else "")
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  RECON-NG
# ══════════════════════════════════════════════════════════════════════════════

def recon_ng(domain: str, modules: list = None) -> dict:
    """Run Recon-ng automated reconnaissance."""
    if not _check_tool("recon-ng"):
        # Fallback to manual recon
        return ip_recon(domain)

    if not modules:
        modules = [
            "recon/domains-hosts/google_site_web",
            "recon/domains-hosts/bing_domain_web",
            "recon/domains-contacts/whois_pocs",
            "recon/hosts-hosts/resolve",
        ]

    rc_lines = [
        f"workspaces create {domain.replace('.','_')}",
        f"db insert domains name={domain}",
    ]
    for mod in modules:
        rc_lines += [f"modules load {mod}", "run"]
    rc_lines.append("exit")

    rc_file = Path(f"/tmp/recon_{domain}.rc")
    rc_file.write_text("\n".join(rc_lines))

    r    = _run(f"recon-ng -r {rc_file}", timeout=300)
    path = _save(f"reconng_{domain}", r["stdout"])

    hosts = [
        l.strip() for l in r["stdout"].splitlines()
        if domain in l and "." in l and not l.startswith("[")
    ]

    return {
        "success": True,
        "domain":  domain,
        "hosts":   hosts[:30],
        "report":  path,
        "message": (
            f"Recon-ng: {domain} — "
            f"Found {len(hosts)} hosts. Report: {path}"
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PHONE OSINT
# ══════════════════════════════════════════════════════════════════════════════

def phone_osint(phone: str) -> dict:
    """Deep phone number investigation."""
    results = {}

    # Phonenumbers library
    try:
        import phonenumbers
        from phonenumbers import geocoder, carrier, timezone
        parsed = phonenumbers.parse(phone)
        results["valid"]    = phonenumbers.is_valid_number(parsed)
        results["possible"] = phonenumbers.is_possible_number(parsed)
        results["country"]  = geocoder.description_for_number(parsed, "en")
        results["carrier"]  = carrier.name_for_number(parsed, "en")
        results["timezones"] = list(timezone.time_zones_for_number(parsed))
        results["number_type"] = str(phonenumbers.number_type(parsed))
        results["formatted"] = phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
        )
    except Exception as e:
        results["parse_error"] = str(e)

    # NumVerify API (if key available)
    nv_key = os.environ.get("NUMVERIFY_API_KEY", "")
    if nv_key:
        try:
            s = _get_session()
            r = s.get(
                "http://apilayer.net/api/validate",
                params={
                    "access_key": nv_key,
                    "number":     phone,
                    "format":     1
                },
                timeout=10
            )
            if r.status_code == 200:
                results["numverify"] = r.json()
        except Exception:
            pass

    # AI analysis
    ai_analysis = ""
    if GROQ_AVAILABLE:
        ai_analysis = _ask_groq(
            f"Analyze this phone number OSINT data. "
            f"What can we determine? What are the OSINT implications? "
            f"How can this be used in a social engineering attack?",
            context=json.dumps(results, indent=2)
        )

    path = _save(f"phone_{phone.replace('+','').replace(' ','')}", json.dumps(results))

    return {
        "success":     True,
        "phone":       phone,
        "results":     results,
        "ai_analysis": ai_analysis,
        "report":      path,
        "message": (
            f"Phone OSINT: {phone}\n"
            f"  Valid: {results.get('valid')}\n"
            f"  Country: {results.get('country')}\n"
            f"  Carrier: {results.get('carrier')}\n"
            f"  Type: {results.get('number_type')}\n"
            + (f"\nAI: {ai_analysis[:200]}" if ai_analysis else "")
        )
    }


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN DISPATCHER
# ══════════════════════════════════════════════════════════════════════════════

def run_osint_agent(args: dict, speak=None, player=None) -> str:
    action = args.get("action", "sherlock")
    speak  = speak or (lambda x: None)

    def say(msg: str):
        short = str(msg)[:300]
        if player:
            player.write_log(f"[OSINT|{OS}] {short}")
        speak(short)

    say(f"OSINT Agent active on {OS}")

    if action == "sherlock":
        target = args.get("target") or args.get("username")
        if not target:
            return "Username required."
        say(f"Running Sherlock on '{target}'...")
        r = sherlock_search(target, args.get("sites", ""))
        say(r["message"])
        return r["message"]

    elif action == "harvester":
        domain = args.get("target") or args.get("domain")
        if not domain:
            return "Domain required."
        say(f"Harvesting {domain}...")
        r = theharvester(
            domain  = domain,
            sources = args.get("sources", "google,bing,linkedin,twitter,duckduckgo"),
            limit   = int(args.get("limit", 500))
        )
        say(r["message"])
        return r["message"]

    elif action == "dorks":
        target = args.get("target") or args.get("domain")
        if not target:
            return "Target required."
        say(f"Generating dorks for {target}...")
        r = google_dorks(target, args.get("dork_type", "all"))
        say(r["message"])
        return r["message"]

    elif action == "github":
        query = args.get("target") or args.get("query")
        if not query:
            return "Query required."
        say(f"GitHub OSINT for '{query}'...")
        r = github_osint(query, args.get("search_type", "code"))
        say(r["message"])
        return r["message"]

    elif action == "image_meta":
        file_p = args.get("file") or args.get("target")
        if not file_p:
            return "File path required."
        r = image_metadata(file_p)
        say(r["message"])
        return r["message"]

    elif action == "pastebin":
        keywords = args.get("keywords", [])
        if isinstance(keywords, str):
            keywords = [keywords]
        target = args.get("target")
        if target:
            keywords.append(target)
        if not keywords:
            return "Keywords required."
        say(f"Monitoring paste sites for: {keywords}...")
        r = pastebin_monitor(keywords, int(args.get("duration", 60)))
        say(r["message"])
        return r["message"]

    elif action == "email":
        email = args.get("target") or args.get("email")
        if not email:
            return "Email required."
        say(f"Email OSINT: {email}...")
        r = email_osint(email)
        say(r["message"])
        return r["message"]

    elif action == "person":
        name = args.get("target") or args.get("name")
        if not name:
            return "Name required."
        say(f"Person search: {name}...")
        r = person_search(
            name     = name,
            location = args.get("location", ""),
            username = args.get("username", ""),
            email    = args.get("email", ""),
            phone    = args.get("phone", "")
        )
        say(r["message"])
        return r["message"]

    elif action == "ip_recon":
        target = args.get("target") or args.get("ip") or args.get("domain")
        if not target:
            return "Target required."
        say(f"Recon on {target}...")
        r = ip_recon(target)
        say(r["message"])
        return r["message"]

    elif action == "recon_ng":
        domain = args.get("target") or args.get("domain")
        if not domain:
            return "Domain required."
        say(f"Recon-ng on {domain}...")
        r = recon_ng(domain, args.get("modules"))
        say(r["message"])
        return r["message"]

    elif action == "phone":
        phone = args.get("target") or args.get("phone")
        if not phone:
            return "Phone number required."
        say(f"Phone OSINT: {phone}...")
        r = phone_osint(phone)
        say(r["message"])
        return r["message"]

    else:
        return (
            f"Unknown OSINT action: {action}. "
            f"Available: sherlock | harvester | dorks | github | "
            f"image_meta | pastebin | email | person | ip_recon | "
            f"recon_ng | phone"
        )