# actions/trading/liquidity.py
"""
Liquidity Engine
─────────────────
Detects:
  - BSL  (Buy Side Liquidity)  — resting above swing highs
  - SSL  (Sell Side Liquidity) — resting below swing lows
  - Equal Highs / Equal Lows
  - Liquidity Sweeps (wick through + close back = confirmed)
  - Sweep Strength Scoring
  - Which sweep triggers the MSS (ICT sequence step 1)
  - Inducement levels
  - Stop Hunt detection
"""

from datetime import datetime
from typing   import Optional
import numpy  as np


# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────

# How close two highs/lows must be to be "equal" (as % of price)
EQUAL_LEVEL_TOLERANCE = 0.0015   # 0.15%

# Minimum wick ratio to confirm a sweep
# wick must be at least this % of the candle range
MIN_SWEEP_WICK_RATIO = 0.3

# How many candles back to look for equal levels
EQUAL_LEVEL_LOOKBACK = 50

# Minimum touches to confirm a liquidity pool
MIN_POOL_TOUCHES = 2


# ─────────────────────────────────────────────────────────────
# EQUAL HIGHS / EQUAL LOWS
# ─────────────────────────────────────────────────────────────

def _find_equal_levels(
    swings:    dict,
    tolerance: float = EQUAL_LEVEL_TOLERANCE,
) -> dict:
    """
    Find equal highs (BSL) and equal lows (SSL).
    Equal = two or more swing points at the same price level.

    Returns:
        {
          "equal_highs": [{"price", "touches", "indices", "desc"}, ...],
          "equal_lows":  [{"price", "touches", "indices", "desc"}, ...],
        }
    """
    highs = swings.get("highs", [])
    lows  = swings.get("lows",  [])

    equal_highs = []
    equal_lows  = []
    used_h      = set()
    used_l      = set()

    # ── Equal Highs ───────────────────────────────
    for i, h1 in enumerate(highs):
        if i in used_h:
            continue
        group   = [h1]
        indices = [i]
        for j, h2 in enumerate(highs):
            if j == i or j in used_h:
                continue
            diff = abs(h1["price"] - h2["price"]) / h1["price"]
            if diff <= tolerance:
                group.append(h2)
                indices.append(j)

        if len(group) >= MIN_POOL_TOUCHES:
            avg_price = float(np.mean([g["price"] for g in group]))
            equal_highs.append({
                "price":   avg_price,
                "touches": len(group),
                "indices": indices,
                "times":   [g["time"] for g in group],
                "type":    "BSL",
                "desc":    (
                    f"Equal Highs BSL @ {avg_price:.5f} "
                    f"({len(group)} touches) — "
                    f"Buy stops resting above"
                ),
                "swept":   False,
                "sweep_candle": None,
            })
            for idx in indices:
                used_h.add(idx)

    # ── Equal Lows ────────────────────────────────
    for i, l1 in enumerate(lows):
        if i in used_l:
            continue
        group   = [l1]
        indices = [i]
        for j, l2 in enumerate(lows):
            if j == i or j in used_l:
                continue
            diff = abs(l1["price"] - l2["price"]) / l1["price"]
            if diff <= tolerance:
                group.append(l2)
                indices.append(j)

        if len(group) >= MIN_POOL_TOUCHES:
            avg_price = float(np.mean([g["price"] for g in group]))
            equal_lows.append({
                "price":   avg_price,
                "touches": len(group),
                "indices": indices,
                "times":   [g["time"] for g in group],
                "type":    "SSL",
                "desc":    (
                    f"Equal Lows SSL @ {avg_price:.5f} "
                    f"({len(group)} touches) — "
                    f"Sell stops resting below"
                ),
                "swept":        False,
                "sweep_candle": None,
            })
            for idx in indices:
                used_l.add(idx)

    return {
        "equal_highs": equal_highs,
        "equal_lows":  equal_lows,
    }


# ─────────────────────────────────────────────────────────────
# LIQUIDITY POOL BUILDER
# ─────────────────────────────────────────────────────────────

