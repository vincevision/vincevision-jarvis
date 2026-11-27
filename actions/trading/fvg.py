# actions/trading/fvg.py
"""
Fair Value Gap (FVG) Engine
────────────────────────────
Detects:
  - Bullish FVG  (gap between candle[i-1] high and candle[i+1] low)
  - Bearish FVG  (gap between candle[i-1] low  and candle[i+1] high)
  - Retest validation  (is price currently retesting the FVG?)
  - Partial vs full fill detection
  - FVG strength scoring (size, age, position in PD zone)
  - Confluence with OB (FVG inside OB = highest quality)
  - IFVG (Inverse FVG — filled FVG becomes support/resistance)
  - Consequent Encroachment (CE) — 50% of FVG
"""

from datetime import datetime
from typing   import Optional
import numpy  as np


# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────

# Minimum FVG size as ATR multiple to be considered valid
MIN_FVG_ATR_MULT = 0.1

# Maximum age (candles) before FVG is considered stale
MAX_FVG_AGE = 100

# Retest tolerance — price within this % of FVG counts as retest
RETEST_TOLERANCE = 0.0005   # 0.05%


# ─────────────────────────────────────────────────────────────
# FVG DETECTOR
# ─────────────────────────────────────────────────────────────

def detect_fvg(
    candles:  list[dict],
    atr:      float,
    min_size: float = MIN_FVG_ATR_MULT,
) -> list[dict]:
    """
    Detect all Fair Value Gaps in candle data.

    ICT Definition:
      Bullish FVG: candle[i-1].high < candle[i+1].low
        → gap between prev high and next low (upward imbalance)
      Bearish FVG: candle[i-1].low  > candle[i+1].high
        → gap between prev low and next high (downward imbalance)

    Args:
        candles:  OHLCV list
        atr:      Current ATR for size filtering
        min_size: Minimum FVG size as ATR multiple

    Returns:
        List of FVG dicts sorted oldest → newest.
    """
    if len(candles) < 3:
        return []

    fvgs      = []
    min_gap   = atr * min_size
    total     = len(candles)

    for i in range(1, total - 1):
        c_prev = candles[i - 1]
        c_curr = candles[i]      # The impulse candle
        c_next = candles[i + 1]

        # ── Bullish FVG ───────────────────────────
        gap_bot = c_prev["high"]
        gap_top = c_next["low"]

        if gap_top > gap_bot and (gap_top - gap_bot) >= min_gap:
            size    = gap_top - gap_bot
            mid     = gap_bot + size * 0.5
            ce      = mid   # Consequent Encroachment = 50%

            fvgs.append({
                "type":      "BULLISH_FVG",
                "direction": "BULLISH",
                "top":       round(gap_top, 5),
                "bottom":    round(gap_bot, 5),
                "mid":       round(mid,     5),
                "ce":        round(ce,      5),
                "size":      round(size,    5),
                "size_atr":  round(size / atr, 2),
                "time":      c_curr["time"],
                "index":     i,
                "age":       total - i,

                # State
                "filled":          False,
                "partially_filled": False,
                "retested":        False,
                "retest_candle":   None,
                "invalidated":     False,

                # Impulse candle info
                "impulse_open":  c_curr["open"],
                "impulse_close": c_curr["close"],
                "impulse_high":  c_curr["high"],
                "impulse_low":   c_curr["low"],

                "desc": (
                    f"Bullish FVG: {gap_bot:.5f} — {gap_top:.5f} "
                    f"(size: {size:.5f}, {size/atr:.1f}x ATR)"
                ),
            })

        # ── Bearish FVG ───────────────────────────
        gap_top2 = c_prev["low"]
        gap_bot2 = c_next["high"]

        if gap_top2 > gap_bot2 and (gap_top2 - gap_bot2) >= min_gap:
            size2   = gap_top2 - gap_bot2
            mid2    = gap_bot2 + size2 * 0.5
            ce2     = mid2

            fvgs.append({
                "type":      "BEARISH_FVG",
                "direction": "BEARISH",
                "top":       round(gap_top2, 5),
                "bottom":    round(gap_bot2, 5),
                "mid":       round(mid2,     5),
                "ce":        round(ce2,      5),
                "size":      round(size2,    5),
                "size_atr":  round(size2 / atr, 2),
                "time":      c_curr["time"],
                "index":     i,
                "age":       total - i,

                # State
                "filled":          False,
                "partially_filled": False,
                "retested":        False,
                "retest_candle":   None,
                "invalidated":     False,

                # Impulse candle info
                "impulse_open":  c_curr["open"],
                "impulse_close": c_curr["close"],
                "impulse_high":  c_curr["high"],
                "impulse_low":   c_curr["low"],

                "desc": (
                    f"Bearish FVG: {gap_bot2:.5f} — {gap_top2:.5f} "
                    f"(size: {size2:.5f}, {size2/atr:.1f}x ATR)"
                ),
            })

    return fvgs


