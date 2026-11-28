"""
Flight Manager for JARVIS — multi-site cheap-flight meta-search
───────────────────────────────────────────────────────────────
Searches Kayak, Google Flights, Skyscanner, Momondo, Expedia, Kiwi,
Booking.com and Trip.com from one command, then ranks what it finds.

  Search     search (one site), compare (all sites), links (deep links only)
  Flexible   flexible / calendar — cheapest day in a ±N-day window
  Tracking   watch, unwatch, watches, check_watches (price-drop alerts)
  Insight    report (markdown), advice (when to buy), airports, status

How it works
────────────
Each site gets a **deep link** built from your route/dates/cabin/party, opened
in a *visible* browser (actions/browser_control.py) so you can watch it and
finish anything yourself. Page text is parsed for prices, then offers are
scored on price, stops, duration and your airline/baggage preferences.

`deep=true` additionally hands the Google Flights page to the existing
actions/flight_finder.py, which uses Gemini for richer parsing.

Honest limits
─────────────
* Deep links follow each site's published URL pattern. They are built and
  unit-tested offline; they were NOT verified against the live sites from the
  build sandbox (no outbound access to those hosts). If a site changes its
  URL scheme, the link may land on its homepage — the search still opens.
* Text parsing is best-effort and assumes an English locale. Sites render
  results with JavaScript and change markup often, so `compare` may return
  fewer offers than the page shows. The deep links are the reliable part.
* No FX conversion is invented: prices are reported in the currency the site
  returns, and `currency` is passed through where the site supports it.

Safety
──────
* **No booking or payment automation.** `book` only opens the offer's site in
  a visible browser for YOU to complete. Card details are never entered.
* Searches are sequential, bounded (max 8 sites) and rate-limited.
* Price watches are local files; nothing is sent anywhere.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────

CONFIRM_TEXT = "FLIGHT CONFIRMED"
WATCH_PATH = Path("memory") / "flight_watches.json"
STATE_PATH = Path("memory") / "flight_state.json"
REPORT_DIR = Path("reports")
CONFIG_PATH = Path("config") / "flights.json"

SITES = ("kayak", "google", "skyscanner", "momondo", "expedia", "kiwi",
         "booking", "trip")
MAX_SITES = 8
CABINS = ("economy", "premium", "business", "first")
STOP_OPTIONS = ("any", "nonstop", "1stop")
DEFAULT_CURRENCY = "USD"

DAILY_SEARCH_CAP = 60
MIN_SEARCH_INTERVAL_S = 3
SITE_DELAY_S = 4.0
MAX_FLEX_DAYS = 7

# City / airport aliases → IATA. Extend freely; unknown codes pass through.
AIRPORTS = {
    "nairobi": "NBO", "jkia": "NBO", "nbo": "NBO", "wilson": "WIL",
    "mombasa": "MBA", "kisumu": "KIS", "eldoret": "EDL",
    "dubai": "DXB", "abu dhabi": "AUH", "doha": "DOH", "riyadh": "RUH",
    "jeddah": "JED", "muscat": "MCT", "kuwait": "KWI", "bahrain": "BAH",
    "london": "LHR", "heathrow": "LHR", "gatwick": "LGW", "stansted": "STN",
    "manchester": "MAN", "edinburgh": "EDI", "dublin": "DUB",
    "paris": "CDG", "orly": "ORY", "amsterdam": "AMS", "brussels": "BRU",
    "frankfurt": "FRA", "munich": "MUC", "berlin": "BER", "zurich": "ZRH",
    "geneva": "GVA", "vienna": "VIE", "rome": "FCO", "milan": "MXP",
    "madrid": "MAD", "barcelona": "BCN", "lisbon": "LIS", "athens": "ATH",
    "istanbul": "IST", "ankara": "ESB", "cairo": "CAI", "casablanca": "CMN",
    "addis ababa": "ADD", "addis": "ADD", "kigali": "KGL", "kampala": "EBB",
    "dar es salaam": "DAR", "dar": "DAR", "zanzibar": "ZNZ", "arusha": "JRO",
    "kilimanjaro": "JRO", "johannesburg": "JNB", "joburg": "JNB",
    "cape town": "CPT", "durban": "DUR", "lagos": "LOS", "abuja": "ABV",
    "accra": "ACC", "dakar": "DSS", "lusaka": "LUN", "harare": "HRE",
    "new york": "JFK", "nyc": "JFK", "newark": "EWR", "boston": "BOS",
    "washington": "IAD", "atlanta": "ATL", "miami": "MIA", "chicago": "ORD",
    "toronto": "YYZ", "vancouver": "YVR", "los angeles": "LAX", "la": "LAX",
    "san francisco": "SFO", "seattle": "SEA", "dallas": "DFW", "houston": "IAH",
    "mumbai": "BOM", "delhi": "DEL", "bangalore": "BLR", "karachi": "KHI",
    "bangkok": "BKK", "singapore": "SIN", "kuala lumpur": "KUL",
    "hong kong": "HKG", "tokyo": "NRT", "osaka": "KIX", "seoul": "ICN",
    "beijing": "PEK", "shanghai": "PVG", "guangzhou": "CAN",
    "sydney": "SYD", "melbourne": "MEL", "auckland": "AKL",
}

AIRLINES = (
    "Kenya Airways", "Emirates", "Qatar Airways", "Etihad", "Turkish Airlines",
    "Ethiopian Airlines", "RwandAir", "British Airways", "KLM", "Air France",
    "Lufthansa", "Swiss", "Brussels Airlines", "EgyptAir", "South African",
    "Precision Air", "Flydubai", "Air Arabia", "Saudia", "Oman Air",
    "Delta", "United", "American Airlines", "Air India", "IndiGo",
    "Singapore Airlines", "Cathay Pacific", "Thai Airways", "Qantas",
)

CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "KES": "KSh",
                    "AED": "AED", "INR": "₹", "ZAR": "R", "AUD": "A$",
                    "CAD": "C$", "JPY": "¥"}


# ── Delegates (lazy, monkeypatchable) ───────────────────────────────────────

def _browser(params: dict, player=None) -> str:
    from actions.browser_control import browser_control
    return browser_control(parameters=params, player=player)


def _deep_parse(origin, destination, date, return_date, passengers, cabin,
                player=None, speak=None) -> str:
    from actions.flight_finder import flight_finder
    return flight_finder({"origin": origin, "destination": destination,
                          "date": date, "return_date": return_date or "",
                          "passengers": passengers, "cabin": cabin},
                         player=player, speak=speak)


def load_prefs(path=None) -> dict:
    """Optional defaults from config/flights.json (see the .example file)."""
    cfg = {"home_airport": "", "currency": DEFAULT_CURRENCY,
           "preferred_airlines": [], "require_bag": False}
    p = Path(path) if path else CONFIG_PATH
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in cfg})
    except Exception:
        pass
    return cfg


def _log(player, msg):
    try:
        if player:
            player.write_log(msg)
    except Exception:
        pass


def _say(speak, msg):
    try:
        if speak:
            speak(msg)
    except Exception:
        pass


# ── Airports ────────────────────────────────────────────────────────────────

def resolve_airport(query: str) -> str:
    """'Nairobi' / 'JKIA' / 'nbo' -> 'NBO'. Unknown 3-letter codes pass through."""
    q = str(query or "").strip().lower()
    if not q:
        return ""
    if q in AIRPORTS:
        return AIRPORTS[q]
    code = re.sub(r"[^a-z]", "", q)
    if len(code) == 3:
        return code.upper()
    # Try a loose contains match on city names ("nairobi kenya").
    for name, iata in AIRPORTS.items():
        if len(name) > 3 and name in q:
            return iata
    return ""


def airport_suggestions(query: str, limit: int = 6) -> list[str]:
    q = str(query or "").strip().lower()
    if not q:
        return []
    hits = [f"{name.title()} ({iata})" for name, iata in AIRPORTS.items()
            if q in name and len(name) > 3]
    seen, out = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out[:limit]


# ── Dates ──────────────────────────────────────────────────────────────────

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday")
_MONTHS = ("january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december")


def parse_date(raw, today: datetime | None = None) -> str:
    """Parse ISO, DD/MM/YYYY, 'tomorrow', 'next friday', 'in 3 weeks',
    '+10d', 'Dec 15', '15 December 2026'. Returns '' if unparseable."""
    if isinstance(raw, datetime):
        return raw.strftime("%Y-%m-%d")
    today = today or datetime.now()
    today = today.replace(hour=0, minute=0, second=0, microsecond=0)
    s = str(raw or "").strip().lower()
    if not s:
        return ""

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            return ""

    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    if s in ("today", "tonight"):
        return today.strftime("%Y-%m-%d")
    if s == "tomorrow":
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    if s in ("yesterday",):
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")

    m = re.fullmatch(r"\+?(\d+)\s*d(?:ays?)?", s)
    if m:
        return (today + timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")
    m = re.fullmatch(r"in\s+(\d+)\s+days?", s)
    if m:
        return (today + timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")
    m = re.fullmatch(r"in\s+(\d+)\s+weeks?", s)
    if m:
        return (today + timedelta(weeks=int(m.group(1)))).strftime("%Y-%m-%d")
    m = re.fullmatch(r"in\s+(\d+)\s+months?", s)
    if m:
        return (today + timedelta(days=30 * int(m.group(1)))).strftime("%Y-%m-%d")

    m = re.fullmatch(r"(?:next\s+|this\s+)?(" + "|".join(_WEEKDAYS) + r")", s)
    if m:
        target = _WEEKDAYS.index(m.group(1))
        delta = (target - today.weekday()) % 7
        if delta == 0 or s.startswith("next "):
            delta += 7
        return (today + timedelta(days=delta)).strftime("%Y-%m-%d")

    # 'dec 15' / 'december 15' / '15 dec'
    for i, name in enumerate(_MONTHS, 1):
        short = name[:3]
        m = re.fullmatch(rf"(?:{name}|{short})\.?\s+(\d{{1,2}})(?:\s+(\d{{4}}))?", s)
        if not m:
            m2 = re.fullmatch(rf"(\d{{1,2}})\s+(?:{name}|{short})\.?(?:\s+(\d{{4}}))?", s)
            if m2:
                day, year = int(m2.group(1)), m2.group(2)
            else:
                continue
        else:
            day, year = int(m.group(1)), m.group(2)
        year = int(year) if year else today.year
        try:
            cand = datetime(year, i, day)
        except ValueError:
            return ""
        if not year or (cand < today and not re.search(r"\d{4}", s)):
            cand = datetime(today.year + 1, i, day)
        return cand.strftime("%Y-%m-%d")
    return ""


def date_grid(center: str, flex_days: int = 3) -> list[str]:
    """Dates within ±flex_days of center (inclusive), sorted."""
    try:
        base = datetime.strptime(center, "%Y-%m-%d")
    except (ValueError, TypeError):
        return []
    n = max(0, min(int(flex_days), MAX_FLEX_DAYS))
    return [(base + timedelta(days=d)).strftime("%Y-%m-%d")
            for d in range(-n, n + 1)]


def days_until(date: str, today: datetime | None = None) -> int:
    today = (today or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        return (datetime.strptime(date, "%Y-%m-%d") - today).days
    except (ValueError, TypeError):
        return 0


# ── Search validation ───────────────────────────────────────────────────────

def build_search(params: dict, today: datetime | None = None) -> dict:
    """Normalise and validate a search request. Returns {ok, ..., errors}."""
    errors = []
    origin = resolve_airport(params.get("origin", ""))
    destination = resolve_airport(params.get("destination", ""))
    if not origin:
        errors.append(f"Unknown origin '{params.get('origin', '')}'. Try a city or IATA code.")
    if not destination:
        errors.append(f"Unknown destination '{params.get('destination', '')}'.")
    if origin and destination and origin == destination:
        errors.append("Origin and destination are the same airport.")

    depart = parse_date(params.get("date") or params.get("depart"), today)
    if not depart:
        errors.append("A departure date is required (e.g. 2026-12-15, 'next friday', 'in 3 weeks').")
    ret = parse_date(params.get("return_date") or params.get("return"), today)
    if (params.get("return_date") or params.get("return")) and not ret:
        errors.append("Could not understand the return date.")
    if depart and ret and ret < depart:
        errors.append("Return date is before the departure date.")

    trip = str(params.get("trip", "")).lower().strip()
    if not trip:
        trip = "roundtrip" if ret else "oneway"
    if trip not in ("oneway", "roundtrip"):
        errors.append("trip must be 'oneway' or 'roundtrip'.")
    if trip == "roundtrip" and not ret:
        errors.append("A round trip needs a return date (or use trip='oneway').")

    try:
        passengers = int(params.get("passengers", 1))
    except (TypeError, ValueError):
        passengers = 0
    if not 1 <= passengers <= 9:
        errors.append("Passengers must be between 1 and 9.")

    cabin = str(params.get("cabin", "economy")).lower().strip()
    if cabin in ("premium economy", "premiumeconomy", "premium_economy"):
        cabin = "premium"
    if cabin not in CABINS:
        errors.append(f"cabin must be one of {', '.join(CABINS)}.")

    stops = str(params.get("stops", "any")).lower().strip()
    if stops in ("direct", "non-stop", "0"):
        stops = "nonstop"
    if stops in ("1", "one", "max1"):
        stops = "1stop"
    if stops not in STOP_OPTIONS:
        errors.append(f"stops must be one of {', '.join(STOP_OPTIONS)}.")

    budget = params.get("max_price", params.get("budget"))
    try:
        budget = float(budget) if budget not in (None, "") else 0.0
    except (TypeError, ValueError):
        errors.append("max_price must be a number.")
        budget = 0.0
    if budget < 0:
        errors.append("max_price cannot be negative.")

    currency = str(params.get("currency", DEFAULT_CURRENCY)).upper().strip()[:3]
    if not re.fullmatch(r"[A-Z]{3}", currency or ""):
        currency = DEFAULT_CURRENCY

    return {"ok": not errors, "errors": errors, "origin": origin,
            "destination": destination, "depart": depart, "return": ret,
            "trip": trip, "passengers": passengers, "cabin": cabin,
            "stops": stops, "max_price": budget, "currency": currency}


# ── Deep links ──────────────────────────────────────────────────────────────

def _site_list(raw) -> list[str]:
    if raw is None or str(raw).strip().lower() in ("", "all", "default"):
        return list(SITES)
    items = raw if isinstance(raw, (list, tuple)) else re.split(r"[,\s]+", str(raw))
    out, seen = [], set()
    for s in items:
        k = str(s or "").strip().lower()
        k = {"google flights": "google", "googleflights": "google",
             "booking.com": "booking", "trip.com": "trip",
             "skyscanner.net": "skyscanner"}.get(k, k)
        if k in SITES and k not in seen:
            seen.add(k)
            out.append(k)
    return out[:MAX_SITES] or list(SITES)


def build_url(site: str, s: dict) -> str:
    """Deep link for one site, following that site's published URL pattern."""
    o, d = s["origin"], s["destination"]
    dep, ret = s["depart"], s.get("return") or ""
    pax, cabin, cur = s["passengers"], s["cabin"], s["currency"]
    rt = s["trip"] == "roundtrip" and bool(ret)
    stops_q = {"nonstop": "&fs=stops=0", "1stop": "&fs=stops=~1"}.get(s["stops"], "")

    if site == "kayak":
        path = f"{o}-{d}/{dep}" + (f"/{ret}" if rt else "")
        if pax > 1 or cabin != "economy":
            path += f"/{pax}adults" + (f"/{cabin}" if cabin != "economy" else "")
        return f"https://www.kayak.com/flights/{path}?sort=price_a{stops_q}"

    if site == "momondo":
        path = f"{o}-{d}/{dep}" + (f"/{ret}" if rt else "")
        return f"https://www.momondo.com/flight-search/{path}?sort=price_a{stops_q}"

    if site == "google":
        q = f"Flights from {o} to {d} on {dep}"
        if rt:
            q += f" through {ret}"
        if cabin != "economy":
            q += f" {cabin} class"
        if s["stops"] == "nonstop":
            q += " nonstop"
        from urllib.parse import quote_plus
        return (f"https://www.google.com/travel/flights?q={quote_plus(q)}"
                f"&curr={cur}&hl=en")

    if site == "skyscanner":
        yy = lambda x: datetime.strptime(x, "%Y-%m-%d").strftime("%y%m%d")
        cabin_map = {"economy": "economy", "premium": "premiumeconomy",
                     "business": "business", "first": "first"}
        path = f"{o.lower()}/{d.lower()}/{yy(dep)}/" + (f"{yy(ret)}/" if rt else "")
        return (f"https://www.skyscanner.net/transport/flights/{path}"
                f"?adultsv2={pax}&cabinclass={cabin_map[cabin]}"
                f"&rtn={'1' if rt else '0'}&preferdirects="
                f"{'true' if s['stops'] == 'nonstop' else 'false'}&currency={cur}")

    if site == "expedia":
        from urllib.parse import quote
        md = lambda x: datetime.strptime(x, "%Y-%m-%d").strftime("%m/%d/%Y")
        leg1 = f"from:{o},to:{d},departure:{md(dep)}TANYT"
        url = (f"https://www.expedia.com/Flights-Search?trip="
               f"{'roundtrip' if rt else 'oneway'}&leg1={quote(leg1, safe=':,/')}")
        if rt:
            leg2 = f"from:{d},to:{o},departure:{md(ret)}TANYT"
            url += f"&leg2={quote(leg2, safe=':,/')}"
        cab = {"economy": "economy", "premium": "premium",
               "business": "business", "first": "first"}[cabin]
        return url + f"&passengers=adults:{pax}&options=cabinclass:{cab}&mode=search"

    if site == "kiwi":
        path = f"{o.lower()}-{d.lower()}/{dep}" + (f"/{ret}" if rt else "")
        return (f"https://www.kiwi.com/en/search/results/{path}"
                f"?adults={pax}&cabinClass={cabin.upper()}&currency={cur}")

    if site == "booking":
        cab = {"economy": "ECONOMY", "premium": "PREMIUM_ECONOMY",
               "business": "BUSINESS", "first": "FIRST"}[cabin]
        url = (f"https://flights.booking.com/flights/{o}-{d}/"
               f"?type={'ROUNDTRIP' if rt else 'ONEWAY'}&adults={pax}"
               f"&cabinClass={cab}&depart={dep}&currency={cur}")
        if rt:
            url += f"&return={ret}"
        return url

    if site == "trip":
        cls = {"economy": "y", "premium": "s", "business": "c", "first": "f"}[cabin]
        url = (f"https://www.trip.com/flights/showfarefirst?dcity={o.lower()}"
               f"&acity={d.lower()}&ddate={dep}"
               f"&triptype={'rt' if rt else 'ow'}&class={cls}&quantity={pax}")
        if rt:
            url += f"&rdate={ret}"
        return url

    return ""