def _build_liquidity_pools(
    swings:    dict,
    candles:   list[dict],
    tolerance: float = EQUAL_LEVEL_TOLERANCE,
) -> list[dict]:
    """
    Build all liquidity pools from swing highs/lows.
    Each swing high = potential BSL pool
    Each swing low  = potential SSL pool

    Returns list of pool dicts sorted by price.
    """
    highs  = swings.get("highs", [])
    lows   = swings.get("lows",  [])
    pools  = []

    # Every swing high is a BSL (buy stops above it)
    for h in highs:
        pools.append({
            "type":         "BSL",
            "price":        h["price"],
            "time":         h["time"],
            "index":        h["index"],
            "strength":     h.get("strength", 1.0),
            "swept":        False,
            "sweep_candle": None,
            "sweep_time":   None,
            "desc":         f"BSL @ {h['price']:.5f}",
        })

    # Every swing low is a SSL (sell stops below it)
    for l in lows:
        pools.append({
            "type":         "SSL",
            "price":        l["price"],
            "time":         l["time"],
            "index":        l["index"],
            "strength":     l.get("strength", 1.0),
            "swept":        False,
            "sweep_candle": None,
            "sweep_time":   None,
            "desc":         f"SSL @ {l['price']:.5f}",
        })

    # Sort by price descending
    pools.sort(key=lambda x: x["price"], reverse=True)
    return pools


# ─────────────────────────────────────────────────────────────
# SWEEP CONFIRMATION
# ─────────────────────────────────────────────────────────────

def _is_sweep_confirmed(
    candle:     dict,
    pool_price: float,
    pool_type:  str,
    atr:        float,
) -> dict:
    """
    Confirm if a candle swept a liquidity level.

    ICT Definition of a sweep:
      BSL Sweep: wick ABOVE the level + close BELOW it
      SSL Sweep: wick BELOW the level + close ABOVE it

    Returns:
      {
        "confirmed": bool,
        "strength":  0.0 - 1.0,
        "wick_size": float,
        "type":      "BSL_SWEPT" | "SSL_SWEPT",
        "desc":      str,
      }
    """
    c_open  = candle["open"]
    c_high  = candle["high"]
    c_low   = candle["low"]
    c_close = candle["close"]
    c_range = c_high - c_low

    if c_range == 0:
        return {"confirmed": False}

    if pool_type == "BSL":
        # Wick must go above BSL price
        if c_high <= pool_price:
            return {"confirmed": False}
        # Close must be back below BSL price (rejection)
        if c_close >= pool_price:
            return {"confirmed": False}

        wick_size  = c_high - max(c_open, c_close)
        wick_ratio = wick_size / c_range

        if wick_ratio < MIN_SWEEP_WICK_RATIO:
            return {"confirmed": False}

        # Strength = how far above the level price went
        overshoot = c_high - pool_price
        strength  = min(overshoot / atr, 1.0)

        return {
            "confirmed": True,
            "strength":  round(strength, 2),
            "wick_size": round(wick_size, 5),
            "overshoot": round(overshoot, 5),
            "type":      "BSL_SWEPT",
            "desc":      (
                f"BSL swept @ {pool_price:.5f} — "
                f"wick to {c_high:.5f}, closed @ {c_close:.5f} "
                f"— look for SELLS"
            ),
        }

    elif pool_type == "SSL":
        # Wick must go below SSL price
        if c_low >= pool_price:
            return {"confirmed": False}
        # Close must be back above SSL price (rejection)
        if c_close <= pool_price:
            return {"confirmed": False}

        wick_size  = min(c_open, c_close) - c_low
        wick_ratio = wick_size / c_range

        if wick_ratio < MIN_SWEEP_WICK_RATIO:
            return {"confirmed": False}

        overshoot = pool_price - c_low
        strength  = min(overshoot / atr, 1.0)

        return {
            "confirmed": True,
            "strength":  round(strength, 2),
            "wick_size": round(wick_size, 5),
            "overshoot": round(overshoot, 5),
            "type":      "SSL_SWEPT",
            "desc":      (
                f"SSL swept @ {pool_price:.5f} — "
                f"wick to {c_low:.5f}, closed @ {c_close:.5f} "
                f"— look for BUYS"
            ),
        }

    return {"confirmed": False}


