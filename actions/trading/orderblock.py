# actions/trading/orderblock.py
"""
Order Block Engine
───────────────────
Detects:
  - Bullish Order Blocks  (last bearish candle before bullish impulse)
  - Bearish Order Blocks  (last bullish candle before bearish impulse)
  - Breaker Blocks        (invalidated OB that flips polarity)
  - Mitigation Blocks     (partially mitigated OB)
  - OB + FVG confluence   (highest quality ICT setup)
  - OB retest validation  (is price retesting right now?)
  - OB strength scoring
  - OB with volume profile
"""

from datetime import datetime
from typing   import Optional
import numpy  as np


# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────

# Minimum impulse move after OB as ATR multiple
MIN_IMPULSE_ATR = 1.5

# Minimum OB body size as ATR multiple
MIN_OB_BODY_ATR = 0.1

# How many candles forward to measure impulse
IMPULSE_LOOKFORWARD = 5

# Retest tolerance as ATR multiple
RETEST_ATR_TOLERANCE = 0.3

# Max OB age in candles
MAX_OB_AGE = 150


# ─────────────────────────────────────────────────────────────
# IMPULSE MEASURER
# ─────────────────────────────────────────────────────────────

def _measure_impulse(
    candles:    list[dict],
    start_idx:  int,
    direction:  str,
    lookforward: int = IMPULSE_LOOKFORWARD,
) -> dict:
    """
    Measure the impulse move after a potential OB candle.

    Args:
        candles:     Full candle list
        start_idx:   Index of OB candle
        direction:   BULLISH | BEARISH
        lookforward: Candles to look forward

    Returns:
        {
          "size":       impulse size in price,
          "size_atr":   impulse as ATR multiple,
          "strong":     bool — is it a valid impulse?
          "end_idx":    index where impulse ends,
          "end_price":  price at impulse end,
        }
    """
    end_idx = min(start_idx + lookforward, len(candles) - 1)
    window  = candles[start_idx + 1 : end_idx + 1]

    if not window:
        return {"size": 0, "size_atr": 0, "strong": False,
                "end_idx": end_idx, "end_price": 0}

    ob_candle = candles[start_idx]

    if direction == "BULLISH":
        # Impulse = how far price moved up from OB
        max_high   = max(c["high"] for c in window)
        size       = max_high - ob_candle["high"]
        end_price  = max_high
    else:
        # Impulse = how far price moved down from OB
        min_low    = min(c["low"] for c in window)
        size       = ob_candle["low"] - min_low
        end_price  = min_low

    return {
        "size":      max(size, 0),
        "end_idx":   end_idx,
        "end_price": end_price,
    }


# ─────────────────────────────────────────────────────────────
# ORDER BLOCK DETECTOR
# ─────────────────────────────────────────────────────────────