def all_urls(s: dict, sites=None) -> dict:
    return {site: build_url(site, s) for site in _site_list(sites)}


# ── Price / offer parsing ───────────────────────────────────────────────────

# Bare "R" (ZAR) must not match inside words — "5 hr 30 min" otherwise reads
# as a price of 30. Symbols are unambiguous; ISO codes need a word boundary.
_PRICE_RE = re.compile(
    r"(?:\b(?:USD|EUR|GBP|KES|KSh|AED|INR|ZAR|AUD|CAD|JPY)\s?"
    r"|[\$€£₹¥]\s?"
    r"|(?<![A-Za-z])R\s?)"
    r"(\d{1,3}(?:[,\s]\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)",
    re.IGNORECASE)
# Longest alternatives first: "hr" must not be matched as "h" (which would
# drop the minutes and turn 5 hr 30 min into 5h).
_DURATION_RE = re.compile(
    r"(\d{1,2})\s*(?:hours|hour|hrs|hr|h)\s*"
    r"(?:(\d{1,2})\s*(?:minutes|minute|mins|min|m)\b)?",
    re.IGNORECASE)
_STOPS_RE = re.compile(r"(\d)\s*\+?\s*stop", re.IGNORECASE)


def parse_prices(text: str) -> list[float]:
    """All currency amounts found in page text (English locale assumed)."""
    out = []
    for m in _PRICE_RE.finditer(str(text or "")):
        raw = m.group(1).replace(",", "").replace(" ", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        if val > 0:
            out.append(val)
    return out


def _duration_minutes(text: str) -> int:
    m = _DURATION_RE.search(text)
    if not m:
        return 0
    return int(m.group(1)) * 60 + int(m.group(2) or 0)


def _stops_count(text: str) -> int:
    low = text.lower()
    if "nonstop" in low or "non-stop" in low or "direct" in low:
        return 0
    m = _STOPS_RE.search(low)
    return int(m.group(1)) if m else -1


def extract_offers(text: str, site: str = "", currency: str = DEFAULT_CURRENCY,
                   limit: int = 20) -> list[dict]:
    """Best-effort offer extraction: each price line plus its context window."""
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    offers, seen = [], set()
    last_price_idx = -1
    for i, line in enumerate(lines):
        prices = parse_prices(line)
        if not prices:
            continue
        # Never look back past the previous price line, or one offer's
        # "Nonstop" / duration leaks into the next offer's context.
        start = max(0, last_price_idx + 1, i - 6)
        last_price_idx = i
        context = " | ".join(lines[start:i + 1])
        airline = next((a for a in AIRLINES if a.lower() in context.lower()), "")
        stops = _stops_count(context)
        minutes = _duration_minutes(context)
        price = min(prices)
        key = (price, airline, stops, minutes)
        if key in seen:
            continue
        seen.add(key)
        offers.append({"site": site, "price": price, "currency": currency,
                       "airline": airline, "stops": stops,
                       "duration_min": minutes, "raw": context[:220]})
        if len(offers) >= limit:
            break
    return offers


# ── Ranking ────────────────────────────────────────────────────────────────

def score_offer(offer: dict, prefs: dict | None = None) -> float:
    """Lower is better. Price dominates; stops/time/preference adjust it."""
    prefs = prefs or {}
    price = float(offer.get("price", 0) or 0)
    score = price
    stops = int(offer.get("stops", -1))
    if stops > 0:
        score += stops * float(prefs.get("stop_penalty", 60))
    minutes = int(offer.get("duration_min", 0) or 0)
    if minutes:
        hours = minutes / 60.0
        baseline = float(prefs.get("baseline_hours", 6))
        if hours > baseline:
            score += (hours - baseline) * float(prefs.get("hour_penalty", 12))
    preferred = [a.lower() for a in (prefs.get("airlines") or [])]
    airline = str(offer.get("airline", "")).lower()
    if preferred and airline:
        if any(p in airline for p in preferred):
            score -= float(prefs.get("airline_bonus", 40))
        else:
            score += float(prefs.get("airline_penalty", 25))
    if prefs.get("require_bag") and not offer.get("bag_included", False):
        score += float(prefs.get("bag_penalty", 70))
    return round(score, 2)


def rank_offers(offers: list[dict], prefs: dict | None = None,
                max_price: float = 0) -> list[dict]:
    out = []
    for o in offers or []:
        if max_price and float(o.get("price", 0)) > max_price:
            continue
        item = dict(o)
        item["score"] = score_offer(o, prefs)
        out.append(item)
    out.sort(key=lambda x: (x["score"], x.get("price", 0)))
    return out


def cheapest_by_date(results: dict) -> list[dict]:
    """results: {date: [offers]} -> [{date, price, site, airline}] sorted by price."""
    rows = []
    for date, offers in (results or {}).items():
        valid = [o for o in offers if float(o.get("price", 0)) > 0]
        if not valid:
            continue
        best = min(valid, key=lambda o: float(o["price"]))
        rows.append({"date": date, "price": float(best["price"]),
                     "site": best.get("site", ""), "airline": best.get("airline", "")})
    rows.sort(key=lambda r: (r["price"], r["date"]))
    return rows


def buying_advice(days: int) -> str:
    """Heuristic guidance — not a price prediction."""
    if days < 0:
        return "That date is in the past."
    if days <= 7:
        return ("⚠️ Under a week out — fares usually climb sharply. Book now if the "
                "price works; waiting rarely helps this close in.")
    if days <= 21:
        return ("Getting close. Prices tend to rise from here; a good fare now is "
                "usually worth taking.")
    if days <= 60:
        return ("✅ This is often the sweet spot for international routes (roughly "
                "3–8 weeks out). Set a price watch and pounce on a drop.")
    if days <= 120:
        return ("Plenty of time. Start a watch now and let it track fares — don't "
                "rush, but avoid the last three weeks.")
    return ("Very early. Airlines often haven't released their cheapest inventory "
            "yet. Watch it and re-check around 2–3 months before departure.")


# ── Persistence: watches + rate limit ───────────────────────────────────────

class PriceWatch:
    """Local price watchlist with history and drop detection."""

    def __init__(self, path=None):
        self.path = Path(path) if path else WATCH_PATH
        self.items = self._load()

    def _load(self) -> list:
        try:
            if self.path.exists():
                d = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(d, list):
                    return d
        except Exception:
            pass
        return []

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.items, indent=2), encoding="utf-8")
        except Exception:
            pass

    def add(self, search: dict, target: float = 0, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        for w in self.items:
            if (w["origin"] == search["origin"] and w["destination"] == search["destination"]
                    and w["depart"] == search["depart"] and w.get("return") == search.get("return")):
                if target:
                    w["target"] = float(target)
                    self.save()
                return {"ok": True, "item": w, "existing": True}
        item = {"id": uuid.uuid4().hex[:8], "origin": search["origin"],
                "destination": search["destination"], "depart": search["depart"],
                "return": search.get("return", ""), "trip": search["trip"],
                "passengers": search["passengers"], "cabin": search["cabin"],
                "currency": search["currency"], "target": float(target or 0),
                "created": now, "history": [], "last_price": 0.0}
        self.items.append(item)
        self.save()
        return {"ok": True, "item": item, "existing": False}

    def list(self) -> list:
        return list(self.items)

    def get(self, wid: str) -> dict | None:
        return next((w for w in self.items if w.get("id") == wid), None)

    def remove(self, wid: str) -> bool:
        before = len(self.items)
        self.items = [w for w in self.items if w.get("id") != wid]
        if len(self.items) < before:
            self.save()
            return True
        return False

    def record(self, wid: str, price: float, site: str = "",
               now: float | None = None) -> dict:
        """Append a price point; report drop/rise vs previous and target hit."""
        now = time.time() if now is None else now
        w = self.get(wid)
        if not w:
            return {"ok": False, "error": f"No watch '{wid}'."}
        price = float(price)
        prev = float(w.get("last_price") or 0)
        w["history"].append({"t": now, "price": price, "site": site})
        w["history"] = w["history"][-60:]
        w["last_price"] = price
        self.save()
        drop = round(prev - price, 2) if prev else 0.0
        target = float(w.get("target") or 0)
        return {"ok": True, "watch": w, "previous": prev, "drop": drop,
                "dropped": bool(prev and price < prev),
                "target_hit": bool(target and price <= target)}

    def render(self) -> str:
        if not self.items:
            return "No flight price watches. Say 'watch flights NBO to DXB on 2026-12-15'."
        lines = []
        for w in self.items:
            route = f"{w['origin']}→{w['destination']} {w['depart']}"
            if w.get("return"):
                route += f"–{w['return']}"
            last = f"{w['currency']} {w['last_price']:,.0f}" if w.get("last_price") else "not checked yet"
            tgt = f" (target {w['currency']} {w['target']:,.0f})" if w.get("target") else ""
            lines.append(f"  [{w['id']}] {route} — {last}{tgt}")
        return f"👁️ Flight watches ({len(self.items)}):\n" + "\n".join(lines)


class SearchLedger:
    def __init__(self, path=None):
        self.path = Path(path) if path else STATE_PATH
        self.data = self._load()

    def _load(self) -> dict:
        try:
            if self.path.exists():
                d = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    d.setdefault("days", {})
                    d.setdefault("last", 0.0)
                    return d
        except Exception:
            pass
        return {"days": {}, "last": 0.0}

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _day(now):
        return datetime.fromtimestamp(now).date().isoformat()

    def count_today(self, now=None) -> int:
        now = time.time() if now is None else now
        return int(self.data["days"].get(self._day(now), 0))

    def check(self, now=None) -> tuple[bool, str]:
        now = time.time() if now is None else now
        if self.count_today(now) >= DAILY_SEARCH_CAP:
            return False, f"Daily flight-search limit reached ({DAILY_SEARCH_CAP}). Try tomorrow."
        wait = MIN_SEARCH_INTERVAL_S - (now - float(self.data.get("last", 0)))
        if self.data.get("last") and wait > 0:
            return False, f"Give the sites a moment — wait {int(wait) + 1}s."
        return True, ""

    def record(self, now=None):
        now = time.time() if now is None else now
        day = self._day(now)
        self.data["days"][day] = int(self.data["days"].get(day, 0)) + 1
        self.data["last"] = now
        self.save()


# ── Reporting ───────────────────────────────────────────────────────────────

def format_offers(offers: list[dict], title: str = "Best offers", limit: int = 10) -> str:
    if not offers:
        return "No offers parsed. The sites may need a moment to load, or the layout changed — open the links and check visually."
    lines = [f"✈️ {title}"]
    for i, o in enumerate(offers[:limit], 1):
        cur = o.get("currency", DEFAULT_CURRENCY)
        bits = [f"{cur} {float(o['price']):,.0f}"]
        if o.get("airline"):
            bits.append(o["airline"])
        st = o.get("stops", -1)
        bits.append("nonstop" if st == 0 else (f"{st} stop(s)" if st > 0 else "stops n/a"))
        if o.get("duration_min"):
            bits.append(f"{o['duration_min'] // 60}h {o['duration_min'] % 60:02d}m")
        if o.get("site"):
            bits.append(f"via {o['site']}")
        lines.append(f"  {i}. " + " · ".join(bits))
    return "\n".join(lines)


def build_report(search: dict, offers: list[dict], urls: dict,
                 now: float | None = None) -> str:
    now = time.time() if now is None else now
    route = f"{search['origin']} → {search['destination']}"
    lines = [f"# Flight comparison — {route}",
             f"_{datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M')}_", "",
             f"- Dates: {search['depart']}" + (f" → {search['return']}" if search.get("return") else " (one-way)"),
             f"- Cabin: {search['cabin']} · Passengers: {search['passengers']} · Stops: {search['stops']}",
             f"- Currency: {search['currency']}", "",
             "## Ranked offers", ""]
    if offers:
        lines += ["| # | Price | Airline | Stops | Duration | Site | Score |",
                  "|---|---|---|---|---|---|---|"]
        for i, o in enumerate(offers[:20], 1):
            st = o.get("stops", -1)
            stxt = "nonstop" if st == 0 else (str(st) if st > 0 else "—")
            mins = o.get("duration_min") or 0
            dtxt = f"{mins // 60}h {mins % 60:02d}m" if mins else "—"
            lines.append(f"| {i} | {o.get('currency', '')} {float(o['price']):,.0f} | "
                         f"{o.get('airline') or '—'} | {stxt} | {dtxt} | "
                         f"{o.get('site') or '—'} | {o.get('score', '—')} |")
    else:
        lines.append("_No offers parsed automatically — use the links below._")
    lines += ["", "## Search links", ""]
    for site, url in (urls or {}).items():
        lines.append(f"- [{site}]({url})")
    lines += ["", "## When to buy", "", buying_advice(days_until(search["depart"]))]
    return "\n".join(lines) + "\n"


# ── Browser operations ──────────────────────────────────────────────────────

def op_search_site(site: str, s: dict, player=None, delay: float | None = None) -> list[dict]:
    # Resolve the default at call time so SITE_DELAY_S stays tunable.
    delay = SITE_DELAY_S if delay is None else delay
    url = build_url(site, s)
    if not url:
        return []
    _browser({"action": "go_to", "url": url, "headless": False}, player)
    if delay:
        time.sleep(delay)
    text = _browser({"action": "get_text", "limit": 40000, "headless": False}, player)
    if not text or "Could not extract" in str(text):
        return []
    return extract_offers(text, site, s["currency"])


def op_meta_search(s: dict, sites=None, player=None, speak=None,
                   delay: float | None = None) -> tuple[list[dict], dict, list[str]]:
    delay = SITE_DELAY_S if delay is None else delay
    urls = all_urls(s, sites)
    offers, notes = [], []
    for site, url in urls.items():
        _log(player, f"[Flights] {site}: {url}")
        try:
            found = op_search_site(site, s, player, delay)
            offers.extend(found)
            notes.append(f"{site}: {len(found)} offer(s)")
        except Exception as e:
            notes.append(f"{site}: failed ({str(e)[:60]})")
    return offers, urls, notes


# ── Dispatcher ──────────────────────────────────────────────────────────────

_ACTIONS = {
    "help", "status", "capabilities", "airports", "advice", "watches", "unwatch",
    "check_watches", "watch_run", "watch", "links", "book", "search", "find",
    "compare", "meta", "best", "deals", "flexible", "calendar", "cheapest_day",
    "report", "deep",
}


def flight_manager(parameters: dict, player=None, speak=None) -> str:
    params = dict(parameters or {})
    action = str(params.get("action", "help")).lower().strip()

    # Optional personal defaults (home airport / currency / airline preference).
    cfg = load_prefs()
    if not params.get("origin") and cfg.get("home_airport"):
        params["origin"] = cfg["home_airport"]
    if not params.get("currency") and cfg.get("currency"):
        params["currency"] = cfg["currency"]

    try:
        if action in ("help", "status", "capabilities"):
            return (
                "✈️ Flight Manager — cheap flights across sites\n"
                f"  Sites: {', '.join(SITES)}\n"
                "  search      — one site, parsed + ranked\n"
                "  compare     — all sites, ranked best-first\n"
                "  links       — deep links only (no browser, instant)\n"
                "  flexible    — cheapest day in a ±N-day window\n"
                "  watch / unwatch / watches / check_watches — price-drop tracking\n"
                "  report      — markdown comparison (save=true writes reports/)\n"
                "  advice      — when to buy for a date\n"
                "  airports    — resolve a city to an IATA code\n"
                "  book        — opens the site for YOU to pay (never enters card details)\n"
                "Example: compare NBO → DXB on 2026-12-15 returning 2026-12-22, max_price 600"
            )

        if action == "airports":
            q = params.get("query") or params.get("city") or params.get("origin", "")
            code = resolve_airport(q)
            sug = airport_suggestions(q)
            if code:
                return f"🛫 {q} → {code}" + (f"\n  Also: {', '.join(sug)}" if sug else "")
            return f"Couldn't resolve '{q}'." + (f" Did you mean: {', '.join(sug)}?" if sug else " Give me an IATA code.")

        if action == "advice":
            date = parse_date(params.get("date") or params.get("depart"))
            if not date:
                return "Which departure date? e.g. 'advice for 2026-12-15'."
            d = days_until(date)
            return f"📅 {date} is {d} day(s) away.\n{buying_advice(d)}"

        if action == "watches":
            return PriceWatch().render()

        if action == "unwatch":
            wid = str(params.get("id", "")).strip()
            if not wid:
                return "Which watch? Give me its id (see 'watches')."
            return (f"🗑️ Removed watch [{wid}]." if PriceWatch().remove(wid)
                    else f"No watch with id '{wid}'.")

        if action in ("check_watches", "watch_run"):
            # Runs purely from stored watches — no route parameters needed.
            pw = PriceWatch()
            watches = pw.list()
            if not watches:
                return "No watches to check."
            ledger = SearchLedger()
            ok, reason = ledger.check()
            if not ok:
                return f"⏳ {reason}"
            ledger.record()
            lines, alerts = [], 0
            for w in watches:
                variant = {"origin": w["origin"], "destination": w["destination"],
                           "depart": w["depart"], "return": w.get("return", ""),
                           "trip": w["trip"], "passengers": w["passengers"],
                           "cabin": w["cabin"], "currency": w["currency"],
                           "stops": "any", "max_price": 0.0}
                try:
                    offers = op_search_site("kayak", variant, player)
                except Exception as e:
                    lines.append(f"  [{w['id']}] check failed: {str(e)[:60]}")
                    continue
                if not offers:
                    lines.append(f"  [{w['id']}] {w['origin']}→{w['destination']}: no price parsed")
                    continue
                best = min(offers, key=lambda o: float(o["price"]))
                res = pw.record(w["id"], best["price"], best.get("site", "kayak"))
                tag = ""
                if res["target_hit"]:
                    tag = " 🎯 TARGET HIT"
                    alerts += 1
                elif res["dropped"]:
                    tag = f" 🔻 down {w['currency']} {res['drop']:,.0f}"
                    alerts += 1
                lines.append(f"  [{w['id']}] {w['origin']}→{w['destination']} {w['depart']}: "
                             f"{w['currency']} {best['price']:,.0f}{tag}")
            if alerts:
                _say(speak, f"{alerts} flight price alert(s), sir.")
            return f"👁️ Checked {len(watches)} watch(es), {alerts} alert(s):\n" + "\n".join(lines)

        if action not in _ACTIONS:
            return f"Unknown flight action '{action}'. Say 'flight help' for the list."

        # Everything below needs a valid route.
        s = build_search(params)

        if action == "watch":
            if not s["ok"]:
                return "Could not set a watch: " + "; ".join(s["errors"])
            target = params.get("target") or params.get("target_price") or 0
            try:
                target = float(target)
            except (TypeError, ValueError):
                return "target must be a number."
            res = PriceWatch().add(s, target)
            w = res["item"]
            verb = "Updated" if res["existing"] else "Watching"
            tgt = f" — alert at/below {s['currency']} {target:,.0f}" if target else ""
            return f"👁️ {verb} [{w['id']}] {s['origin']}→{s['destination']} {s['depart']}{tgt}"

        if not s["ok"]:
            return "Search problem: " + "; ".join(s["errors"])

        if action == "links":
            urls = all_urls(s, params.get("sites"))
            head = f"🔗 {s['origin']} → {s['destination']} on {s['depart']}"
            if s.get("return"):
                head += f" (return {s['return']})"
            return head + "\n" + "\n".join(f"  {k}: {v}" for k, v in urls.items())

        if action == "book":
            if str(params.get("confirm", "")) != CONFIRM_TEXT:
                return (f"I'll open the booking site, but I never enter payment details — "
                        f"you complete the purchase. Call again with confirm='{CONFIRM_TEXT}'.")
            site = _site_list(params.get("sites") or params.get("site") or "kayak")[0]
            url = build_url(site, s)
            _browser({"action": "go_to", "url": url, "headless": False}, player)
            return (f" Opened {site} for {s['origin']}→{s['destination']} on {s['depart']}.\n"
                    "Complete the passenger details and payment yourself — I won't enter card data.")

        ledger = SearchLedger()
        ok, reason = ledger.check()
        if not ok:
            return f"⏳ {reason}"

        prefs = {"airlines": params.get("airlines") or params.get("preferred_airlines")
                             or cfg.get("preferred_airlines"),
                 "require_bag": bool(params.get("require_bag") or cfg.get("require_bag"))}

        if action in ("search", "find"):
            site = _site_list(params.get("sites") or params.get("site") or "kayak")[0]
            _say(speak, f"Searching {site} for flights to {s['destination']}.")
            ledger.record()
            offers = op_search_site(site, s, player)
            ranked = rank_offers(offers, prefs, s["max_price"])
            out = format_offers(ranked, f"{s['origin']} → {s['destination']} · {s['depart']} · {site}")
            if not ranked and offers:
                out += f"\n(All {len(offers)} parsed offers were above your {s['currency']} {s['max_price']:,.0f} cap.)"
            return out + f"\n\n{buying_advice(days_until(s['depart']))}"

        if action in ("compare", "meta", "best", "deals"):
            sites = _site_list(params.get("sites"))
            _say(speak, f"Comparing flights across {len(sites)} sites.")
            ledger.record()
            offers, urls, notes = op_meta_search(s, sites, player, speak)
            ranked = rank_offers(offers, prefs, s["max_price"])
            head = f"{s['origin']} → {s['destination']} · {s['depart']}"
            if s.get("return"):
                head += f"–{s['return']}"
            out = format_offers(ranked, head + f" · {len(sites)} sites")
            out += "\n\nChecked: " + "; ".join(notes)
            if ranked:
                best = ranked[0]
                out += f"\n\n🏆 Best: {best['currency']} {best['price']:,.0f}"
                if best.get("airline"):
                    out += f" on {best['airline']}"
                out += f" via {best.get('site', '?')}"
            out += "\n\n" + buying_advice(days_until(s["depart"]))
            if params.get("save"):
                REPORT_DIR.mkdir(parents=True, exist_ok=True)
                path = REPORT_DIR / f"flights_{s['origin']}_{s['destination']}_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
                path.write_text(build_report(s, ranked, urls), encoding="utf-8")
                out += f"\n\n📄 Report saved: {path}"
            return out

        if action in ("flexible", "calendar", "cheapest_day"):
            flex = int(params.get("flex_days", 3))
            grid = date_grid(s["depart"], flex)
            if not grid:
                return "Could not build a date window from that departure date."
            site = _site_list(params.get("sites") or "kayak")[0]
            ledger.record()
            results = {}
            for date in grid:
                variant = dict(s, depart=date)
                if variant.get("return"):
                    span = (datetime.strptime(s["return"], "%Y-%m-%d")
                            - datetime.strptime(s["depart"], "%Y-%m-%d")).days
                    variant["return"] = (datetime.strptime(date, "%Y-%m-%d")
                                         + timedelta(days=span)).strftime("%Y-%m-%d")
                try:
                    results[date] = op_search_site(site, variant, player)
                except Exception:
                    results[date] = []
            rows = cheapest_by_date(results)
            if not rows:
                return (f"No prices parsed across {len(grid)} dates on {site}. "
                        "Open the links and check visually.")
            lines = [f"📅 Cheapest days {s['origin']}→{s['destination']} (±{flex}d, {site}):"]
            for r in rows:
                mark = " ← cheapest" if r is rows[0] else ""
                lines.append(f"  {r['date']}: {s['currency']} {r['price']:,.0f}"
                             f"{' · ' + r['airline'] if r['airline'] else ''}{mark}")
            return "\n".join(lines)

        if action == "report":
            ledger.record()
            offers, urls, _ = op_meta_search(s, _site_list(params.get("sites")), player, speak)
            ranked = rank_offers(offers, prefs, s["max_price"])
            text = build_report(s, ranked, urls)
            if params.get("save"):
                REPORT_DIR.mkdir(parents=True, exist_ok=True)
                path = REPORT_DIR / f"flights_{s['origin']}_{s['destination']}_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
                path.write_text(text, encoding="utf-8")
                return f"📄 Report saved: {path}\n\n{text}"
            return text

        if action == "deep":
            ledger.record()
            return _deep_parse(s["origin"], s["destination"], s["depart"],
                               s.get("return"), s["passengers"], s["cabin"],
                               player, speak)

        return f"Unknown flight action '{action}'. Say 'flight help' for the list."
    except Exception as e:
        return f"flight_manager '{action}' failed: {e}"