# ─────────────────────────────────────────────────────────────
# FILL / RETEST VALIDATOR
# ─────────────────────────────────────────────────────────────

def validate_fvg_states(
    fvgs:    list[dict],
    candles: list[dict],
    atr:     float,
) -> list[dict]:
    """
    For each FVG check all candles AFTER it formed:
      - Is it partially filled? (price entered but did not close through)
      - Is it fully filled?     (price closed fully through)
      - Is it being retested?   (price is currently inside it)
      - Is it invalidated?      (price closed far through)

    Updates FVG dicts in place and returns them.
    """
    tolerance = atr * RETEST_TOLERANCE

    for fvg in fvgs:
        formed_idx    = fvg["index"]
        post_candles  = candles[formed_idx + 2:]  # candles after FVG

        for c in post_candles:
            c_high  = c["high"]
            c_low   = c["low"]
            c_close = c["close"]
            fvg_top = fvg["top"]
            fvg_bot = fvg["bottom"]
            fvg_mid = fvg["mid"]

            if fvg["type"] == "BULLISH_FVG":
                # Price entered FVG from above (pullback into gap)
                if c_low <= fvg_top and c_high >= fvg_bot:
                    fvg["partially_filled"] = True

                    if fvg["retest_candle"] is None:
                        fvg["retest_candle"] = c
                        fvg["retested"]      = True

                # Price closed below FVG bottom = fully filled / invalid
                if c_close < fvg_bot - tolerance:
                    fvg["filled"]      = True
                    fvg["invalidated"] = True

            elif fvg["type"] == "BEARISH_FVG":
                # Price entered FVG from below (pullback into gap)
                if c_high >= fvg_bot and c_low <= fvg_top:
                    fvg["partially_filled"] = True

                    if fvg["retest_candle"] is None:
                        fvg["retest_candle"] = c
                        fvg["retested"]      = True

                # Price closed above FVG top = fully filled / invalid
                if c_close > fvg_top + tolerance:
                    fvg["filled"]      = True
                    fvg["invalidated"] = True

    return fvgs


# ─────────────────────────────────────────────────────────────
# FVG STRENGTH SCORER
# ─────────────────────────────────────────────────────────────

def score_fvg(
    fvg:      dict,
    pd_zones: dict,
    trend:    str,
) -> float:
    """
    Score FVG quality from 0.0 to 1.0.

    Factors:
      + Size (larger = stronger imbalance)
      + Fresh (not yet retested)
      + Aligned with trend
      + Inside discount (bullish) or premium (bearish) zone
      + Impulse candle was strong (large body)
      - Old (more candles ago = weaker)
      - Already filled
    """
    score = 0.0

    if fvg.get("invalidated") or fvg.get("filled"):
        return 0.0

    # Size score (0 - 0.25)
    size_atr = fvg.get("size_atr", 0)
    score   += min(size_atr / 4.0, 0.25)

    # Fresh score (0 - 0.20)
    age   = fvg.get("age", MAX_FVG_AGE)
    fresh = max(0, 1.0 - age / MAX_FVG_AGE)
    score += fresh * 0.20

    # Not yet retested (0.15)
    if not fvg.get("retested"):
        score += 0.15

    # Trend alignment (0.20)
    fvg_dir = fvg.get("direction", "")
    if (fvg_dir == "BULLISH" and trend == "BULLISH") or \
       (fvg_dir == "BEARISH" and trend == "BEARISH"):
        score += 0.20

    # PD Zone alignment (0.15)
    fvg_mid = fvg.get("mid", 0)
    eq      = pd_zones.get("equilibrium", 0)
    if eq > 0:
        if fvg_dir == "BULLISH" and fvg_mid < eq:
            score += 0.15   # Bullish FVG in discount
        elif fvg_dir == "BEARISH" and fvg_mid > eq:
            score += 0.15   # Bearish FVG in premium

    # Impulse candle strength (0.05)
    i_open  = fvg.get("impulse_open",  0)
    i_close = fvg.get("impulse_close", 0)
    i_high  = fvg.get("impulse_high",  0)
    i_low   = fvg.get("impulse_low",   0)
    if i_high > i_low:
        body_ratio = abs(i_close - i_open) / (i_high - i_low)
        score     += body_ratio * 0.05

    return round(min(score, 1.0), 2)