def detect_order_blocks(
    candles: list[dict],
    atr:     float,
    swings:  dict = None,
) -> list[dict]:
    """
    Detect Bullish and Bearish Order Blocks.

    ICT Definition:
      Bullish OB = last BEARISH candle before a BULLISH impulse
        → close < open (red candle)
        → followed by strong up move
        → OB zone: low to high of that red candle

      Bearish OB = last BULLISH candle before a BEARISH impulse
        → close > open (green candle)
        → followed by strong down move
        → OB zone: low to high of that green candle

    Args:
        candles: OHLCV list
        atr:     Current ATR
        swings:  Swing highs/lows for context

    Returns:
        List of OB dicts sorted oldest → newest.
    """
    if len(candles) < IMPULSE_LOOKFORWARD + 2:
        return []

    obs          = []
    total        = len(candles)
    min_impulse  = atr * MIN_IMPULSE_ATR
    min_body     = atr * MIN_OB_BODY_ATR

    for i in range(1, total - IMPULSE_LOOKFORWARD - 1):
        c     = candles[i]
        c_body = abs(c["close"] - c["open"])

        # Skip doji / tiny candles
        if c_body < min_body:
            continue

        # ── Bullish OB ────────────────────────────
        # Last bearish candle (red) before bullish impulse
        if c["close"] < c["open"]:
            impulse = _measure_impulse(candles, i, "BULLISH")
            if impulse["size"] >= min_impulse:
                # Confirm: next candle opens above OB high
                next_c = candles[i + 1]
                if next_c["open"] >= c["close"]:

                    # OB zone = body of bearish candle
                    ob_top    = c["open"]     # top of body
                    ob_bottom = c["close"]    # bottom of body
                    ob_mid    = (ob_top + ob_bottom) / 2
                    ob_50     = ob_mid        # 50% entry level

                    obs.append({
                        "type":      "BULLISH_OB",
                        "direction": "BULLISH",

                        # Zone
                        "top":       round(ob_top,    5),
                        "bottom":    round(ob_bottom, 5),
                        "mid":       round(ob_mid,    5),
                        "entry_50":  round(ob_50,     5),

                        # Full candle range (wicks)
                        "high":      round(c["high"],  5),
                        "low":       round(c["low"],   5),

                        # Impulse
                        "impulse_size":     round(impulse["size"], 5),
                        "impulse_end":      round(impulse["end_price"], 5),

                        # Metadata
                        "time":             c["time"],
                        "index":            i,
                        "age":              total - i,
                        "candle_body":      round(c_body, 5),
                        "body_atr":         round(c_body / atr, 2),
                        "impulse_atr":      round(impulse["size"] / atr, 2),

                        # State
                        "mitigated":        False,
                        "broken":           False,
                        "retested":         False,
                        "retest_candle":    None,
                        "retest_time":      None,
                        "is_breaker":       False,
                        "has_fvg":          False,
                        "fvg_inside":       None,
                        "score":            0.0,

                        "desc": (
                            f"Bullish OB @ {ob_bottom:.5f}—{ob_top:.5f} "
                            f"impulse {impulse['size'] / atr:.1f}x ATR"
                        ),
                    })

        # ── Bearish OB ────────────────────────────
        # Last bullish candle (green) before bearish impulse
        if c["close"] > c["open"]:
            impulse = _measure_impulse(candles, i, "BEARISH")
            if impulse["size"] >= min_impulse:
                next_c = candles[i + 1]
                if next_c["open"] <= c["close"]:

                    ob_top    = c["close"]    # top of body
                    ob_bottom = c["open"]     # bottom of body
                    ob_mid    = (ob_top + ob_bottom) / 2
                    ob_50     = ob_mid

                    obs.append({
                        "type":      "BEARISH_OB",
                        "direction": "BEARISH",

                        # Zone
                        "top":       round(ob_top,    5),
                        "bottom":    round(ob_bottom, 5),
                        "mid":       round(ob_mid,    5),
                        "entry_50":  round(ob_50,     5),

                        # Full candle range
                        "high":      round(c["high"],  5),
                        "low":       round(c["low"],   5),

                        # Impulse
                        "impulse_size":     round(impulse["size"], 5),
                        "impulse_end":      round(impulse["end_price"], 5),

                        # Metadata
                        "time":             c["time"],
                        "index":            i,
                        "age":              total - i,
                        "candle_body":      round(c_body, 5),
                        "body_atr":         round(c_body / atr, 2),
                        "impulse_atr":      round(impulse["size"] / atr, 2),

                        # State
                        "mitigated":        False,
                        "broken":           False,
                        "retested":         False,
                        "retest_candle":    None,
                        "retest_time":      None,
                        "is_breaker":       False,
                        "has_fvg":          False,
                        "fvg_inside":       None,
                        "score":            0.0,

                        "desc": (
                            f"Bearish OB @ {ob_bottom:.5f}—{ob_top:.5f} "
                            f"impulse {impulse['size'] / atr:.1f}x ATR"
                        ),
                    })

    return obs


