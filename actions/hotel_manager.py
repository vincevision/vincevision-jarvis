"""
Hotel Manager for JARVIS — multi-site stay search, watched on screen
────────────────────────────────────────────────────────────────────
Searches Booking.com, Airbnb, Expedia, Hotels.com, Agoda, Kayak and Google
Hotels from one command, then ranks stays by price *and* quality.

  search / compare / links   — one site, all sites, or instant deep links
  flexible                   — cheapest check-in in a ±N-day window
  watch / watches / check_watches / unwatch — nightly-price tracking
  report                     — markdown comparison (save=true → reports/)

Everything runs through core/visible.py, so the browser opens **on screen**
and each step is narrated. The whole dispatcher is wrapped in
core/safe_run.safe_tool, so a site failure can never crash the session.

Honest limits: deep links follow each site's published URL pattern and are
unit-tested offline, but were not verified against the live sites from the
build sandbox (no outbound access to those hosts). Text parsing is
best-effort, English-locale. No FX rates are invented.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from core.safe_run import safe_tool
from core.visible import Narrator, visible

CONFIRM_TEXT = "HOTEL CONFIRMED"
WATCH_PATH = Path("memory") / "hotel_watches.json"
STATE_PATH = Path("memory") / "hotel_state.json"
REPORT_DIR = Path("reports")
CONFIG_PATH = Path("config") / "hotels.json"

SITES = ("booking", "airbnb", "expedia", "hotels", "agoda", "kayak", "google")
MAX_SITES = 7
DEFAULT_CURRENCY = "USD"
DAILY_SEARCH_CAP = 60
MIN_SEARCH_INTERVAL_S = 3
SITE_DELAY_S = 4.0
MAX_FLEX_DAYS = 7


def _browser(params: dict, player=None) -> str:
    from actions.browser_control import browser_control
    return browser_control(parameters=visible(params), player=player)


def _alerts():
    from core import alerts
    return alerts


def load_prefs(path=None) -> dict:
    cfg = {"default_city": "", "currency": DEFAULT_CURRENCY,
           "min_rating": 0.0, "guests": 2}
    p = Path(path) if path else CONFIG_PATH
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in cfg})
    except Exception:
        pass
    return cfg


# ── Dates (shared semantics with flight_manager) ────────────────────────────

def parse_date(raw, today: datetime | None = None) -> str:
    from actions.flight_manager import parse_date as fd
    return fd(raw, today)


def nights_between(checkin: str, checkout: str) -> int:
    try:
        a = datetime.strptime(checkin, "%Y-%m-%d")
        b = datetime.strptime(checkout, "%Y-%m-%d")
        return (b - a).days
    except (ValueError, TypeError):
        return 0


def date_grid(center: str, flex_days: int = 3) -> list[str]:
    try:
        base = datetime.strptime(center, "%Y-%m-%d")
    except (ValueError, TypeError):
        return []
    n = max(0, min(int(flex_days), MAX_FLEX_DAYS))
    return [(base + timedelta(days=d)).strftime("%Y-%m-%d") for d in range(-n, n + 1)]


# ── Search validation ───────────────────────────────────────────────────────

def build_search(params: dict, today: datetime | None = None) -> dict:
    errors = []
    city = str(params.get("city") or params.get("destination") or "").strip()
    if not city:
        errors.append("Which city? e.g. 'hotels in Dubai'.")

    checkin = parse_date(params.get("checkin") or params.get("date"), today)
    if not checkin:
        errors.append("A check-in date is required (2026-12-15, 'next friday', 'in 3 weeks').")
    checkout = parse_date(params.get("checkout") or params.get("return_date"), today)

    try:
        nights = int(params.get("nights", 0) or 0)
    except (TypeError, ValueError):
        nights = 0
        errors.append("nights must be a whole number.")
    if nights < 0:
        errors.append("nights cannot be negative.")

    if checkin and not checkout and nights > 0:
        checkout = (datetime.strptime(checkin, "%Y-%m-%d")
                    + timedelta(days=nights)).strftime("%Y-%m-%d")
    if checkin and not checkout:
        checkout = (datetime.strptime(checkin, "%Y-%m-%d")
                    + timedelta(days=1)).strftime("%Y-%m-%d")
    if checkin and checkout and nights_between(checkin, checkout) < 1:
        errors.append("Check-out must be after check-in.")

    try:
        guests = int(params.get("guests", 2))
    except (TypeError, ValueError):
        guests = 0
    if not 1 <= guests <= 16:
        errors.append("guests must be between 1 and 16.")

    try:
        rooms = int(params.get("rooms", 1))
    except (TypeError, ValueError):
        rooms = 0
    if not 1 <= rooms <= 8:
        errors.append("rooms must be between 1 and 8.")

    budget = params.get("max_price", params.get("budget"))
    try:
        budget = float(budget) if budget not in (None, "") else 0.0
    except (TypeError, ValueError):
        errors.append("max_price must be a number (per night).")
        budget = 0.0
    if budget < 0:
        errors.append("max_price cannot be negative.")

    rating = params.get("min_rating", 0)
    try:
        rating = float(rating or 0)
    except (TypeError, ValueError):
        errors.append("min_rating must be a number.")
        rating = 0.0
    if not 0 <= rating <= 10:
        errors.append("min_rating must be between 0 and 10.")

    currency = str(params.get("currency", DEFAULT_CURRENCY)).upper().strip()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        currency = DEFAULT_CURRENCY

    return {"ok": not errors, "errors": errors, "city": city, "checkin": checkin,
            "checkout": checkout, "nights": nights_between(checkin, checkout),
            "guests": guests, "rooms": rooms, "max_price": budget,
            "min_rating": rating, "currency": currency}


def _site_list(raw) -> list[str]:
    if raw is None or str(raw).strip().lower() in ("", "all", "default"):
        return list(SITES)
    items = raw if isinstance(raw, (list, tuple)) else re.split(r"[,\s]+", str(raw))
    aliases = {"booking.com": "booking", "hotels.com": "hotels",
               "google hotels": "google", "googlehotels": "google"}
    out, seen = [], set()
    for s in items:
        k = str(s or "").strip().lower()
        k = aliases.get(k, k)
        if k in SITES and k not in seen:
            seen.add(k)
            out.append(k)
    return out[:MAX_SITES] or list(SITES)


# ── Deep links ──────────────────────────────────────────────────────────────

def build_url(site: str, s: dict) -> str:
    from urllib.parse import quote_plus
    city, ci, co = s["city"], s["checkin"], s["checkout"]
    guests, rooms, cur = s["guests"], s["rooms"], s["currency"]
    q = quote_plus(city)

    if site == "booking":
        url = (f"https://www.booking.com/searchresults.html?ss={q}"
               f"&checkin={ci}&checkout={co}&group_adults={guests}"
               f"&no_rooms={rooms}&selected_currency={cur}&order=price")
        if s["max_price"]:
            url += f"&nflt=price%3D{cur}-min-{int(s['max_price'])}-1"
        return url

    if site == "airbnb":
        url = (f"https://www.airbnb.com/s/{q}/homes?checkin={ci}&checkout={co}"
               f"&adults={guests}&currency={cur}")
        if s["max_price"]:
            url += f"&price_max={int(s['max_price'])}"
        return url

    if site in ("expedia", "hotels"):
        host = "www.expedia.com" if site == "expedia" else "www.hotels.com"
        url = (f"https://{host}/Hotel-Search?destination={q}"
               f"&startDate={ci}&endDate={co}&adults={guests}&rooms={rooms}"
               f"&sort=PRICE_LOW_TO_HIGH")
        if s["min_rating"]:
            url += f"&guestRating={int(s['min_rating'])}"
        return url

    if site == "agoda":
        return (f"https://www.agoda.com/search?textToSearch={q}&checkIn={ci}"
                f"&los={max(1, s['nights'])}&adults={guests}&rooms={rooms}"
                f"&currency={cur}&sort=priceLowToHigh")

    if site == "kayak":
        return (f"https://www.kayak.com/hotels/{q}/{ci}/{co}/{guests}adults"
                f"?sort=price_a&rooms={rooms}")

    if site == "google":
        query = f"hotels in {city} from {ci} to {co} for {guests} guests"
        return (f"https://www.google.com/travel/hotels?q={quote_plus(query)}"
                f"&curr={cur}&hl=en")

    return ""


def all_urls(s: dict, sites=None) -> dict:
    return {site: build_url(site, s) for site in _site_list(sites)}


# ── Parsing ────────────────────────────────────────────────────────────────

_PRICE_RE = re.compile(
    r"(?:\b(?:USD|EUR|GBP|KES|KSh|AED|INR|ZAR|AUD|CAD|JPY)\s?"
    r"|[\$€£₹¥]\s?|(?<![A-Za-z])R\s?)"
    r"(\d{1,3}(?:[,\s]\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)",
    re.IGNORECASE)
_RATING_RE = re.compile(r"\b([0-9](?:\.\d)?)\s*(?:/\s*(?:5|10))?\b")
_REVIEW_RE = re.compile(r"([\d,]+)\s*(?:reviews|ratings|guest reviews)", re.IGNORECASE)
_STARS_RE = re.compile(r"(\d)\s*[- ]?star", re.IGNORECASE)


def parse_prices(text: str) -> list[float]:
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


def parse_rating(text: str) -> float:
    """Guest score. '8.6' (10-scale) stays 8.6; '4.5/5' becomes 9.0."""
    low = str(text or "")
    m = re.search(r"\b(\d(?:\.\d)?)\s*/\s*5\b", low)
    if m:
        return round(float(m.group(1)) * 2, 1)
    m = re.search(r"\b(\d(?:\.\d)?)\s*/\s*10\b", low)
    if m:
        return float(m.group(1))
    for cand in re.findall(r"\b([0-9]\.\d)\b", low):
        val = float(cand)
        if 1.0 <= val <= 10.0:
            return val
    return 0.0


def parse_reviews(text: str) -> int:
    m = _REVIEW_RE.search(str(text or ""))
    if not m:
        return 0
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return 0


def parse_stars(text: str) -> int:
    m = _STARS_RE.search(str(text or ""))
    return int(m.group(1)) if m else 0


def extract_stays(text: str, site: str = "", currency: str = DEFAULT_CURRENCY,
                  limit: int = 20) -> list[dict]:
    """Best-effort: each price line plus its own context block."""
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    stays, seen = [], set()
    last = -1
    for i, line in enumerate(lines):
        prices = parse_prices(line)
        if not prices:
            continue
        start = max(0, last + 1, i - 6)
        last = i
        context = " | ".join(lines[start:i + 1])
        name = ""
        for ln in lines[start:i]:
            if not parse_prices(ln) and len(ln) > 3 and not ln.replace(".", "").isdigit():
                name = ln
                break
        price = min(prices)
        rating = parse_rating(context)
        key = (price, name, rating)
        if key in seen:
            continue
        seen.add(key)
        stays.append({"site": site, "price": price, "currency": currency,
                      "name": name[:90], "rating": rating,
                      "reviews": parse_reviews(context), "stars": parse_stars(context),
                      "raw": context[:220]})
        if len(stays) >= limit:
            break
    return stays


# ── Ranking ────────────────────────────────────────────────────────────────

def score_stay(stay: dict, prefs: dict | None = None) -> float:
    """Lower is better: nightly price, adjusted for quality and confidence."""
    prefs = prefs or {}
    price = float(stay.get("price", 0) or 0)
    score = price
    rating = float(stay.get("rating", 0) or 0)
    if rating:
        # A 9.0 stay is worth a premium; a 5.0 stay needs a discount.
        score += (8.0 - rating) * float(prefs.get("rating_weight", 12))
    reviews = int(stay.get("reviews", 0) or 0)
    if reviews == 0:
        score += float(prefs.get("no_reviews_penalty", 25))
    elif reviews < 20:
        score += float(prefs.get("few_reviews_penalty", 10))
    stars = int(stay.get("stars", 0) or 0)
    want = int(prefs.get("min_stars", 0) or 0)
    if want and stars and stars < want:
        score += (want - stars) * float(prefs.get("star_penalty", 30))
    return round(score, 2)


def rank_stays(stays: list[dict], prefs: dict | None = None,
               max_price: float = 0, min_rating: float = 0) -> list[dict]:
    out = []
    for st in stays or []:
        price = float(st.get("price", 0) or 0)
        if max_price and price > max_price:
            continue
        if min_rating and float(st.get("rating", 0) or 0) < min_rating:
            continue
        item = dict(st)
        item["score"] = score_stay(st, prefs)
        out.append(item)
    out.sort(key=lambda x: (x["score"], x.get("price", 0)))
    return out


def cheapest_by_date(results: dict) -> list[dict]:
    rows = []
    for date, stays in (results or {}).items():
        valid = [x for x in stays if float(x.get("price", 0)) > 0]
        if not valid:
            continue
        best = min(valid, key=lambda x: float(x["price"]))
        rows.append({"date": date, "price": float(best["price"]),
                     "site": best.get("site", ""), "name": best.get("name", "")})
    rows.sort(key=lambda r: (r["price"], r["date"]))
    return rows


# ── Watches + rate limit ────────────────────────────────────────────────────

class HotelWatch:
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

    def add(self, s: dict, target: float = 0, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        for w in self.items:
            if (w["city"].lower() == s["city"].lower() and w["checkin"] == s["checkin"]
                    and w["checkout"] == s["checkout"]):
                if target:
                    w["target"] = float(target)
                    self.save()
                return {"ok": True, "item": w, "existing": True}
        item = {"id": uuid.uuid4().hex[:8], "city": s["city"], "checkin": s["checkin"],
                "checkout": s["checkout"], "guests": s["guests"], "rooms": s["rooms"],
                "currency": s["currency"], "nights": s["nights"],
                "target": float(target or 0), "created": now,
                "history": [], "last_price": 0.0}
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
        target = float(w.get("target") or 0)
        return {"ok": True, "watch": w, "previous": prev,
                "drop": round(prev - price, 2) if prev else 0.0,
                "dropped": bool(prev and price < prev),
                "target_hit": bool(target and price <= target)}

    def render(self) -> str:
        if not self.items:
            return "No hotel watches. Say 'watch hotels in Dubai Dec 15 for 5 nights'."
        lines = []
        for w in self.items:
            last = (f"{w['currency']} {w['last_price']:,.0f}/night"
                    if w.get("last_price") else "not checked yet")
            tgt = f" (target {w['currency']} {w['target']:,.0f})" if w.get("target") else ""
            lines.append(f"  [{w['id']}] {w['city']} {w['checkin']}→{w['checkout']} — {last}{tgt}")
        return f"🏨 Hotel watches ({len(self.items)}):\n" + "\n".join(lines)


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
            return False, f"Daily hotel-search limit reached ({DAILY_SEARCH_CAP}). Try tomorrow."
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


# ── Formatting ──────────────────────────────────────────────────────────────

def format_stays(stays: list[dict], title: str = "Best stays", limit: int = 10) -> str:
    if not stays:
        return ("No stays parsed. The sites may still be loading, or the layout changed — "
                "the browser is open so you can look yourself.")
    lines = [f"🏨 {title}"]
    for i, st in enumerate(stays[:limit], 1):
        bits = [f"{st.get('currency', DEFAULT_CURRENCY)} {float(st['price']):,.0f}/night"]
        if st.get("name"):
            bits.append(st["name"])
        if st.get("rating"):
            bits.append(f"★ {st['rating']}")
        if st.get("reviews"):
            bits.append(f"{st['reviews']:,} reviews")
        if st.get("site"):
            bits.append(f"via {st['site']}")
        lines.append(f"  {i}. " + " · ".join(bits))
    return "\n".join(lines)


def build_report(s: dict, stays: list[dict], urls: dict, now: float | None = None) -> str:
    now = time.time() if now is None else now
    lines = [f"# Hotel comparison — {s['city']}",
             f"_{datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M')}_", "",
             f"- Stay: {s['checkin']} → {s['checkout']} ({s['nights']} night(s))",
             f"- Guests: {s['guests']} · Rooms: {s['rooms']} · Currency: {s['currency']}", ""]
    if s["max_price"]:
        lines.append(f"- Budget: {s['currency']} {s['max_price']:,.0f}/night")
    lines += ["", "## Ranked stays", ""]
    if stays:
        lines += ["| # | Nightly | Total | Name | Rating | Reviews | Site |",
                  "|---|---|---|---|---|---|---|"]
        for i, st in enumerate(stays[:20], 1):
            total = float(st["price"]) * max(1, s["nights"])
            lines.append(f"| {i} | {st.get('currency', '')} {float(st['price']):,.0f} | "
                         f"{st.get('currency', '')} {total:,.0f} | {st.get('name') or '—'} | "
                         f"{st.get('rating') or '—'} | {st.get('reviews') or '—'} | "
                         f"{st.get('site') or '—'} |")
    else:
        lines.append("_No stays parsed automatically — use the links below._")
    lines += ["", "## Search links", ""]
    for site, url in (urls or {}).items():
        lines.append(f"- [{site}]({url})")
    return "\n".join(lines) + "\n"


# ── Visible browser operations ──────────────────────────────────────────────

def op_search_site(site: str, s: dict, narrator: Narrator | None = None,
                   delay: float | None = None) -> list[dict]:
    delay = SITE_DELAY_S if delay is None else delay
    n = narrator or Narrator()
    url = build_url(site, s)
    if not url:
        return []
    n.doing(f"Opening {site} for {s['city']}")
    _browser({"action": "go_to", "url": url, "headless": False}, n.player)
    if delay:
        n.pause(delay)
    n.doing(f"Reading prices on {site}")
    text = _browser({"action": "get_text", "limit": 40000, "headless": False}, n.player)
    if not text or "Could not extract" in str(text):
        n.warn(f"{site} did not return readable text")
        return []
    stays = extract_stays(text, site, s["currency"])
    n.done(f"{site}: {len(stays)} stay(s) found")
    return stays


def op_meta_search(s: dict, sites=None, narrator: Narrator | None = None,
                   delay: float | None = None) -> tuple[list[dict], dict, list[str]]:
    n = narrator or Narrator()
    urls = all_urls(s, sites)
    stays, notes = [], []
    n.doing(f"Comparing {len(urls)} hotel sites for {s['city']}", speak_it=True)
    for site in urls:
        try:
            found = op_search_site(site, s, n, delay)
            stays.extend(found)
            notes.append(f"{site}: {len(found)}")
        except Exception as exc:
            n.warn(f"{site} failed: {str(exc)[:70]}")
            notes.append(f"{site}: failed")
    return stays, urls, notes


# ── Dispatcher ──────────────────────────────────────────────────────────────

_ACTIONS = {"help", "status", "capabilities", "watches", "unwatch", "check_watches",
            "watch_run", "watch", "links", "search", "find", "compare", "meta",
            "best", "deals", "flexible", "calendar", "report", "book"}


@safe_tool("hotel_manager")
def hotel_manager(parameters: dict, player=None, speak=None) -> str:
    params = dict(parameters or {})
    action = str(params.get("action", "help")).lower().strip()
    cfg = load_prefs()
    if not (params.get("city") or params.get("destination")) and cfg.get("default_city"):
        params["city"] = cfg["default_city"]
    if not params.get("currency") and cfg.get("currency"):
        params["currency"] = cfg["currency"]

    n = Narrator(player, speak, prefix="Hotels")

    if action in ("help", "status", "capabilities"):
        return ("🏨 Hotel Manager — stays across sites, watched on screen\n"
                f"  Sites: {', '.join(SITES)}\n"
                "  compare — all sites, ranked by price AND rating\n"
                "  search  — one site\n"
                "  links   — instant deep links, opens nothing\n"
                "  flexible — cheapest check-in ±N days\n"
                "  watch / watches / check_watches / unwatch — nightly-price alerts\n"
                "  report  — markdown table (save=true → reports/)\n"
                "Example: compare hotels in Dubai, checkin 2026-12-15, nights 5, max_price 150")

    if action == "watches":
        return HotelWatch().render()

    if action == "unwatch":
        wid = str(params.get("id", "")).strip()
        if not wid:
            return "Which watch? Give me its id (see 'watches')."
        return (f"🗑️ Removed watch [{wid}]." if HotelWatch().remove(wid)
                else f"No watch with id '{wid}'.")

    if action in ("check_watches", "watch_run"):
        hw = HotelWatch()
        watches = hw.list()
        if not watches:
            return "No hotel watches to check."
        ledger = SearchLedger()
        ok, reason = ledger.check()
        if not ok:
            return f"⏳ {reason}"
        ledger.record()
        lines, alerts = [], 0
        for w in watches:
            variant = {"city": w["city"], "checkin": w["checkin"], "checkout": w["checkout"],
                       "guests": w["guests"], "rooms": w["rooms"], "currency": w["currency"],
                       "nights": w.get("nights", 1), "max_price": 0.0, "min_rating": 0.0}
            try:
                stays = op_search_site("booking", variant, n)
            except Exception as exc:
                lines.append(f"  [{w['id']}] check failed: {str(exc)[:60]}")
                continue
            if not stays:
                lines.append(f"  [{w['id']}] {w['city']}: no price parsed")
                continue
            best = min(stays, key=lambda x: float(x["price"]))
            res = hw.record(w["id"], best["price"], best.get("site", "booking"))
            tag = ""
            if res["target_hit"]:
                tag = " 🎯 TARGET HIT"
                alerts += 1
            elif res["dropped"]:
                tag = f" 🔻 down {w['currency']} {res['drop']:,.0f}"
                alerts += 1
            lines.append(f"  [{w['id']}] {w['city']} {w['checkin']}: "
                         f"{w['currency']} {best['price']:,.0f}/night{tag}")
            if tag:
                try:
                    _alerts().notify(
                        f"Hotel price alert — {w['city']}",
                        f"{w['city']} {w['checkin']}→{w['checkout']}: "
                        f"{w['currency']} {best['price']:,.0f}/night{tag}")
                except Exception:
                    pass
        n.done(f"Checked {len(watches)} hotel watch(es), {alerts} alert(s)")
        return f"👁️ Checked {len(watches)} watch(es), {alerts} alert(s):\n" + "\n".join(lines)

    if action not in _ACTIONS:
        return f"Unknown hotel action '{action}'. Say 'hotel help' for the list."

    s = build_search(params)

    if action == "watch":
        if not s["ok"]:
            return "Could not set a watch: " + "; ".join(s["errors"])
        try:
            target = float(params.get("target") or params.get("target_price") or 0)
        except (TypeError, ValueError):
            return "target must be a number (per night)."
        res = HotelWatch().add(s, target)
        w = res["item"]
        verb = "Updated" if res["existing"] else "Watching"
        tgt = f" — alert at/below {s['currency']} {target:,.0f}/night" if target else ""
        n.done(f"{verb} {s['city']} {s['checkin']}")
        return f"👁️ {verb} [{w['id']}] {s['city']} {s['checkin']}→{s['checkout']}{tgt}"

    if not s["ok"]:
        return "Search problem: " + "; ".join(s["errors"])

    if action == "links":
        urls = all_urls(s, params.get("sites"))
        head = f"🔗 Hotels in {s['city']} · {s['checkin']} → {s['checkout']} ({s['nights']}n)"
        return head + "\n" + "\n".join(f"  {k}: {v}" for k, v in urls.items())

    if action == "book":
        if str(params.get("confirm", "")) != CONFIRM_TEXT:
            return (f"I'll open the booking site, but I never enter payment details. "
                    f"Call again with confirm='{CONFIRM_TEXT}'.")
        site = _site_list(params.get("sites") or params.get("site") or "booking")[0]
        url = build_url(site, s)
        n.doing(f"Opening {site} for you to complete the booking")
        _browser({"action": "go_to", "url": url, "headless": False}, player)
        return (f"🏨 Opened {site} for {s['city']} ({s['checkin']}→{s['checkout']}).\n"
                "Enter guest and payment details yourself — I won't touch card data.")

    ledger = SearchLedger()
    ok, reason = ledger.check()
    if not ok:
        return f"⏳ {reason}"

    prefs = {"min_stars": params.get("min_stars", 0)}

    if action in ("search", "find"):
        site = _site_list(params.get("sites") or params.get("site") or "booking")[0]
        ledger.record()
        stays = op_search_site(site, s, n)
        ranked = rank_stays(stays, prefs, s["max_price"], s["min_rating"])
        out = format_stays(ranked, f"{s['city']} · {s['checkin']}→{s['checkout']} · {site}")
        if not ranked and stays:
            out += "\n(All parsed stays were outside your price/rating filters.)"
        return out

    if action in ("compare", "meta", "best", "deals"):
        sites = _site_list(params.get("sites"))
        ledger.record()
        stays, urls, notes = op_meta_search(s, sites, n)
        ranked = rank_stays(stays, prefs, s["max_price"], s["min_rating"])
        out = format_stays(ranked, f"{s['city']} · {s['nights']} night(s) · {len(sites)} sites")
        out += "\n\nChecked: " + "; ".join(notes)
        if ranked:
            best = ranked[0]
            total = float(best["price"]) * max(1, s["nights"])
            out += (f"\n\n🏆 Best: {best['currency']} {best['price']:,.0f}/night"
                    f" ({best['currency']} {total:,.0f} total)")
            if best.get("name"):
                out += f" — {best['name']}"
            out += f" via {best.get('site', '?')}"
        if params.get("save"):
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            path = REPORT_DIR / f"hotels_{re.sub(r'[^a-z0-9]+', '_', s['city'].lower())}_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
            path.write_text(build_report(s, ranked, urls), encoding="utf-8")
            out += f"\n\n📄 Report saved: {path}"
        n.done("Hotel comparison finished")
        return out

    if action in ("flexible", "calendar"):
        try:
            flex = int(params.get("flex_days", 3))
        except (TypeError, ValueError):
            return "flex_days must be a whole number."
        if flex < 0 or flex > MAX_FLEX_DAYS:
            return f"flex_days must be between 0 and {MAX_FLEX_DAYS}."
        grid = date_grid(s["checkin"], flex)
        if not grid:
            return "Could not build a date window from that check-in date."
        site = _site_list(params.get("sites") or "booking")[0]
        ledger.record()
        results = {}
        span = max(1, s["nights"])
        for date in grid:
            variant = dict(s, checkin=date,
                           checkout=(datetime.strptime(date, "%Y-%m-%d")
                                     + timedelta(days=span)).strftime("%Y-%m-%d"))
            try:
                results[date] = op_search_site(site, variant, n)
            except Exception:
                results[date] = []
        rows = cheapest_by_date(results)
        if not rows:
            return f"No prices parsed across {len(grid)} dates on {site}. The browser is open — check visually."
        lines = [f"📅 Cheapest check-ins in {s['city']} (±{flex}d, {site}):"]
        for r in rows:
            mark = " ← cheapest" if r is rows[0] else ""
            lines.append(f"  {r['date']}: {s['currency']} {r['price']:,.0f}/night{mark}")
        return "\n".join(lines)

    if action == "report":
        ledger.record()
        stays, urls, _ = op_meta_search(s, _site_list(params.get("sites")), n)
        ranked = rank_stays(stays, prefs, s["max_price"], s["min_rating"])
        text = build_report(s, ranked, urls)
        if params.get("save"):
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            path = REPORT_DIR / f"hotels_{re.sub(r'[^a-z0-9]+', '_', s['city'].lower())}_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
            path.write_text(text, encoding="utf-8")
            return f"📄 Report saved: {path}\n\n{text}"
        return text

    return f"Unknown hotel action '{action}'. Say 'hotel help' for the list."