# ─────────────────────────────────────────────────────────────
# CURRENT RETEST CHECKER
# ─────────────────────────────────────────────────────────────

def get_active_fvg_retest(
    fvgs:          list[dict],
    current_price: float,
    direction:     str,
    atr:           float,
) -> Optional[dict]:
    """
    Check if price is currently retesting a valid FVG.
    This is the ICT entry trigger — price retests FVG after MSS.

    Args:
        fvgs:          All detected FVGs
        current_price: Current market price
        direction:     BULLISH | BEARISH
        atr:           Current ATR

    Returns:
        Best FVG being retested, or None.
    """
    tolerance = atr * 0.1
    active    = []

    for fvg in fvgs:
        if fvg.get("invalidated") or fvg.get("filled"):
            continue

        fvg_type = fvg["type"]
        fvg_top  = fvg["top"]
        fvg_bot  = fvg["bottom"]

        if direction == "BULLISH" and fvg_type == "BULLISH_FVG":
            # Price pulling back INTO bullish FVG
            if fvg_bot - tolerance <= current_price <= fvg_top + tolerance:
                active.append(fvg)

        elif direction == "BEARISH" and fvg_type == "BEARISH_FVG":
            # Price pulling back INTO bearish FVG
            if fvg_bot - tolerance <= current_price <= fvg_top + tolerance:
                active.append(fvg)

    if not active:
        return None

    # Return highest scored active FVG
    active.sort(key=lambda x: x.get("score", 0), reverse=True)
    return active[0]


# ─────────────────────────────────────────────────────────────
# IFVG DETECTOR (Inverse FVG)
# ─────────────────────────────────────────────────────────────

def detect_ifvg(
    fvgs:    list[dict],
    candles: list[dict],
) -> list[dict]:
    """
    Detect Inverse FVGs (IFVG).
    A filled FVG flips polarity:
      Filled Bullish FVG → becomes resistance (IFVG Bearish)
      Filled Bearish FVG → becomes support    (IFVG Bullish)

    Returns list of IFVG levels.
    """
    ifvgs = []

    for fvg in fvgs:
        if not fvg.get("filled"):
            continue

        if fvg["type"] == "BULLISH_FVG":
            ifvgs.append({
                "type":      "IFVG_BEARISH",
                "direction": "BEARISH",
                "top":       fvg["top"],
                "bottom":    fvg["bottom"],
                "mid":       fvg["mid"],
                "time":      fvg["time"],
                "desc":      (
                    f"IFVG Bearish (filled bull FVG) "
                    f"@ {fvg['bottom']:.5f}—{fvg['top']:.5f} "
                    f"— now acts as resistance"
                ),
            })

        elif fvg["type"] == "BEARISH_FVG":
            ifvgs.append({
                "type":      "IFVG_BULLISH",
                "direction": "BULLISH",
                "top":       fvg["top"],
                "bottom":    fvg["bottom"],
                "mid":       fvg["mid"],
                "time":      fvg["time"],
                "desc":      (
                    f"IFVG Bullish (filled bear FVG) "
                    f"@ {fvg['bottom']:.5f}—{fvg['top']:.5f} "
                    f"— now acts as support"
                ),
            })

    return ifvgs[-5:]


# ─────────────────────────────────────────────────────────────
# MAIN FVG ANALYSIS
# ─────────────────────────────────────────────────────────────