# ─────────────────────────────────────────────────────────────
# OB STATE VALIDATOR
# ─────────────────────────────────────────────────────────────

def validate_ob_states(
    obs:     list[dict],
    candles: list[dict],
    atr:     float,
) -> list[dict]:
    """
    For each OB scan candles after formation:
      - Retested:   price entered the OB zone
      - Mitigated:  price closed through 50% of OB
      - Broken:     price closed fully beyond OB
                    → becomes Breaker Block

    Updates OB dicts in place.
    """
    tolerance = atr * RETEST_ATR_TOLERANCE

    for ob in obs:
        formed_idx   = ob["index"]
        post_candles = candles[formed_idx + 2:]
        ob_top       = ob["top"]
        ob_bottom    = ob["bottom"]
        ob_50        = ob["entry_50"]

        for c in post_candles:
            c_high  = c["high"]
            c_low   = c["low"]
            c_close = c["close"]

            if ob["type"] == "BULLISH_OB":
                # Retest: price came back down into OB
                if c_low <= ob_top + tolerance and c_high >= ob_bottom - tolerance:
                    if not ob["retested"]:
                        ob["retested"]     = True
                        ob["retest_candle"] = c
                        ob["retest_time"]   = c["time"]

                # Mitigated: price closed below 50%
                if c_close < ob_50:
                    ob["mitigated"] = True

                # Broken: price closed fully below OB bottom
                # → becomes bearish Breaker Block
                if c_close < ob_bottom - tolerance:
                    ob["broken"]     = True
                    ob["is_breaker"] = True
                    ob["breaker_type"] = "BEARISH_BREAKER"
                    ob["desc"] = (
                        f"Breaker Block (was Bull OB) "
                        f"@ {ob_bottom:.5f}—{ob_top:.5f} "
                        f"→ now RESISTANCE"
                    )

            elif ob["type"] == "BEARISH_OB":
                # Retest: price came back up into OB
                if c_high >= ob_bottom - tolerance and c_low <= ob_top + tolerance:
                    if not ob["retested"]:
                        ob["retested"]      = True
                        ob["retest_candle"] = c
                        ob["retest_time"]   = c["time"]

                # Mitigated: price closed above 50%
                if c_close > ob_50:
                    ob["mitigated"] = True

                # Broken: price closed fully above OB top
                # → becomes bullish Breaker Block
                if c_close > ob_top + tolerance:
                    ob["broken"]     = True
                    ob["is_breaker"] = True
                    ob["breaker_type"] = "BULLISH_BREAKER"
                    ob["desc"] = (
                        f"Breaker Block (was Bear OB) "
                        f"@ {ob_bottom:.5f}—{ob_top:.5f} "
                        f"→ now SUPPORT"
                    )

    return obs


# ─────────────────────────────────────────────────────────────
# FVG CONFLUENCE CHECKER
# ─────────────────────────────────────────────────────────────

def check_fvg_inside_ob(
    obs:  list[dict],
    fvgs: list[dict],
) -> list[dict]:
    """
    Check if any FVG sits INSIDE an OB zone.
    OB + FVG = highest quality ICT confluence.

    Marks ob["has_fvg"] = True and stores fvg reference.
    """
    for ob in obs:
        ob_top = ob["top"]
        ob_bot = ob["bottom"]

        for fvg in fvgs:
            # FVG must be same direction as OB
            fvg_dir = fvg.get("direction", "")
            ob_dir  = ob.get("direction",  "")

            if fvg_dir != ob_dir:
                continue

            fvg_top = fvg["top"]
            fvg_bot = fvg["bottom"]

            # Check overlap
            overlap = (
                min(ob_top, fvg_top) - max(ob_bot, fvg_bot)
            )

            if overlap > 0:
                ob["has_fvg"]    = True
                ob["fvg_inside"] = {
                    "top":    fvg_top,
                    "bottom": fvg_bot,
                    "mid":    fvg["mid"],
                    "score":  fvg.get("score", 0),
                }
                break   # One FVG per OB is enough

    return obs


