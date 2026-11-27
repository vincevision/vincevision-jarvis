# number_tracer.py
"""
JARVIS Number Tracer & Scammer Hunter — TRUECALLER GRADE
─────────────────────────────────────────────────────────
Features:
  - Phone validation, carrier, line type
  - Real identity lookup (Telegram, Truecaller, OpenCNAM, Sync.me, EveryCaller)
  - Telegram rich profile (name, username, bio, photo, last seen)
  - Email discovery (Google/Bing dorks + EmailRep verification)
  - Messaging app presence (WhatsApp, Telegram, Signal)
  - Social media profile discovery (FB, IG, LinkedIn, Twitter, etc.)
  - Data breach lookup (HIBP, DeHashed, LeakCheck)
  - Reputation scoring (IPQualityScore)
  - Spam database checks
  - Comprehensive Truecaller-style GUI report
"""

import re
import os
import sys
import json
import time
import platform
import requests
import urllib.parse
from pathlib            import Path
from datetime           import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

_OS = platform.system()


# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR    = _get_base_dir()
REPORTS_DIR = BASE_DIR / "reports" / "number_traces"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _get_api_key(service: str, key: str = "api_key") -> str:
    """Pull API keys from credential_manager."""
    try:
        from core.credential_manager import get_credential
        return get_credential(service, key) or ""
    except Exception:
        return ""


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ═════════════════════════════════════════════
# PHONE NUMBER PARSER
# ═════════════════════════════════════════════

def _parse_number(phone: str) -> dict:
    """Parse and validate a phone number."""
    try:
        import phonenumbers
        from phonenumbers import (
            geocoder, carrier, timezone,
            NumberParseException, PhoneNumberType,
        )

        clean = re.sub(r"[^\d+\-\(\) ]", "", phone.strip())

        parsed = None
        for attempt in [clean, f"+1{clean}", f"+{clean}"]:
            try:
                parsed = phonenumbers.parse(attempt, None)
                if phonenumbers.is_valid_number(parsed):
                    break
                parsed = None
            except NumberParseException:
                continue

        if not parsed:
            for cc in ["+1", "+44", "+27", "+234", "+91", "+86", "+33", "+49", "+61"]:
                try:
                    test = phonenumbers.parse(f"{cc}{clean}", None)
                    if phonenumbers.is_valid_number(test):
                        parsed = test
                        break
                except Exception:
                    continue

        if not parsed:
            return {"valid": False, "error": "Could not parse", "raw": phone}

        num_type = phonenumbers.number_type(parsed)
        type_map = {
            PhoneNumberType.MOBILE:               "Mobile",
            PhoneNumberType.FIXED_LINE:           "Landline",
            PhoneNumberType.FIXED_LINE_OR_MOBILE: "Mobile/Landline",
            PhoneNumberType.TOLL_FREE:            "Toll-Free",
            PhoneNumberType.PREMIUM_RATE:         "Premium Rate ⚠️",
            PhoneNumberType.SHARED_COST:          "Shared Cost",
            PhoneNumberType.VOIP:                 "VOIP",
            PhoneNumberType.PERSONAL_NUMBER:      "Personal",
            PhoneNumberType.PAGER:                "Pager",
            PhoneNumberType.UAN:                  "UAN",
            PhoneNumberType.UNKNOWN:              "Unknown",
        }

        return {
            "valid":           True,
            "raw":             phone,
            "international":   phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
            "national":        phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL),
            "e164":            phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164),
            "country_code":    f"+{parsed.country_code}",
            "national_number": str(parsed.national_number),
            "country":         geocoder.description_for_number(parsed, "en") or "Unknown",
            "carrier":         carrier.name_for_number(parsed, "en") or "Unknown",
            "type":            type_map.get(num_type, "Unknown"),
            "timezones":       list(timezone.time_zones_for_number(parsed)),
            "is_valid":        phonenumbers.is_valid_number(parsed),
            "is_possible":     phonenumbers.is_possible_number(parsed),
            "region_code":     phonenumbers.region_code_for_number(parsed) or "",
        }

    except ImportError:
        clean = re.sub(r"[\s\-\(\)]", "", phone)
        return {
            "valid": True, "raw": phone, "e164": clean,
            "international": clean, "national": clean,
            "country": "Unknown (install phonenumbers)",
            "carrier": "Unknown", "type": "Unknown", "timezones": [],
        }


# ═════════════════════════════════════════════
# IDENTITY LOOKUP (NAME)
# ═════════════════════════════════════════════