# ─────────────────────────────────────────────────────────────
# SWEEP SCANNER
# ─────────────────────────────────────────────────────────────

def scan_sweeps(
    candles:   list[dict],
    pools:     list[dict],
    atr:       float,
    lookback:  int = 20,
) -> list[dict]:
    """
    Scan recent candles for confirmed liquidity sweeps.

    Args:
        candles:  Full candle list
        pools:    Liquidity pools from _build_liquidity_pools()
        atr:      Current ATR value
        lookback: How many recent candles to check

    Returns:
        List of confirmed sweep events, most recent last.
    """
    sweeps       = []
    recent       = candles[-lookback:]
    recent_start = len(candles) - lookback

    for pool in pools:
        pool_idx = pool.get("index", 0)

        for i, candle in enumerate(recent):
            candle_idx = recent_start + i

            # Only check candles AFTER the pool formed
            if candle_idx <= pool_idx:
                continue

            result = _is_sweep_confirmed(
                candle,
                pool["price"],
                pool["type"],
                atr,
            )

            if result.get("confirmed"):
                sweep_event = {
                    # Pool info
                    "pool_type":  pool["type"],
                    "pool_price": pool["price"],
                    "pool_time":  pool["time"],

                    # Sweep info
                    "type":       result["type"],
                    "strength":   result["strength"],
                    "wick_size":  result["wick_size"],
                    "overshoot":  result["overshoot"],
                    "desc":       result["desc"],

                    # Candle that swept
                    "candle":     candle,
                    "time":       candle["time"],
                    "candle_idx": candle_idx,

                    # Direction bias after sweep
                    "bias_after": (
                        "BEARISH" if result["type"] == "BSL_SWEPT"
                        else "BULLISH"
                    ),

                    # ICT sequence flag
                    "mss_expected": True,
                    "retest_expected": True,
                }

                # Mark pool as swept
                pool["swept"]        = True
                pool["sweep_candle"] = candle
                pool["sweep_time"]   = candle["time"]

                sweeps.append(sweep_event)

    # Sort by candle index (most recent last)
    sweeps.sort(key=lambda x: x["candle_idx"])
    return sweeps


# ─────────────────────────────────────────────────────────────
# INDUCEMENT DETECTOR
# ─────────────────────────────────────────────────────────────

def detect_inducement(
    candles:   list[dict],
    swings:    dict,
    trend:     str,
    atr:       float,
) -> list[dict]:
    """
    Detect inducement levels (IDM).
    Inducement = minor liquidity taken before the real sweep.
    Confirms smart money is engineering liquidity.

    In uptrend:  IDM = minor low taken before sweeping BSL
    In downtrend: IDM = minor high taken before sweeping SSL
    """
    highs      = swings.get("highs", [])
    lows       = swings.get("lows",  [])
    inducement = []
    min_size   = atr * 0.5

    if trend == "BULLISH" and len(lows) >= 3:
        # Look for a minor low being taken (IDM)
        for i in range(len(lows) - 2):
            l1 = lows[i]
            l2 = lows[i + 1]
            l3 = lows[i + 2] if i + 2 < len(lows) else None

            # Minor low between two higher lows
            if l2["price"] < l1["price"] and (
                l3 is None or l3["price"] > l2["price"]
            ):
                inducement.append({
                    "type":  "IDM_LOW",
                    "price": l2["price"],
                    "time":  l2["time"],
                    "desc":  (
                        f"Inducement low @ {l2['price']:.5f} — "
                        f"minor SSL before major BSL run"
                    ),
                })

    if trend == "BEARISH" and len(highs) >= 3:
        for i in range(len(highs) - 2):
            h1 = highs[i]
            h2 = highs[i + 1]
            h3 = highs[i + 2] if i + 2 < len(highs) else None

            if h2["price"] > h1["price"] and (
                h3 is None or h3["price"] < h2["price"]
            ):
                inducement.append({
                    "type":  "IDM_HIGH",
                    "price": h2["price"],
                    "time":  h2["time"],
                    "desc":  (
                        f"Inducement high @ {h2['price']:.5f} — "
                        f"minor BSL before major SSL run"
                    ),
                })

    return inducement[-3:]