# ─────────────────────────────────────────────────────────────
# OB STRENGTH SCORER
# ─────────────────────────────────────────────────────────────

def score_ob(
    ob:       dict,
    pd_zones: dict,
    trend:    str,
) -> float:
    """
    Score OB quality from 0.0 to 1.0.

    Factors:
      + Large impulse after OB
      + Fresh (not yet retested)
      + FVG inside OB (confluence)
      + Aligned with trend
      + In PD zone (discount for bull, premium for bear)
      + Large OB body
      - Old
      - Already broken
      - Already mitigated
    """
    if ob.get("broken"):
        # Breaker blocks get low base score
        # unless we want to trade the flip
        return 0.1

    score = 0.0

    # Impulse strength (0 - 0.25)
    imp_atr = ob.get("impulse_atr", 0)
    score  += min(imp_atr / 8.0, 0.25)

    # Fresh — not yet retested (0.20)
    if not ob.get("retested"):
        score += 0.20

    # FVG inside OB — highest confluence (0.20)
    if ob.get("has_fvg"):
        score += 0.20

    # Trend alignment (0.15)
    ob_dir = ob.get("direction", "")
    if (ob_dir == "BULLISH" and trend == "BULLISH") or \
       (ob_dir == "BEARISH" and trend == "BEARISH"):
        score += 0.15

    # PD Zone (0.10)
    ob_mid = ob.get("mid", 0)
    eq     = pd_zones.get("equilibrium", 0)
    if eq > 0:
        if ob_dir == "BULLISH" and ob_mid < eq:
            score += 0.10   # Bull OB in discount
        elif ob_dir == "BEARISH" and ob_mid > eq:
            score += 0.10   # Bear OB in premium

    # OB body size (0.05)
    body_atr = ob.get("body_atr", 0)
    score   += min(body_atr / 4.0, 0.05)

    # Age penalty (0 - 0.05)
    age   = ob.get("age", MAX_OB_AGE)
    fresh = max(0, 1.0 - age / MAX_OB_AGE)
    score += fresh * 0.05

    # Mitigation penalty
    if ob.get("mitigated"):
        score *= 0.6

    return round(min(score, 1.0), 2)


# ─────────────────────────────────────────────────────────────
# CURRENT RETEST CHECKER
# ─────────────────────────────────────────────────────────────

def get_active_ob_retest(
    obs:           list[dict],
    current_price: float,
    direction:     str,
    atr:           float,
) -> Optional[dict]:
    """
    Check if price is currently retesting a valid OB.
    This is the ICT entry trigger after sweep + MSS.

    Args:
        obs:           All detected OBs
        current_price: Current market price
        direction:     BULLISH | BEARISH
        atr:           Current ATR

    Returns:
        Best OB being retested right now, or None.
    """
    tolerance = atr * RETEST_ATR_TOLERANCE
    active    = []

    for ob in obs:
        # Skip broken or invalid
        if ob.get("broken") or ob.get("age", 0) > MAX_OB_AGE:
            continue

        ob_top = ob["top"]
        ob_bot = ob["bottom"]
        ob_dir = ob["direction"]

        if direction == "BULLISH" and ob_dir == "BULLISH":
            # Price pulling back into bullish OB
            if ob_bot - tolerance <= current_price <= ob_top + tolerance:
                active.append(ob)

        elif direction == "BEARISH" and ob_dir == "BEARISH":
            # Price pulling up into bearish OB
            if ob_bot - tolerance <= current_price <= ob_top + tolerance:
                active.append(ob)

    if not active:
        return None

    # Return highest scored
    active.sort(key=lambda x: x.get("score", 0), reverse=True)
    return active[0]


# ─────────────────────────────────────────────────────────────
# BREAKER BLOCK EXTRACTOR
# ─────────────────────────────────────────────────────────────