def _lookup_identity(e164: str, region: str = "us") -> dict:
    """Find owner's name from multiple sources."""
    identity = {"name": None, "aliases": [], "sources": [], "emails_from_id": []}

    # ── 0. Telegram (free, most reliable) ────────
    try:
        from actions.telegram_lookup import telegram_lookup, is_telegram_ready
        if is_telegram_ready():
            tg = telegram_lookup(e164, download_photo=False)
            if tg.get("registered") and tg.get("full_name"):
                identity["name"] = tg["full_name"]
                if tg.get("username"):
                    identity["aliases"].append(f"@{tg['username']}")
                identity["sources"].append("telegram")
                if tg.get("bio"):
                    identity["telegram_bio"] = tg["bio"]
    except Exception as e:
        print(f"[Identity] Telegram failed: {e}")

    # ── 1. Truecaller unofficial API ─────────────
    tc_token = _get_api_key("truecaller", "auth_token")
    if tc_token:
        try:
            r = requests.get(
                "https://search5-noneu.truecaller.com/v2/search",
                params={
                    "q":           e164,
                    "countryCode": region.upper() or "US",
                    "type":        "4",
                    "placement":   "SEARCHRESULTS,HISTORY,DETAILS",
                    "encoding":    "json",
                },
                headers={**HEADERS, "Authorization": f"Bearer {tc_token}"},
                timeout=8,
            )
            if r.status_code == 200:
                data = r.json()
                for d in data.get("data", []):
                    name = d.get("name")
                    if name:
                        if not identity["name"]:
                            identity["name"] = name
                        elif name not in identity["aliases"] and name != identity["name"]:
                            identity["aliases"].append(name)
                        for addr in d.get("internetAddresses", []):
                            if addr.get("service") == "email":
                                identity["emails_from_id"].append(addr["id"])
                if "truecaller" not in identity["sources"]:
                    identity["sources"].append("truecaller")
        except Exception as e:
            print(f"[Identity] Truecaller failed: {e}")

    # ── 2. OpenCNAM (US numbers) ─────────────────
    cnam_sid = _get_api_key("opencnam", "sid")
    cnam_tok = _get_api_key("opencnam", "token")
    if cnam_sid and cnam_tok and e164.startswith("+1"):
        try:
            r = requests.get(
                f"https://api.opencnam.com/v3/phone/{e164}",
                auth=(cnam_sid, cnam_tok),
                params={"format": "json"},
                timeout=6,
            )
            if r.status_code == 200:
                data = r.json()
                name = data.get("name")
                if name:
                    if not identity["name"]:
                        identity["name"] = name
                    elif name not in identity["aliases"] and name != identity["name"]:
                        identity["aliases"].append(name)
                    identity["sources"].append("opencnam")
        except Exception as e:
            print(f"[Identity] OpenCNAM failed: {e}")

    # ── 3. NumVerify ─────────────────────────────
    nv_key = _get_api_key("numverify", "api_key")
    if nv_key:
        try:
            r = requests.get(
                "http://apilayer.net/api/validate",
                params={
                    "access_key": nv_key,
                    "number":     e164.lstrip("+"),
                    "format":     1,
                },
                timeout=6,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("valid"):
                    identity["numverify"] = {
                        "carrier":   data.get("carrier"),
                        "line_type": data.get("line_type"),
                        "location":  data.get("location"),
                    }
                    identity["sources"].append("numverify")
        except Exception:
            pass

    # ── 4. Sync.me scraping ──────────────────────
    try:
        r = requests.get(
            f"https://sync.me/search/?number={urllib.parse.quote(e164)}",
            headers=HEADERS, timeout=8,
        )
        if r.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            for sel in ["h1.name", ".profile-name", ".user-name", "h1"]:
                el = soup.select_one(sel)
                if el:
                    text = el.get_text(strip=True)
                    if text and len(text) > 2 and "phone" not in text.lower() and "sync" not in text.lower():
                        if not identity["name"]:
                            identity["name"] = text
                        elif text not in identity["aliases"]:
                            identity["aliases"].append(text)
                        identity["sources"].append("sync.me")
                        break
    except Exception:
        pass

    # ── 5. EveryCaller ───────────────────────────
    try:
        clean = re.sub(r"[^\d]", "", e164)
        r = requests.get(
            f"https://www.everycaller.com/phone-number/{clean}/",
            headers=HEADERS, timeout=6,
        )
        if r.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            for sel in [".caller-name", ".owner-name", "h1"]:
                el = soup.select_one(sel)
                if el:
                    text = el.get_text(strip=True)
                    if text and "everycaller" not in text.lower() and len(text) > 2:
                        if not identity["name"]:
                            identity["name"] = text
                        identity["sources"].append("everycaller")
                        break
    except Exception:
        pass

    # Dedupe
    identity["aliases"]        = list(set(identity["aliases"]))
    identity["emails_from_id"] = list(set(identity["emails_from_id"]))
    if identity["name"] in identity["aliases"]:
        identity["aliases"].remove(identity["name"])

    return identity


# ═════════════════════════════════════════════
# EMAIL DISCOVERY
# ═════════════════════════════════════════════

def _discover_emails(phone: str, e164: str, name: str = None) -> list:
    """Find emails linked to this phone via Google dorking + verification."""
    emails = set()

    queries = [
        f'"{e164}" email',
        f'"{phone}" "@"',
        f'"{e164}" contact',
    ]
    if name:
        queries.append(f'"{name}" "{e164}" email')

    email_re = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

    for q in queries[:2]:
        try:
            r = requests.get(
                f"https://www.google.com/search?q={urllib.parse.quote(q)}",
                headers=HEADERS, timeout=6,
            )
            if r.status_code == 200:
                for em in email_re.findall(r.text):
                    em = em.lower()
                    if not any(x in em for x in [
                        "google.com", "gstatic.com", "schema.org",
                        "w3.org", "example.com", "sentry.io",
                    ]):
                        emails.add(em)
        except Exception:
            pass
        time.sleep(0.4)

    # Bing fallback
    try:
        r = requests.get(
            f"https://www.bing.com/search?q={urllib.parse.quote(f'{e164} email')}",
            headers=HEADERS, timeout=6,
        )
        if r.status_code == 200:
            for em in email_re.findall(r.text)[:5]:
                em = em.lower()
                if not any(x in em for x in ["bing.com", "microsoft.com"]):
                    emails.add(em)
    except Exception:
        pass

    # Verify via EmailRep
    verified = []
    for em in list(emails)[:5]:
        info = {"email": em}
        try:
            r = requests.get(
                f"https://emailrep.io/{em}",
                headers={**HEADERS, "Accept": "application/json"},
                timeout=5,
            )
            if r.status_code == 200:
                data = r.json()
                info.update({
                    "reputation": data.get("reputation"),
                    "suspicious": data.get("suspicious"),
                    "references": data.get("references"),
                    "details":    data.get("details", {}),
                })
        except Exception:
            pass
        verified.append(info)

    return verified


# ═════════════════════════════════════════════
# MESSAGING APP PRESENCE
# ═════════════════════════════════════════════

def _check_messaging_apps(e164: str) -> dict:
    """Check WhatsApp, Telegram, Signal presence — with rich Telegram data."""
    apps = {}

    # ── WhatsApp ─────────────────────────────────
    try:
        clean = e164.lstrip("+")
        r = requests.get(
            f"https://wa.me/{clean}",
            headers=HEADERS, timeout=5, allow_redirects=True,
        )
        if r.status_code == 200:
            text = r.text.lower()
            if "chat on whatsapp" in text or "use whatsapp" in text or "send a message" in text:
                apps["whatsapp"] = {"registered": True, "url": f"https://wa.me/{clean}"}
            else:
                apps["whatsapp"] = {"registered": "unknown"}
        else:
            apps["whatsapp"] = {"registered": "unknown"}
    except Exception:
        apps["whatsapp"] = {"error": "check failed"}

    # ── Telegram (FULL LOOKUP) ───────────────────
    try:
        from actions.telegram_lookup import telegram_lookup, is_telegram_ready
        if is_telegram_ready():
            tg = telegram_lookup(e164, download_photo=True)
            if tg.get("registered"):
                apps["telegram"] = {
                    "registered":  True,
                    "user_id":     tg.get("user_id"),
                    "username":    tg.get("username"),
                    "first_name":  tg.get("first_name"),
                    "last_name":   tg.get("last_name"),
                    "full_name":   tg.get("full_name"),
                    "bio":         tg.get("bio"),
                    "is_premium":  tg.get("is_premium"),
                    "is_verified": tg.get("is_verified"),
                    "is_scam":     tg.get("is_scam"),
                    "is_fake":     tg.get("is_fake"),
                    "last_seen":   tg.get("last_seen"),
                    "photo_path":  tg.get("photo_path"),
                }
            else:
                apps["telegram"] = {
                    "registered": False,
                    "message":    tg.get("message", "Not on Telegram"),
                }
        else:
            apps["telegram"] = {"skipped": "Run setup wizard to configure Telegram"}
    except Exception as e:
        apps["telegram"] = {"error": str(e)[:80]}

    # ── Signal ───────────────────────────────────
    try:
        import subprocess, shutil
        if shutil.which("signal-cli"):
            r = subprocess.run(
                ["signal-cli", "--output=json", "getUserStatus", e164],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                try:
                    data = json.loads(r.stdout) if r.stdout else {}
                    apps["signal"] = {"registered": data.get("isRegistered", False)}
                except Exception:
                    apps["signal"] = {"registered": "unknown"}
            else:
                apps["signal"] = {"registered": "unknown"}
        else:
            apps["signal"] = {"skipped": "signal-cli not installed"}
    except Exception:
        apps["signal"] = {"error": "check failed"}

    apps["viber"]    = {"skipped": "no public API"}
    apps["imessage"] = {"skipped": "macOS only"}

    return apps


# ═════════════════════════════════════════════
# SOCIAL MEDIA DISCOVERY
# ═════════════════════════════════════════════

def _discover_social(phone: str, e164: str, name: str = None) -> dict:
    """Find social media profiles linked to phone via Google dorking."""
    profiles = {}

    dorks = {
        "facebook":  f'"{e164}" site:facebook.com',
        "instagram": f'"{e164}" site:instagram.com',
        "linkedin":  f'"{e164}" site:linkedin.com',
        "twitter":   f'"{e164}" site:twitter.com OR site:x.com',
        "tiktok":    f'"{e164}" site:tiktok.com',
        "github":    f'"{e164}" site:github.com',
    }

    for platform, query in dorks.items():
        try:
            r = requests.get(
                f"https://www.google.com/search?q={urllib.parse.quote(query)}",
                headers=HEADERS, timeout=5,
            )
            if r.status_code == 200:
                from bs4 import BeautifulSoup
                soup    = BeautifulSoup(r.text, "html.parser")
                results = []
                for g in soup.find_all("a", href=True)[:10]:
                    href = g.get("href", "")
                    if platform in href and "google.com" not in href:
                        m = re.search(r"https?://[^\s&]+", href)
                        if m:
                            url = m.group(0)
                            if url not in results:
                                results.append(url)
                if results:
                    profiles[platform] = results[:3]
        except Exception:
            pass
        time.sleep(0.3)

    return profiles


# ═════════════════════════════════════════════
# DATA BREACH LOOKUP
# ═════════════════════════════════════════════

def _check_breaches(e164: str, emails: list = None) -> dict:
    """Check breach databases (HIBP, DeHashed, LeakCheck)."""
    breaches = {"hibp": [], "dehashed": [], "leakcheck": []}

    # ── HaveIBeenPwned (requires API key) ───────
    hibp_key = _get_api_key("hibp", "api_key")
    if hibp_key and emails:
        for em_info in emails[:3]:
            em = em_info.get("email") if isinstance(em_info, dict) else em_info
            if not em:
                continue
            try:
                r = requests.get(
                    f"https://haveibeenpwned.com/api/v3/breachedaccount/{urllib.parse.quote(em)}",
                    headers={
                        **HEADERS,
                        "hibp-api-key": hibp_key,
                        "User-Agent":   "JARVIS-NumberTracer",
                    },
                    timeout=8,
                )
                if r.status_code == 200:
                    for b in r.json():
                        breaches["hibp"].append({
                            "email":        em,
                            "name":         b.get("Name"),
                            "domain":       b.get("Domain"),
                            "breach_date":  b.get("BreachDate"),
                            "data_classes": b.get("DataClasses", []),
                        })
                time.sleep(1.6)  # HIBP rate limit
            except Exception:
                pass

    # ── DeHashed ─────────────────────────────────
    dh_email = _get_api_key("dehashed", "email")
    dh_key   = _get_api_key("dehashed", "api_key")
    if dh_email and dh_key:
        try:
            r = requests.get(
                "https://api.dehashed.com/search",
                params={"query": f"phone:{e164.lstrip('+')}"},
                auth=(dh_email, dh_key),
                headers={**HEADERS, "Accept": "application/json"},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                for entry in (data.get("entries") or [])[:10]:
                    breaches["dehashed"].append({
                        "email":    entry.get("email"),
                        "username": entry.get("username"),
                        "name":     entry.get("name"),
                        "address":  entry.get("address"),
                        "database": entry.get("database_name"),
                    })
        except Exception:
            pass

    # ── LeakCheck ────────────────────────────────
    lc_key = _get_api_key("leakcheck", "api_key")
    if lc_key:
        try:
            r = requests.get(
                "https://leakcheck.io/api/v2/query",
                params={"check": e164.lstrip("+"), "type": "phone"},
                headers={**HEADERS, "X-API-Key": lc_key},
                timeout=8,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("success"):
                    for r_entry in (data.get("result") or [])[:10]:
                        breaches["leakcheck"].append({
                            "source": r_entry.get("source", {}).get("name"),
                            "email":  r_entry.get("email"),
                            "fields": r_entry.get("fields", []),
                        })
        except Exception:
            pass

    return breaches


# ═════════════════════════════════════════════
# REPUTATION SCORING (IPQualityScore)
# ═════════════════════════════════════════════

def _check_reputation(e164: str) -> dict:
    """Use IPQualityScore for fraud scoring."""
    rep = {}
    ipqs_key = _get_api_key("ipqualityscore", "api_key")
    if ipqs_key:
        try:
            r = requests.get(
                f"https://www.ipqualityscore.com/api/json/phone/{ipqs_key}/{e164.lstrip('+')}",
                timeout=8,
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("success"):
                    rep["ipqualityscore"] = {
                        "fraud_score":  data.get("fraud_score"),
                        "valid":        data.get("valid"),
                        "active":       data.get("active"),
                        "carrier":      data.get("carrier"),
                        "line_type":    data.get("line_type"),
                        "country":      data.get("country"),
                        "city":         data.get("city"),
                        "region":       data.get("region"),
                        "timezone":     data.get("timezone"),
                        "do_not_call":  data.get("do_not_call"),
                        "leaked":       data.get("leaked"),
                        "spammer":      data.get("spammer"),
                        "risky":        data.get("risky"),
                        "name":         data.get("name"),
                    }
        except Exception:
            pass
    return rep


# ═════════════════════════════════════════════
# SPAM DATABASE LOOKUP
# ═════════════════════════════════════════════

def _check_scammer_databases(phone: str) -> dict:
    """Check spam DBs."""
    results = {}
    clean   = re.sub(r"[^\d]", "", phone)
    e164    = re.sub(r"[^\d+]", "", phone)

    # NumLookup
    try:
        r = requests.get(
            f"https://api.numlookupapi.com/v1/info/{e164}",
            timeout=5, headers=HEADERS,
        )
        if r.status_code == 200:
            data = r.json()
            results["numlookup"] = {
                "valid":     data.get("valid"),
                "country":   data.get("country_name"),
                "carrier":   data.get("carrier"),
                "line_type": data.get("line_type"),
            }
    except Exception:
        pass

    # ShouldIAnswer
    try:
        r = requests.get(
            f"https://www.shouldianswer.com/phone-number/{clean}",
            timeout=5, headers=HEADERS,
        )
        if r.status_code == 200:
            text = r.text.lower()
            if "scam" in text or "fraud" in text:
                rating = "SCAM ⚠️"
            elif "spam" in text or "telemarket" in text:
                rating = "SPAM"
            elif "safe" in text or "legit" in text:
                rating = "SAFE ✅"
            else:
                rating = "Unknown"
            results["shouldianswer"] = {"rating": rating}
    except Exception:
        pass

    # SpamCalls.net
    try:
        r = requests.get(
            f"https://spamcalls.net/en/number/{clean}",
            timeout=5, headers=HEADERS,
        )
        if r.status_code == 200:
            text = r.text.lower()
            spam_score = 0
            if "scam"         in text: spam_score += 3
            if "fraud"        in text: spam_score += 3
            if "spam"         in text: spam_score += 2
            if "telemarketer" in text: spam_score += 1
            if "robocall"     in text: spam_score += 2
            results["spamcalls"] = {
                "spam_score": spam_score,
                "flagged":    spam_score > 0,
            }
    except Exception:
        pass

    # WhoCallsMe
    try:
        r = requests.get(
            f"https://whocallsme.com/Phone-Number.aspx/{clean}",
            timeout=5, headers=HEADERS,
        )
        if r.status_code == 200:
            from bs4 import BeautifulSoup
            soup    = BeautifulSoup(r.text, "html.parser")
            reports = soup.find_all("div", class_=re.compile("report|comment"))
            results["whocallsme"] = {"report_count": len(reports)}
    except Exception:
        pass

    return results


# ═════════════════════════════════════════════
# OSINT (Google + DuckDuckGo)
# ═════════════════════════════════════════════

def _osint_search(phone: str, number_info: dict) -> dict:
    """OSINT investigation."""
    osint = {}
    intl  = number_info.get("international", phone)

    # Google
    try:
        q = f'"{intl}" scam OR fraud OR reported'
        r = requests.get(
            f"https://www.google.com/search?q={urllib.parse.quote(q)}",
            headers=HEADERS, timeout=6,
        )
        if r.status_code == 200:
            from bs4 import BeautifulSoup
            soup    = BeautifulSoup(r.text, "html.parser")
            results = []
            for result in soup.find_all("div", class_="g")[:5]:
                title   = result.find("h3")
                snippet = result.find("div", class_=re.compile("IsZvec|VwiC3b"))
                if title:
                    results.append({
                        "title":   title.get_text()[:80],
                        "snippet": snippet.get_text()[:140] if snippet else "",
                    })
            osint["google_results"] = results
    except Exception:
        pass

    # DuckDuckGo
    try:
        r = requests.get(
            "https://api.duckduckgo.com/",
            params={
                "q":       f"{intl} scam OR fraud OR spam",
                "format":  "json",
                "no_html": "1",
            },
            timeout=5,
        )
        if r.status_code == 200:
            data    = r.json()
            results = data.get("RelatedTopics", [])[:5]
            osint["duckduckgo"] = [
                r.get("Text", "")[:120] for r in results if r.get("Text")
            ]
    except Exception:
        pass

    return osint


# ═════════════════════════════════════════════
# SPAM SCORE CALCULATOR
# ═════════════════════════════════════════════

def _calculate_spam_score(
    number_info:  dict,
    scammer_data: dict,
    osint_data:   dict,
    breaches:     dict = None,
    reputation:   dict = None,
    msg_apps:     dict = None,
) -> dict:
    """Calculate 0-100 risk score."""
    score, flags, notes = 0, [], []

    # Number type
    num_type = number_info.get("type", "")
    if "Premium Rate" in num_type:
        score += 30
        flags.append("⚠️ Premium rate number")
    if "VOIP" in num_type:
        score += 15
        flags.append("📞 VOIP (harder to trace)")
    if "Toll-Free" in num_type:
        score += 5
        flags.append("📞 Toll-free number")

    if not number_info.get("carrier") or number_info.get("carrier") == "Unknown":
        score += 10
        flags.append("❓ Unknown carrier")

    # IPQS reputation
    if reputation and "ipqualityscore" in reputation:
        ipqs = reputation["ipqualityscore"]
        fs = ipqs.get("fraud_score", 0) or 0
        if fs >= 75:
            score += 35
            flags.append(f"🚨 IPQS fraud score: {fs}/100")
        elif fs >= 50:
            score += 20
            flags.append(f"⚠️ IPQS fraud score: {fs}/100")
        if ipqs.get("spammer"):
            score += 25
            flags.append("🚨 IPQS marks as spammer")
        if ipqs.get("risky"):
            score += 15
            flags.append("⚠️ IPQS marks as risky")
        if ipqs.get("leaked"):
            score += 10
            flags.append("📤 Number found in leaks (IPQS)")
        if not ipqs.get("active", True):
            score += 5
            flags.append("📵 Number reported inactive")

    # Scammer DBs
    for source, data in scammer_data.items():
        if not isinstance(data, dict):
            continue
        rating = str(data.get("rating", "")).upper()
        if "SCAM" in rating or "FRAUD" in rating:
            score += 40
            flags.append(f"🚨 {source}: SCAM")
        elif "SPAM" in rating:
            score += 20
            flags.append(f"📵 {source}: SPAM")

        ss = data.get("spam_score", 0)
        if ss > 2:
            score += ss * 5
            flags.append(f"⚠️ {source}: spam score {ss}")

        rc = data.get("report_count", 0)
        if rc > 5:
            score += min(rc * 2, 20)
            flags.append(f"📋 {source}: {rc} user reports")

    # OSINT
    for r in osint_data.get("google_results", []):
        text = (r.get("title", "") + r.get("snippet", "")).lower()
        if any(w in text for w in ["scam", "fraud", "fake", "dangerous", "phishing"]):
            score += 15
            flags.append(f"🔍 Mentioned in scam reports")
            break

    # Breaches
    if breaches:
        total_breaches = sum(len(v) for v in breaches.values())
        if total_breaches > 0:
            score += min(total_breaches * 3, 15)
            notes.append(f"Found in {total_breaches} breach record(s)")

    # Telegram red flags
    if msg_apps:
        tg = msg_apps.get("telegram", {})
        if isinstance(tg, dict):
            if tg.get("is_scam"):
                score += 50
                flags.append("🚨 Telegram flagged as SCAM")
            if tg.get("is_fake"):
                score += 30
                flags.append("⚠️ Telegram flagged as FAKE")

        # Active on multiple messaging apps reduces risk slightly
        active_apps = sum(
            1 for k, v in msg_apps.items()
            if isinstance(v, dict) and v.get("registered") is True
        )
        if active_apps >= 2:
            score = max(0, score - 5)
            notes.append(f"Active on {active_apps} messaging apps (reduces risk)")

    score = min(score, 100)

    if score >= 70:
        risk, color = "🚨 HIGH RISK — Likely Scammer",       "RED"
    elif score >= 40:
        risk, color = "⚠️ MEDIUM RISK — Suspicious",         "ORANGE"
    elif score >= 20:
        risk, color = "⚡ LOW RISK — Use Caution",            "YELLOW"
    else:
        risk, color = "✅ LOW RISK — Appears Safe",          "GREEN"

    return {"score": score, "risk_level": risk, "color": color, "flags": flags, "notes": notes}


# ═════════════════════════════════════════════
# REPORT GENERATOR (TRUECALLER STYLE)
# ═════════════════════════════════════════════

def _generate_report(
    number, number_info, identity, emails, msg_apps, social,
    breaches, reputation, scammer_data, osint_data, spam_score,
) -> str:
    """Build full Truecaller-style report."""
    now    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    border = "═" * 64
    lines  = [
        border,
        "🔍 JARVIS NUMBER INVESTIGATION REPORT",
        border,
        f"Generated:    {now}",
        f"Investigator: JARVIS AI",
        border,
        "",
        "👤 IDENTITY",
        "─" * 50,
    ]

    if identity.get("name"):
        lines.append(f"  Name:     {identity['name']}")
    else:
        lines.append("  Name:     ❌ Not found")
    if identity.get("aliases"):
        lines.append(f"  Aliases:  {', '.join(identity['aliases'])}")
    if identity.get("sources"):
        lines.append(f"  Sources:  {', '.join(identity['sources'])}")
    if identity.get("telegram_bio"):
        lines.append(f"  Bio:      {identity['telegram_bio'][:120]}")

    # IPQS extras
    ipqs = (reputation or {}).get("ipqualityscore", {})
    if ipqs.get("name") and ipqs["name"] != identity.get("name"):
        lines.append(f"  IPQS Name: {ipqs['name']}")

    lines += [
        "",
        "📞 NUMBER INFO",
        "─" * 50,
    ]

    if number_info.get("valid"):
        lines += [
            f"  International: {number_info.get('international')}",
            f"  E.164:         {number_info.get('e164')}",
            f"  National:      {number_info.get('national')}",
            f"  Country:       {number_info.get('country')}",
            f"  Region:        {number_info.get('region_code')}",
            f"  Carrier:       {number_info.get('carrier')}",
            f"  Line Type:     {number_info.get('type')}",
            f"  Timezones:     {', '.join(number_info.get('timezones', []))}",
            f"  Valid:         {'✅ Yes' if number_info.get('is_valid') else '❌ No'}",
        ]
        if ipqs:
            lines += [
                f"  City:          {ipqs.get('city') or 'N/A'}",
                f"  Active:        {ipqs.get('active')}",
            ]
    else:
        lines.append(f"  ⚠️ {number_info.get('error', '')}")

    lines += [
        "",
        "🎯 RISK ASSESSMENT",
        "─" * 50,
        f"  Risk Score: {spam_score['score']}/100",
        f"  Risk Level: {spam_score['risk_level']}",
    ]

    if spam_score["flags"]:
        lines.append("\n  🚩 Risk Flags:")
        for f in spam_score["flags"]:
            lines.append(f"    • {f}")
    if spam_score["notes"]:
        lines.append("\n  📝 Notes:")
        for n in spam_score["notes"]:
            lines.append(f"    • {n}")

    # Emails
    lines += [
        "",
        "📧 LINKED EMAILS",
        "─" * 50,
    ]
    all_emails = list(emails or [])
    for em in identity.get("emails_from_id", []):
        all_emails.append({"email": em, "source": "truecaller"})
    if all_emails:
        for em in all_emails:
            line = f"  • {em.get('email')}"
            if em.get("reputation"):
                line += f"  [rep: {em['reputation']}]"
            if em.get("suspicious"):
                line += "  ⚠️ SUSPICIOUS"
            if em.get("references"):
                line += f"  ({em['references']} refs)"
            lines.append(line)
    else:
        lines.append("  No linked emails discovered")

    # Messaging apps
    lines += [
        "",
        "💬 MESSAGING APPS",
        "─" * 50,
    ]
    for app, data in (msg_apps or {}).items():
        if not isinstance(data, dict):
            continue
        if data.get("registered") is True:
            extra = ""
            if data.get("first_name"):
                extra += f" — {data.get('first_name')} {data.get('last_name','') or ''}".rstrip()
            if data.get("username"):
                extra += f" (@{data['username']})"
            badges = []
            if data.get("is_premium"):  badges.append("⭐ PREMIUM")
            if data.get("is_verified"): badges.append("✅ VERIFIED")
            if data.get("is_scam"):     badges.append("🚨 SCAM FLAG")
            if data.get("is_fake"):     badges.append("⚠️ FAKE")
            badge_str = f"  {' '.join(badges)}" if badges else ""

            lines.append(f"  ✅ {app.capitalize():12} REGISTERED{extra}{badge_str}")

            if data.get("bio"):
                lines.append(f"     └─ Bio:       {data['bio'][:100]}")
            if data.get("last_seen"):
                lines.append(f"     └─ Last seen: {data['last_seen']}")
            if data.get("photo_path"):
                lines.append(f"     └─ Photo:     {data['photo_path']}")

        elif data.get("registered") is False:
            lines.append(f"  ❌ {app.capitalize():12} Not registered")
        elif data.get("skipped"):
            lines.append(f"  ⏭️  {app.capitalize():12} {data['skipped']}")
        else:
            lines.append(f"  ❓ {app.capitalize():12} Unknown")

    # Social media
    lines += [
        "",
        "🌐 SOCIAL MEDIA PROFILES",
        "─" * 50,
    ]
    if social:
        for plat, urls in social.items():
            lines.append(f"  [{plat.upper()}]")
            for u in urls[:3]:
                lines.append(f"    • {u}")
    else:
        lines.append("  No social profiles discovered")

    # Breaches
    lines += [
        "",
        "🔓 DATA BREACHES",
        "─" * 50,
    ]
    total_b = sum(len(v) for v in (breaches or {}).values())
    if total_b > 0:
        for src, items in breaches.items():
            if items:
                lines.append(f"  [{src.upper()}] {len(items)} record(s)")
                for b in items[:5]:
                    if src == "hibp":
                        lines.append(f"    • {b.get('name')} ({b.get('breach_date')}) — {b.get('email')}")
                    elif src == "dehashed":
                        bits = []
                        if b.get("email"):    bits.append(f"email: {b['email']}")
                        if b.get("username"): bits.append(f"user: {b['username']}")
                        if b.get("name"):     bits.append(f"name: {b['name']}")
                        lines.append(f"    • {b.get('database')}: {' | '.join(bits)}")
                    elif src == "leakcheck":
                        lines.append(f"    • {b.get('source')}: {b.get('email')}")
    else:
        lines.append("  No breach records found (or no API keys configured)")

    # Spam DBs
    lines += [
        "",
        "🗄️ SPAM DATABASES",
        "─" * 50,
    ]
    if scammer_data:
        for source, data in scammer_data.items():
            lines.append(f"  [{source.upper()}]")
            if isinstance(data, dict):
                for k, v in data.items():
                    if v is not None and v != "":
                        lines.append(f"    {k}: {v}")
    else:
        lines.append("  No database hits")

    # OSINT
    lines += [
        "",
        "🕵️ OSINT FINDINGS",
        "─" * 50,
    ]
    if osint_data.get("google_results"):
        lines.append("  Google:")
        for r in osint_data["google_results"][:3]:
            lines.append(f"    📌 {r.get('title','')}")
            if r.get("snippet"):
                lines.append(f"       {r['snippet'][:120]}")
    if osint_data.get("duckduckgo"):
        lines.append("  DuckDuckGo:")
        for r in osint_data["duckduckgo"][:3]:
            lines.append(f"    • {r[:120]}")
    if not osint_data.get("google_results") and not osint_data.get("duckduckgo"):
        lines.append("  No OSINT mentions")

    # Recommendations
    lines += [
        "",
        "💡 RECOMMENDATIONS",
        "─" * 50,
    ]
    score = spam_score["score"]
    if score >= 70:
        lines += [
            "  🚨 DO NOT answer calls from this number",
            "  🚨 DO NOT provide personal information",
            "  🚨 Block & report to your carrier",
            "  🚨 If money requested — it IS a scam",
        ]
    elif score >= 40:
        lines += [
            "  ⚠️ Exercise caution",
            "  ⚠️ Don't share financial info",
            "  ⚠️ Verify caller's identity independently",
        ]
    elif score >= 20:
        lines += [
            "  ⚡ Some risk indicators present",
            "  ⚡ Be cautious but may be legitimate",
        ]
    else:
        lines += [
            "  ✅ No significant risk indicators",
            "  ✅ Use normal caution",
        ]

    lines += [
        "",
        "📢 REPORT SCAMMERS",
        "─" * 50,
        "  🇺🇸 USA:  reportfraud.ftc.gov",
        "  🇬🇧 UK:   actionfraud.police.uk",
        "  🇿🇦 SA:   saps.gov.za",
        "  🌍 Intl: ic3.gov",
        "",
        border,
        "Generated by JARVIS AI Investigation System",
        border,
    ]

    return "\n".join(lines)


# ═════════════════════════════════════════════
# GUI REPORT VIEWER
# ═════════════════════════════════════════════

def _show_report_gui(report, spam_score, number_info, identity, msg_apps):
    """Truecaller-style GUI report."""
    os.environ["GTK_THEME"]              = "Adwaita"
    os.environ["GLYCIN_DISABLE_SANDBOX"] = "1"
    os.environ["GSK_RENDERER"]           = "cairo"

    if hasattr(os, "geteuid") and os.geteuid() == 0 and _OS == "Linux":
        print(report)
        try:
            path = REPORTS_DIR / f"report_{int(time.time())}.txt"
            path.write_text(report, encoding="utf-8")
            print(f"\n[NumberTracer] 💾 Saved: {path}")
        except Exception:
            pass
        return

    try:
        import tkinter as tk
        from tkinter import scrolledtext

        root = tk.Tk()
        root.title("🔍 JARVIS — Number Investigation")
        root.geometry("900x800")
        root.configure(bg="#0a0a1a")
        root.attributes("-topmost", True)

        # Header
        header = tk.Frame(root, bg="#1a1a2e", pady=15)
        header.pack(fill="x")
        tk.Label(
            header, text="🔍 Number Investigation Report",
            font=("Arial", 18, "bold"), fg="#00d4ff", bg="#1a1a2e",
        ).pack()

        # Identity bar
        id_bar = tk.Frame(root, bg="#0f1f3a", pady=10)
        id_bar.pack(fill="x", padx=10, pady=(5, 0))

        # Try to show profile photo if available
        photo_path = None
        tg = (msg_apps or {}).get("telegram", {})
        if isinstance(tg, dict):
            photo_path = tg.get("photo_path")

        id_inner = tk.Frame(id_bar, bg="#0f1f3a")
        id_inner.pack(fill="x", padx=15)

        if photo_path and os.path.exists(photo_path):
            try:
                from PIL import Image, ImageTk
                img = Image.open(photo_path)
                img.thumbnail((80, 80))
                photo = ImageTk.PhotoImage(img)
                photo_label = tk.Label(id_inner, image=photo, bg="#0f1f3a")
                photo_label.image = photo  # keep reference
                photo_label.pack(side="left", padx=(0, 10))
            except Exception:
                pass

        text_frame = tk.Frame(id_inner, bg="#0f1f3a")
        text_frame.pack(side="left", fill="both", expand=True)

        name = identity.get("name") or "Unknown Identity"
        tk.Label(
            text_frame, text=f"👤 {name}",
            font=("Arial", 16, "bold"), fg="#ffffff", bg="#0f1f3a",
        ).pack(anchor="w")

        if identity.get("aliases"):
            tk.Label(
                text_frame, text=f"Also: {', '.join(identity['aliases'][:3])}",
                font=("Arial", 10, "italic"), fg="#aaaaaa", bg="#0f1f3a",
            ).pack(anchor="w")

        if identity.get("telegram_bio"):
            tk.Label(
                text_frame, text=f"💭 {identity['telegram_bio'][:80]}",
                font=("Arial", 9), fg="#88ccff", bg="#0f1f3a",
                wraplength=600, justify="left",
            ).pack(anchor="w", pady=(3, 0))

        # Score
        score = spam_score["score"]
        color = {
            "RED":    "#ff4444", "ORANGE": "#ff8800",
            "YELLOW": "#ffdd00", "GREEN":  "#00ff88",
        }.get(spam_score["color"], "#ffffff")

        score_frame = tk.Frame(root, bg="#1a1a2e", pady=10)
        score_frame.pack(fill="x", padx=10)

        canvas = tk.Canvas(score_frame, width=100, height=100, bg="#1a1a2e", highlightthickness=0)
        canvas.pack(side="left", padx=20)
        canvas.create_oval(5, 5, 95, 95, fill="#0a0a1a", outline=color, width=4)
        canvas.create_text(50, 45, text=str(score), font=("Arial", 24, "bold"), fill=color)
        canvas.create_text(50, 70, text="/100", font=("Arial", 10), fill="#888888")

        info_frame = tk.Frame(score_frame, bg="#1a1a2e")
        info_frame.pack(side="left", fill="both", expand=True)
        tk.Label(info_frame, text=spam_score["risk_level"], font=("Arial", 14, "bold"), fg=color, bg="#1a1a2e").pack(anchor="w")
        tk.Label(info_frame, text=f"📞 {number_info.get('international','')}", font=("Arial", 12), fg="#ffffff", bg="#1a1a2e").pack(anchor="w")
        tk.Label(
            info_frame,
            text=f"🌍 {number_info.get('country','')}  |  📡 {number_info.get('carrier','')}  |  📲 {number_info.get('type','')}",
            font=("Arial", 10), fg="#888888", bg="#1a1a2e",
        ).pack(anchor="w")

        # Messaging app badges
        if msg_apps:
            apps_frame = tk.Frame(root, bg="#0a0a1a", pady=5)
            apps_frame.pack(fill="x", padx=15)
            for app, data in msg_apps.items():
                if not isinstance(data, dict):
                    continue
                if data.get("registered") is True:
                    label = f"✅ {app.capitalize()}"
                    if data.get("is_scam"):
                        label += " 🚨"
                    if data.get("is_premium"):
                        label += " ⭐"
                    tk.Label(
                        apps_frame, text=label,
                        font=("Arial", 10, "bold"), fg="#00ff88", bg="#0a0a1a",
                        padx=8,
                    ).pack(side="left", padx=3)
                elif data.get("registered") is False:
                    tk.Label(
                        apps_frame, text=f"❌ {app.capitalize()}",
                        font=("Arial", 10), fg="#666666", bg="#0a0a1a",
                        padx=8,
                    ).pack(side="left", padx=3)

        # Flags
        if spam_score["flags"]:
            flags_frame = tk.Frame(root, bg="#0a0a1a", pady=5)
            flags_frame.pack(fill="x", padx=10)
            for flag in spam_score["flags"][:4]:
                tk.Label(
                    flags_frame, text=flag, font=("Arial", 10),
                    fg="#ffaa00", bg="#0a0a1a", anchor="w",
                ).pack(fill="x", padx=10)

        # Report
        rep_frame = tk.Frame(root, bg="#0a0a1a")
        rep_frame.pack(fill="both", expand=True, padx=10, pady=5)
        text_area = scrolledtext.ScrolledText(
            rep_frame, font=("Courier", 9),
            bg="#0d0d1a", fg="#cccccc",
            insertbackground="#ffffff", relief="flat",
            padx=10, pady=10,
        )
        text_area.pack(fill="both", expand=True)
        text_area.insert("1.0", report)
        text_area.config(state="disabled")

        # Buttons
        btn_frame = tk.Frame(root, bg="#0a0a1a", pady=10)
        btn_frame.pack(fill="x")

        def save_report():
            path = REPORTS_DIR / f"report_{int(time.time())}.txt"
            path.write_text(report, encoding="utf-8")
            try:
                import subprocess
                subprocess.Popen(["xdg-open", str(path)])
            except Exception:
                pass
            save_btn.config(text="✅ Saved!")

        save_btn = tk.Button(
            btn_frame, text="💾 Save Report", font=("Arial", 10),
            bg="#1a1a2e", fg="#ffffff", relief="flat",
            padx=15, pady=6, command=save_report,
        )
        save_btn.pack(side="left", padx=10)

        def copy_report():
            root.clipboard_clear()
            root.clipboard_append(report)
            copy_btn.config(text="✅ Copied!")
            root.after(2000, lambda: copy_btn.config(text="📋 Copy Report"))

        copy_btn = tk.Button(
            btn_frame, text="📋 Copy Report", font=("Arial", 10),
            bg="#1a1a2e", fg="#ffffff", relief="flat",
            padx=15, pady=6, command=copy_report,
        )
        copy_btn.pack(side="left", padx=5)

        tk.Button(
            btn_frame, text="❌ Close", font=("Arial", 10),
            bg="#551a1a", fg="#ffffff", relief="flat",
            padx=15, pady=6, command=root.destroy,
        ).pack(side="right", padx=10)

        root.mainloop()

    except Exception as e:
        print(f"[NumberTracer] GUI error: {e}")
        print(report)


# ═════════════════════════════════════════════
# MAIN AGENT
# ═════════════════════════════════════════════

def number_tracer(parameters: dict, player=None, speak=None) -> str:
    """
    Actions:
        trace    — Full Truecaller-grade investigation
        validate — Just parse the number
        spam     — Quick spam check
        identity — Just look up the name
        report   — Same as trace
        lookup   — Reverse phone lookup
    """
    params = parameters or {}
    action = params.get("action", "trace").lower().strip()
    phone  = (params.get("phone") or params.get("number") or "").strip()

    if not phone:
        return "Please provide a phone number, sir."

    if player:
        player.write_log(f"[NumberTracer] Investigating: {phone}")
    print(f"[NumberTracer] 🔍 {phone}")

    # Validate
    if action == "validate":
        info = _parse_number(phone)
        if info.get("valid"):
            result = (
                f"Number: {info.get('international')}\n"
                f"Country: {info.get('country')}\n"
                f"Carrier: {info.get('carrier')}\n"
                f"Type: {info.get('type')}"
            )
        else:
            result = f"Invalid: {info.get('error')}"
        if speak:
            speak(result[:200])
        return result

    # Identity only
    if action == "identity":
        info = _parse_number(phone)
        if speak:
            speak(f"Looking up the identity of {phone}, sir.")
        ident = _lookup_identity(info.get("e164", phone), info.get("region_code", "us"))
        if ident.get("name"):
            result = f"Name: {ident['name']}"
            if ident.get("aliases"):
                result += f"\nAliases: {', '.join(ident['aliases'])}"
            result += f"\nSources: {', '.join(ident['sources'])}"
            if ident.get("telegram_bio"):
                result += f"\nBio: {ident['telegram_bio']}"
        else:
            result = "No identity found, sir. Configure Telegram/Truecaller/OpenCNAM API for better results."
        if speak:
            speak(result[:200])
        return result

    # Quick spam
    if action == "spam":
        if speak:
            speak(f"Checking {phone} against spam databases.")
        info     = _parse_number(phone)
        scammer  = _check_scammer_databases(info.get("e164", phone))
        rep      = _check_reputation(info.get("e164", phone))
        score    = _calculate_spam_score(info, scammer, {}, reputation=rep)
        result   = (
            f"Spam check for {phone}:\n"
            f"Risk Score: {score['score']}/100\n"
            f"Risk Level: {score['risk_level']}"
        )
        if score["flags"]:
            result += "\n\nFlags:\n" + "\n".join(f"  • {f}" for f in score["flags"])
        if speak:
            speak(f"Risk score is {score['score']} out of 100. {score['risk_level']}")
        return result

    # Full trace
    if action in ("trace", "investigate", "report", "lookup"):
        if speak:
            speak(f"Running full Truecaller-grade investigation on {phone}, sir.")

        # Step 1: parse
        if player: player.write_log("[NumberTracer] 1/7 Parsing...")
        info   = _parse_number(phone)
        e164   = info.get("e164", phone)
        region = info.get("region_code", "us")

        if player: player.write_log("[NumberTracer] 2/7 Identity lookup...")
        if player: player.write_log("[NumberTracer] 3/7 Email discovery...")
        if player: player.write_log("[NumberTracer] 4/7 Messaging apps...")
        if player: player.write_log("[NumberTracer] 5/7 Social media...")
        if player: player.write_log("[NumberTracer] 6/7 Breach + reputation...")
        if player: player.write_log("[NumberTracer] 7/7 OSINT + spam DBs...")

        identity     = {}
        emails       = []
        msg_apps     = {}
        social       = {}
        breaches     = {}
        reputation   = {}
        scammer_data = {}
        osint_data   = {}

        # Run in parallel for speed
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {
                "identity":   ex.submit(_lookup_identity, e164, region),
                "msg_apps":   ex.submit(_check_messaging_apps, e164),
                "social":     ex.submit(_discover_social, phone, e164),
                "reputation": ex.submit(_check_reputation, e164),
                "scammer":    ex.submit(_check_scammer_databases, e164),
                "osint":      ex.submit(_osint_search, phone, info),
            }
            for key, fut in futures.items():
                try:
                    res = fut.result(timeout=30)
                    if   key == "identity":   identity     = res
                    elif key == "msg_apps":   msg_apps     = res
                    elif key == "social":     social       = res
                    elif key == "reputation": reputation   = res
                    elif key == "scammer":    scammer_data = res
                    elif key == "osint":      osint_data   = res
                except Exception as e:
                    print(f"[NumberTracer] {key} failed: {e}")

        # Email discovery (uses name if found)
        try:
            emails = _discover_emails(phone, e164, identity.get("name"))
        except Exception as e:
            print(f"[NumberTracer] email discovery failed: {e}")

        # Breach lookup (uses emails)
        try:
            breaches = _check_breaches(e164, emails)
        except Exception as e:
            print(f"[NumberTracer] breach lookup failed: {e}")

        # Score
        spam_score = _calculate_spam_score(
            info, scammer_data, osint_data,
            breaches=breaches, reputation=reputation, msg_apps=msg_apps,
        )
        print(f"[NumberTracer] 🎯 Score: {spam_score['score']}/100")

        # Report
        report = _generate_report(
            phone, info, identity, emails, msg_apps, social,
            breaches, reputation, scammer_data, osint_data, spam_score,
        )

        report_path = REPORTS_DIR / f"trace_{re.sub(r'[^d]', '', phone)}_{int(time.time())}.txt"
        report_path.write_text(report, encoding="utf-8")
        print(f"[NumberTracer] 💾 Saved: {report_path}")

        if player:
            player.write_log(f"[NumberTracer] {spam_score['risk_level']}")

        if speak:
            name_part = ""
            if identity.get("name"):
                name_part = f" The owner appears to be {identity['name']}."
            speak(
                f"Investigation complete, sir.{name_part} "
                f"Risk score is {spam_score['score']} out of 100. "
                f"{spam_score['risk_level']}. Opening detailed report."
            )

        # GUI
        import threading
        threading.Thread(
            target=_show_report_gui,
            args=(report, spam_score, info, identity, msg_apps),
            daemon=True,
        ).start()

        summary = (
            f"Investigation complete.\n"
            f"Name: {identity.get('name') or 'Unknown'}\n"
            f"Number: {info.get('international', phone)}\n"
            f"Country: {info.get('country', 'Unknown')}\n"
            f"Carrier: {info.get('carrier', 'Unknown')}\n"
            f"Type: {info.get('type', 'Unknown')}\n"
            f"Risk Score: {spam_score['score']}/100\n"
            f"Risk Level: {spam_score['risk_level']}\n"
            f"Emails: {len(emails)}\n"
            f"Social Profiles: {sum(len(v) for v in social.values())}\n"
            f"Breach Records: {sum(len(v) for v in breaches.values())}\n"
            f"Report saved: {report_path}"
        )
        return summary

    return f"Unknown action: {action}"