# ─────────────────────────────────────────────────────────────
# NEXT TARGET LIQUIDITY
# ─────────────────────────────────────────────────────────────

def get_next_liquidity_target(
    pools:         list[dict],
    current_price: float,
    direction:     str,
    min_distance:  float = 0.0,
) -> Optional[dict]:
    """
    Find the next liquidity target in the trade direction.

    LONG  → next BSL above price (buy stops to target)
    SHORT → next SSL below price (sell stops to target)

    Args:
        pools:         All liquidity pools
        current_price: Current market price
        direction:     BULLISH | BEARISH
        min_distance:  Minimum distance from price (ATR units)

    Returns:
        The nearest unswept pool in trade direction.
    """
    candidates = []

    if direction == "BULLISH":
        # Target BSL above current price
        candidates = [
            p for p in pools
            if p["type"] == "BSL"
            and p["price"] > current_price + min_distance
            and not p["swept"]
        ]
        # Sort ascending — nearest first
        candidates.sort(key=lambda x: x["price"])

    elif direction == "BEARISH":
        # Target SSL below current price
        candidates = [
            p for p in pools
            if p["type"] == "SSL"
            and p["price"] < current_price - min_distance
            and not p["swept"]
        ]
        # Sort descending — nearest first
        candidates.sort(key=lambda x: x["price"], reverse=True)

    return candidates[0] if candidates else None


# ─────────────────────────────────────────────────────────────
# PREMIUM / DISCOUNT ZONES
# ─────────────────────────────────────────────────────────────

def get_pd_zones(
    last_high: float,
    last_low:  float,
) -> dict:
    """
    Calculate Premium and Discount zones.
    Used to filter OB/FVG entries.

    Premium  = above 50% — only look for SELLS here
    Discount = below 50% — only look for BUYS here
    EQ       = 50% equilibrium
    """
    rng  = last_high - last_low
    eq   = last_low + rng * 0.5
    prem = last_low + rng * 0.618

    return {
        "equilibrium":   round(eq,   5),
        "premium_start": round(prem, 5),
        "premium_top":   round(last_high, 5),
        "discount_end":  round(eq - (rng * 0.118), 5),
        "discount_bot":  round(last_low,  5),
        "ote_high":      round(last_low + rng * 0.786, 5),
        "ote_low":       round(last_low + rng * 0.618, 5),
        "range":         round(rng, 5),
        "desc": (
            f"EQ: {eq:.5f} | "
            f"Premium: {prem:.5f}+ | "
            f"Discount: below {eq:.5f}"
        ),
    }


# ─────────────────────────────────────────────────────────────
# MAIN LIQUIDITY ANALYSIS
# ─────────────────────────────────────────────────────────────