def analyse_fvg(
    candles:  list[dict],
    atr:      float,
    trend:    str        = "UNKNOWN",
    pd_zones: dict       = None,
) -> dict:
    """
    Full FVG analysis — main entry point for ICT engine.

    Returns:
      {
        "all_fvgs":       every FVG found,
        "valid_fvgs":     unfilled, unvalidated,
        "bullish_fvgs":   valid bullish only,
        "bearish_fvgs":   valid bearish only,
        "best_bullish":   highest scored bullish FVG,
        "best_bearish":   highest scored bearish FVG,
        "active_retest":  FVG being retested right now,
        "ifvgs":          inverse FVGs,
        "count":          total valid count,
      }
    """
    if not candles or len(candles) < 3:
        return {
            "error":       "Insufficient candle data",
            "all_fvgs":    [],
            "valid_fvgs":  [],
            "count":       0,
        }

    if pd_zones is None:
        pd_zones = {}

    current_price = candles[-1]["close"]

    # ── Detect All FVGs ───────────────────────────
    all_fvgs = detect_fvg(candles, atr)

    # ── Validate States ───────────────────────────
    all_fvgs = validate_fvg_states(all_fvgs, candles, atr)

    # ── Score Each FVG ────────────────────────────
    for fvg in all_fvgs:
        fvg["score"] = score_fvg(fvg, pd_zones, trend)

    # ── Filter Valid ──────────────────────────────
    valid_fvgs = [
        f for f in all_fvgs
        if not f["invalidated"]
        and not f["filled"]
        and f["age"] <= MAX_FVG_AGE
        and f["score"] > 0
    ]

    # ── Split by Direction ────────────────────────
    bullish_fvgs = sorted(
        [f for f in valid_fvgs if f["direction"] == "BULLISH"],
        key=lambda x: x["score"],
        reverse=True,
    )
    bearish_fvgs = sorted(
        [f for f in valid_fvgs if f["direction"] == "BEARISH"],
        key=lambda x: x["score"],
        reverse=True,
    )

    # ── Best FVGs ─────────────────────────────────
    best_bullish = bullish_fvgs[0] if bullish_fvgs else None
    best_bearish = bearish_fvgs[0] if bearish_fvgs else None

    # ── Active Retest ─────────────────────────────
    direction    = trend if trend != "UNKNOWN" else "BULLISH"
    active_retest = get_active_fvg_retest(
        valid_fvgs, current_price, direction, atr
    )

    # ── Inverse FVGs ──────────────────────────────
    ifvgs = detect_ifvg(all_fvgs, candles)

    return {
        # All data
        "all_fvgs":     all_fvgs,
        "valid_fvgs":   valid_fvgs,
        "bullish_fvgs": bullish_fvgs[:5],
        "bearish_fvgs": bearish_fvgs[:5],

        # Best picks
        "best_bullish":  best_bullish,
        "best_bearish":  best_bearish,
        "active_retest": active_retest,

        # Inverse
        "ifvgs": ifvgs,

        # Summary
        "count":          len(valid_fvgs),
        "bull_count":     len(bullish_fvgs),
        "bear_count":     len(bearish_fvgs),
        "current_price":  current_price,
        "analysed_at":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─────────────────────────────────────────────────────────────
# FORMATTER
# ─────────────────────────────────────────────────────────────

def format_fvg(result: dict) -> str:
    """Human readable FVG summary."""
    if "error" in result:
        return f"[FVG] Error: {result['error']}"

    lines = [
        "📦 FAIR VALUE GAPS",
        "─" * 42,
        f"Total Valid:   {result.get('count', 0)}",
        f"Bullish FVGs:  {result.get('bull_count', 0)}",
        f"Bearish FVGs:  {result.get('bear_count', 0)}",
        f"Current Price: {result.get('current_price', 0):.5f}",
    ]

    best_b = result.get("best_bullish")
    if best_b:
        lines += [
            "",
            "🟢 BEST BULLISH FVG:",
            f"  Zone:   {best_b['bottom']:.5f} — {best_b['top']:.5f}",
            f"  CE:     {best_b['ce']:.5f}",
            f"  Size:   {best_b['size_atr']:.1f}x ATR",
            f"  Score:  {best_b['score'] * 100:.0f}%",
            f"  Age:    {best_b['age']} candles",
            f"  Tested: {'YES' if best_b['retested'] else 'NO'}",
        ]

    best_r = result.get("best_bearish")
    if best_r:
        lines += [
            "",
            "🔴 BEST BEARISH FVG:",
            f"  Zone:   {best_r['bottom']:.5f} — {best_r['top']:.5f}",
            f"  CE:     {best_r['ce']:.5f}",
            f"  Size:   {best_r['size_atr']:.1f}x ATR",
            f"  Score:  {best_r['score'] * 100:.0f}%",
            f"  Age:    {best_r['age']} candles",
            f"  Tested: {'YES' if best_r['retested'] else 'NO'}",
        ]

    active = result.get("active_retest")
    if active:
        lines += [
            "",
            "⚡ ACTIVE RETEST:",
            f"  Type:   {active['type']}",
            f"  Zone:   {active['bottom']:.5f} — {active['top']:.5f}",
            f"  Score:  {active['score'] * 100:.0f}%",
            f"  → Entry opportunity forming!",
        ]

    ifvgs = result.get("ifvgs", [])
    if ifvgs:
        lines += ["", "🔄 INVERSE FVGs:"]
        for iv in ifvgs[:3]:
            lines.append(f"  • {iv['desc']}")

    return "\n".join(lines)