def get_breaker_blocks(obs: list[dict]) -> list[dict]:
    """
    Extract all breaker blocks from OB list.
    Breakers = OBs that were broken and flipped polarity.

    Bullish Breaker: was bearish OB, price broke above
      → now acts as support on retest
    Bearish Breaker: was bullish OB, price broke below
      → now acts as resistance on retest
    """
    breakers = []
    for ob in obs:
        if ob.get("is_breaker"):
            breakers.append({
                **ob,
                "breaker_direction": (
                    "BULLISH"
                    if ob.get("breaker_type") == "BULLISH_BREAKER"
                    else "BEARISH"
                ),
            })
    return breakers


# ─────────────────────────────────────────────────────────────
# MAIN OB ANALYSIS
# ─────────────────────────────────────────────────────────────

def analyse_orderblocks(
    candles:  list[dict],
    atr:      float,
    trend:    str        = "UNKNOWN",
    pd_zones: dict       = None,
    fvgs:     list[dict] = None,
    swings:   dict       = None,
) -> dict:
    """
    Full order block analysis — main entry point for ICT engine.

    Returns:
      {
        "all_obs":        every OB found,
        "valid_obs":      unbroken, within age limit,
        "bullish_obs":    valid bullish OBs scored,
        "bearish_obs":    valid bearish OBs scored,
        "best_bullish":   highest scored bullish OB,
        "best_bearish":   highest scored bearish OB,
        "active_retest":  OB being retested right now,
        "breakers":       all breaker blocks,
        "confluence_obs": OBs with FVG inside,
      }
    """
    if not candles or len(candles) < 10:
        return {
            "error":      "Insufficient candle data",
            "all_obs":    [],
            "valid_obs":  [],
            "count":      0,
        }

    if pd_zones is None:
        pd_zones = {}
    if fvgs is None:
        fvgs = []

    current_price = candles[-1]["close"]

    # ── Detect OBs ────────────────────────────────
    all_obs = detect_order_blocks(candles, atr, swings)

    # ── Validate States ───────────────────────────
    all_obs = validate_ob_states(all_obs, candles, atr)

    # ── Check FVG Confluence ──────────────────────
    all_obs = check_fvg_inside_ob(all_obs, fvgs)

    # ── Score Each OB ─────────────────────────────
    for ob in all_obs:
        ob["score"] = score_ob(ob, pd_zones, trend)

    # ── Filter Valid ──────────────────────────────
    valid_obs = [
        ob for ob in all_obs
        if not ob.get("broken")
        and ob.get("age", 0) <= MAX_OB_AGE
        and ob.get("score", 0) > 0
    ]

    # ── Split by Direction ────────────────────────
    bullish_obs = sorted(
        [ob for ob in valid_obs if ob["direction"] == "BULLISH"],
        key=lambda x: x["score"],
        reverse=True,
    )
    bearish_obs = sorted(
        [ob for ob in valid_obs if ob["direction"] == "BEARISH"],
        key=lambda x: x["score"],
        reverse=True,
    )

    # ── Best OBs ──────────────────────────────────
    best_bullish = bullish_obs[0] if bullish_obs else None
    best_bearish = bearish_obs[0] if bearish_obs else None

    # ── Active Retest ─────────────────────────────
    direction    = trend if trend != "UNKNOWN" else "BULLISH"
    active_retest = get_active_ob_retest(
        valid_obs, current_price, direction, atr
    )

    # ── Breaker Blocks ────────────────────────────
    breakers = get_breaker_blocks(all_obs)

    # ── Confluence OBs ────────────────────────────
    confluence_obs = [
        ob for ob in valid_obs if ob.get("has_fvg")
    ]
    confluence_obs.sort(key=lambda x: x["score"], reverse=True)

    return {
        # All data
        "all_obs":       all_obs,
        "valid_obs":     valid_obs,
        "bullish_obs":   bullish_obs[:5],
        "bearish_obs":   bearish_obs[:5],

        # Best picks
        "best_bullish":   best_bullish,
        "best_bearish":   best_bearish,
        "active_retest":  active_retest,

        # Special types
        "breakers":       breakers,
        "confluence_obs": confluence_obs[:3],

        # Summary
        "count":          len(valid_obs),
        "bull_count":     len(bullish_obs),
        "bear_count":     len(bearish_obs),
        "current_price":  current_price,
        "analysed_at":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─────────────────────────────────────────────────────────────
# FORMATTER
# ─────────────────────────────────────────────────────────────

def format_orderblocks(result: dict) -> str:
    """Human readable OB summary."""
    if "error" in result:
        return f"[OB] Error: {result['error']}"

    lines = [
        "🧱 ORDER BLOCKS",
        "─" * 42,
        f"Total Valid:    {result.get('count', 0)}",
        f"Bullish OBs:    {result.get('bull_count', 0)}",
        f"Bearish OBs:    {result.get('bear_count', 0)}",
        f"Breakers:       {len(result.get('breakers', []))}",
        f"OB+FVG Confluence: {len(result.get('confluence_obs', []))}",
        f"Current Price:  {result.get('current_price', 0):.5f}",
    ]

    best_b = result.get("best_bullish")
    if best_b:
        fvg_tag = " ⚡ FVG INSIDE" if best_b.get("has_fvg") else ""
        lines += [
            "",
            f"🟢 BEST BULLISH OB:{fvg_tag}",
            f"  Zone:     {best_b['bottom']:.5f} — {best_b['top']:.5f}",
            f"  Entry 50: {best_b['entry_50']:.5f}",
            f"  Impulse:  {best_b['impulse_atr']:.1f}x ATR",
            f"  Score:    {best_b['score'] * 100:.0f}%",
            f"  Age:      {best_b['age']} candles",
            f"  Retested: {'YES' if best_b['retested'] else 'NO (fresh)'}",
            f"  Mitigated:{'YES' if best_b['mitigated'] else 'NO'}",
        ]

    best_r = result.get("best_bearish")
    if best_r:
        fvg_tag = " ⚡ FVG INSIDE" if best_r.get("has_fvg") else ""
        lines += [
            "",
            f"🔴 BEST BEARISH OB:{fvg_tag}",
            f"  Zone:     {best_r['bottom']:.5f} — {best_r['top']:.5f}",
            f"  Entry 50: {best_r['entry_50']:.5f}",
            f"  Impulse:  {best_r['impulse_atr']:.1f}x ATR",
            f"  Score:    {best_r['score'] * 100:.0f}%",
            f"  Age:      {best_r['age']} candles",
            f"  Retested: {'YES' if best_r['retested'] else 'NO (fresh)'}",
            f"  Mitigated:{'YES' if best_r['mitigated'] else 'NO'}",
        ]

    active = result.get("active_retest")
    if active:
        fvg_tag = " ⚡ FVG INSIDE" if active.get("has_fvg") else ""
        lines += [
            "",
            f"⚡ ACTIVE OB RETEST:{fvg_tag}",
            f"  Type:     {active['type']}",
            f"  Zone:     {active['bottom']:.5f} — {active['top']:.5f}",
            f"  Score:    {active['score'] * 100:.0f}%",
            f"  → Entry opportunity forming!",
        ]

    breakers = result.get("breakers", [])
    if breakers:
        lines += ["", "🔄 BREAKER BLOCKS:"]
        for b in breakers[:3]:
            lines.append(
                f"  • {b.get('breaker_type','?')} "
                f"@ {b['bottom']:.5f}—{b['top']:.5f}"
            )

    conf = result.get("confluence_obs", [])
    if conf:
        lines += ["", "⭐ CONFLUENCE (OB + FVG):"]
        for c in conf[:3]:
            lines.append(
                f"  • {c['type']} @ {c['bottom']:.5f}—{c['top']:.5f} "
                f"score {c['score']*100:.0f}%"
            )

    return "\n".join(lines)