def analyse_liquidity(
    candles:       list[dict],
    swings:        dict,
    atr:           float,
    trend:         str        = "UNKNOWN",
    sweep_lookback: int       = 30,
) -> dict:
    """
    Full liquidity analysis.
    Main entry point for the ICT engine.

    Returns:
      {
        "pools":          all BSL/SSL pools,
        "equal_highs":    equal high clusters (strong BSL),
        "equal_lows":     equal low clusters (strong SSL),
        "sweeps":         confirmed sweep events,
        "last_sweep":     most recent sweep,
        "inducement":     IDM levels,
        "pd_zones":       premium/discount zones,
        "next_target":    next liquidity target,
        "bias_after_sweep": BULLISH | BEARISH | NONE,
      }
    """
    if not candles or not swings:
        return {
            "error":   "No candle or swing data",
            "pools":   [],
            "sweeps":  [],
        }

    current_price = candles[-1]["close"]

    # ── Build Pools ───────────────────────────────
    pools = _build_liquidity_pools(swings, candles)

    # ── Equal Levels ──────────────────────────────
    equal_levels = _find_equal_levels(swings)

    # ── Scan for Sweeps ───────────────────────────
    sweeps = scan_sweeps(candles, pools, atr, lookback=sweep_lookback)

    # ── Most Recent Sweep ─────────────────────────
    last_sweep        = sweeps[-1] if sweeps else None
    bias_after_sweep  = "NONE"

    if last_sweep:
        bias_after_sweep = last_sweep["bias_after"]

    # ── Inducement ────────────────────────────────
    inducement = detect_inducement(candles, swings, trend, atr)

    # ── Premium / Discount ────────────────────────
    highs    = swings.get("highs", [])
    lows     = swings.get("lows",  [])
    last_h   = highs[-1]["price"] if highs else current_price * 1.01
    last_l   = lows[-1]["price"]  if lows  else current_price * 0.99
    pd_zones = get_pd_zones(last_h, last_l)

    # ── Next Target ───────────────────────────────
    direction    = bias_after_sweep if bias_after_sweep != "NONE" else trend
    next_target  = get_next_liquidity_target(
        pools, current_price, direction, atr * 2
    )

    # ── Unswept Pools Near Price ──────────────────
    atr_3 = atr * 3
    nearby_bsl = [
        p for p in pools
        if p["type"] == "BSL"
        and not p["swept"]
        and current_price < p["price"] < current_price + atr_3
    ]
    nearby_ssl = [
        p for p in pools
        if p["type"] == "SSL"
        and not p["swept"]
        and current_price - atr_3 < p["price"] < current_price
    ]

    return {
        # All pools
        "pools":          pools,
        "bsl_pools":      [p for p in pools if p["type"] == "BSL"],
        "ssl_pools":      [p for p in pools if p["type"] == "SSL"],

        # Equal levels (strongest pools)
        "equal_highs":    equal_levels["equal_highs"],
        "equal_lows":     equal_levels["equal_lows"],

        # Sweeps
        "sweeps":              sweeps,
        "last_sweep":          last_sweep,
        "bias_after_sweep":    bias_after_sweep,

        # Nearby unswept
        "nearby_bsl":     nearby_bsl[:3],
        "nearby_ssl":     nearby_ssl[:3],

        # Supporting
        "inducement":     inducement,
        "pd_zones":       pd_zones,
        "next_target":    next_target,

        # Meta
        "current_price":  current_price,
        "analysed_at":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─────────────────────────────────────────────────────────────
# FORMATTER
# ─────────────────────────────────────────────────────────────

def format_liquidity(result: dict) -> str:
    """Human readable liquidity summary."""
    if "error" in result:
        return f"[Liquidity] Error: {result['error']}"

    lines = [
        "💧 LIQUIDITY ANALYSIS",
        "─" * 42,
        f"Current Price:  {result.get('current_price', 0):.5f}",
        f"BSL Pools:      {len(result.get('bsl_pools', []))}",
        f"SSL Pools:      {len(result.get('ssl_pools', []))}",
        f"Equal Highs:    {len(result.get('equal_highs', []))}",
        f"Equal Lows:     {len(result.get('equal_lows',  []))}",
        f"Sweeps Found:   {len(result.get('sweeps', []))}",
        f"Bias After:     {result.get('bias_after_sweep', 'NONE')}",
    ]

    last = result.get("last_sweep")
    if last:
        lines += [
            "",
            "🎯 LAST SWEEP:",
            f"  Type:     {last['type']}",
            f"  Price:    {last['pool_price']:.5f}",
            f"  Time:     {last['time']}",
            f"  Strength: {last['strength'] * 100:.0f}%",
            f"  Desc:     {last['desc']}",
        ]

    target = result.get("next_target")
    if target:
        lines += [
            "",
            "🏹 NEXT TARGET:",
            f"  Type:  {target['type']}",
            f"  Price: {target['price']:.5f}",
            f"  Desc:  {target['desc']}",
        ]

    pd = result.get("pd_zones", {})
    if pd:
        lines += [
            "",
            "📊 PREMIUM / DISCOUNT:",
            f"  {pd.get('desc', '')}",
            f"  OTE Zone: {pd.get('ote_low', 0):.5f} — "
            f"{pd.get('ote_high', 0):.5f}",
        ]

    idm = result.get("inducement", [])
    if idm:
        lines += ["", "🎭 INDUCEMENT:"]
        for i in idm:
            lines.append(f"  • {i['desc']}")

    return "\n".join(lines)