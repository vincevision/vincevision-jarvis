# actions/trading/market_structure.py
"""
Market Structure Engine
────────────────────────
Detects:
  - Swing Highs / Lows (ATR-sensitive)
  - BOS  (Break of Structure)
  - CHoCH (Change of Character)
  - MSS  (Market Structure Shift / reversal signal)
  - HTF Trend Bias
  - Continuation vs Reversal tagging
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

import numpy as np


# ─────────────────────────────────────────────────────────────
# ATR CALCULATOR
# ─────────────────────────────────────────────────────────────

def _atr(candles: list[dict], period: int = 14) -> float:
    """
    Calculate Average True Range for dynamic sensitivity.
    Used to filter out noise in swing detection.
    """
    if len(candles) < period + 1:
        # Fallback: use simple high-low average
        hl = [c["high"] - c["low"] for c in candles]
        return float(np.mean(hl)) if hl else 0.001

    true_ranges = []
    for i in range(1, len(candles)):
        c    = candles[i]
        prev = candles[i - 1]
        tr   = max(
            c["high"] - c["low"],
            abs(c["high"] - prev["close"]),
            abs(c["low"]  - prev["close"]),
        )
        true_ranges.append(tr)

    return float(np.mean(true_ranges[-period:]))


# ─────────────────────────────────────────────────────────────
# SWING HIGH / LOW DETECTION
# ─────────────────────────────────────────────────────────────

def find_swings(
    candles:  list[dict],
    lookback: int  = 5,
    atr_mult: float = 0.3,
) -> dict:
    """
    Detect swing highs and lows using ATR-based sensitivity.

    Args:
        candles:  OHLCV list of dicts
        lookback: bars left and right to confirm a swing
        atr_mult: minimum swing size as ATR multiple

    Returns:
        {
          "highs": [{"index", "price", "time", "strength"}, ...],
          "lows":  [{"index", "price", "time", "strength"}, ...],
        }
    """
    if len(candles) < lookback * 2 + 1:
        return {"highs": [], "lows": []}

    atr       = _atr(candles)
    min_swing = atr * atr_mult
    highs     = []
    lows      = []

    for i in range(lookback, len(candles) - lookback):
        current = candles[i]
        window  = candles[i - lookback : i + lookback + 1]

        max_high = max(c["high"] for c in window)
        min_low  = min(c["low"]  for c in window)

        # ── Swing High ───────────────────────────
        if current["high"] == max_high:
            # Check it's significant enough vs neighbours
            left_high  = max(c["high"] for c in candles[i - lookback : i])
            right_high = max(c["high"] for c in candles[i + 1 : i + lookback + 1])
            strength   = min(
                current["high"] - left_high,
                current["high"] - right_high,
            )
            if strength >= min_swing:
                # Avoid duplicate at same price level
                if not highs or abs(current["high"] - highs[-1]["price"]) > min_swing:
                    highs.append({
                        "index":    i,
                        "price":    current["high"],
                        "time":     current["time"],
                        "strength": round(strength / atr, 2),
                        "candle":   current,
                    })

        # ── Swing Low ────────────────────────────
        if current["low"] == min_low:
            left_low  = min(c["low"] for c in candles[i - lookback : i])
            right_low = min(c["low"] for c in candles[i + 1 : i + lookback + 1])
            strength  = min(
                left_low  - current["low"],
                right_low - current["low"],
            )
            if strength >= min_swing:
                if not lows or abs(current["low"] - lows[-1]["price"]) > min_swing:
                    lows.append({
                        "index":    i,
                        "price":    current["low"],
                        "time":     current["time"],
                        "strength": round(strength / atr, 2),
                        "candle":   current,
                    })

    return {"highs": highs, "lows": lows}


# ─────────────────────────────────────────────────────────────
# STRUCTURE CLASSIFIER
# ─────────────────────────────────────────────────────────────

def _classify_structure(
    highs: list[dict],
    lows:  list[dict],
) -> str:
    """
    Classify market structure from swing sequence.

    Returns: BULLISH | BEARISH | RANGING | UNKNOWN
    """
    if len(highs) < 2 or len(lows) < 2:
        return "UNKNOWN"

    # Use last 3 swings for classification
    h = highs[-3:] if len(highs) >= 3 else highs
    l = lows[-3:]  if len(lows)  >= 3 else lows

    # Higher Highs + Higher Lows = BULLISH
    hh = all(h[i]["price"] < h[i + 1]["price"] for i in range(len(h) - 1))
    hl = all(l[i]["price"] < l[i + 1]["price"] for i in range(len(l) - 1))

    # Lower Highs + Lower Lows = BEARISH
    lh = all(h[i]["price"] > h[i + 1]["price"] for i in range(len(h) - 1))
    ll = all(l[i]["price"] > l[i + 1]["price"] for i in range(len(l) - 1))

    if hh and hl:
        return "BULLISH"
    if lh and ll:
        return "BEARISH"

    # Partial alignment
    if hh or hl:
        return "BULLISH"
    if lh or ll:
        return "BEARISH"

    return "RANGING"


# ─────────────────────────────────────────────────────────────
# BOS / CHoCH / MSS DETECTOR
# ─────────────────────────────────────────────────────────────

def detect_structure_events(
    candles: list[dict],
    swings:  dict,
    lookback_events: int = 5,
) -> list[dict]:
    """
    Detect BOS, CHoCH, and MSS events.

    Definitions:
      BOS   — Break of Structure (trend continuation break)
      CHoCH — Change of Character (first sign of reversal)
      MSS   — Market Structure Shift (confirmed reversal)

    Each event:
      {
        "type":      BOS | CHoCH | MSS,
        "direction": BULLISH | BEARISH,
        "price":     level broken,
        "candle":    the breaking candle,
        "time":      candle time,
        "confirmed": True/False,
        "tag":       CONTINUATION | REVERSAL,
        "desc":      human readable,
      }
    """
    highs  = swings["highs"]
    lows   = swings["lows"]
    events = []

    if len(highs) < 2 or len(lows) < 2:
        return events

    trend = _classify_structure(highs, lows)

    # ── Scan recent candles for breaks ───────────
    scan_start = max(
        highs[-1]["index"] if highs else 0,
        lows[-1]["index"]  if lows  else 0,
    )
    recent_candles = candles[scan_start:]

    for i, candle in enumerate(recent_candles):
        close = candle["close"]
        high  = candle["high"]
        low   = candle["low"]

        # ── Bullish BOS: close above prev swing high ──
        if len(highs) >= 2:
            prev_high = highs[-2]["price"]
            last_high = highs[-1]["price"]

            # BOS in bullish trend (continuation)
            if trend == "BULLISH" and close > last_high:
                events.append({
                    "type":      "BOS",
                    "direction": "BULLISH",
                    "price":     last_high,
                    "candle":    candle,
                    "time":      candle["time"],
                    "confirmed": True,
                    "tag":       "CONTINUATION",
                    "desc":      (
                        f"Bullish BOS — price closed above "
                        f"{last_high:.5f} continuing uptrend"
                    ),
                })

            # CHoCH in bearish trend (first reversal sign)
            if trend == "BEARISH" and close > prev_high:
                events.append({
                    "type":      "CHoCH",
                    "direction": "BULLISH",
                    "price":     prev_high,
                    "candle":    candle,
                    "time":      candle["time"],
                    "confirmed": False,
                    "tag":       "REVERSAL",
                    "desc":      (
                        f"Bullish CHoCH — price breaking above "
                        f"{prev_high:.5f} in downtrend — watch for MSS"
                    ),
                })

            # MSS: CHoCH + close above last high = confirmed reversal
            if trend == "BEARISH" and close > last_high:
                events.append({
                    "type":      "MSS",
                    "direction": "BULLISH",
                    "price":     last_high,
                    "candle":    candle,
                    "time":      candle["time"],
                    "confirmed": True,
                    "tag":       "REVERSAL",
                    "desc":      (
                        f"Bullish MSS CONFIRMED — reversal above "
                        f"{last_high:.5f} — look for LONG retest"
                    ),
                })

        # ── Bearish BOS: close below prev swing low ───
        if len(lows) >= 2:
            prev_low = lows[-2]["price"]
            last_low = lows[-1]["price"]

            # BOS in bearish trend (continuation)
            if trend == "BEARISH" and close < last_low:
                events.append({
                    "type":      "BOS",
                    "direction": "BEARISH",
                    "price":     last_low,
                    "candle":    candle,
                    "time":      candle["time"],
                    "confirmed": True,
                    "tag":       "CONTINUATION",
                    "desc":      (
                        f"Bearish BOS — price closed below "
                        f"{last_low:.5f} continuing downtrend"
                    ),
                })

            # CHoCH in bullish trend
            if trend == "BULLISH" and close < prev_low:
                events.append({
                    "type":      "CHoCH",
                    "direction": "BEARISH",
                    "price":     prev_low,
                    "candle":    candle,
                    "time":      candle["time"],
                    "confirmed": False,
                    "tag":       "REVERSAL",
                    "desc":      (
                        f"Bearish CHoCH — price breaking below "
                        f"{prev_low:.5f} in uptrend — watch for MSS"
                    ),
                })

            # MSS confirmed bearish reversal
            if trend == "BULLISH" and close < last_low:
                events.append({
                    "type":      "MSS",
                    "direction": "BEARISH",
                    "price":     last_low,
                    "candle":    candle,
                    "time":      candle["time"],
                    "confirmed": True,
                    "tag":       "REVERSAL",
                    "desc":      (
                        f"Bearish MSS CONFIRMED — reversal below "
                        f"{last_low:.5f} — look for SHORT retest"
                    ),
                })

    # Deduplicate — keep last of each type
    seen   = {}
    unique = []
    for e in events:
        key = f"{e['type']}_{e['direction']}"
        seen[key] = e
    unique = list(seen.values())

    return unique[-lookback_events:]


# ─────────────────────────────────────────────────────────────
# HTF BIAS ENGINE
# ─────────────────────────────────────────────────────────────

def get_htf_bias(
    htf_candles: list[dict],
    lookback:    int = 5,
) -> dict:
    """
    Determine Higher Timeframe bias.
    Used to filter LTF entries — only take trades
    aligned with HTF direction.

    Returns:
      {
        "bias":        BULLISH | BEARISH | RANGING | UNKNOWN,
        "strength":    0.0 - 1.0,
        "last_high":   float,
        "last_low":    float,
        "description": str,
        "trade_with":  LONG | SHORT | WAIT,
      }
    """
    if not htf_candles or len(htf_candles) < 20:
        return {
            "bias":        "UNKNOWN",
            "strength":    0.0,
            "last_high":   0.0,
            "last_low":    0.0,
            "description": "Insufficient HTF data",
            "trade_with":  "WAIT",
        }

    swings = find_swings(htf_candles, lookback=lookback)
    highs  = swings["highs"]
    lows   = swings["lows"]

    if not highs or not lows:
        return {
            "bias":        "UNKNOWN",
            "strength":    0.0,
            "last_high":   0.0,
            "last_low":    0.0,
            "description": "No clear swings on HTF",
            "trade_with":  "WAIT",
        }

    bias   = _classify_structure(highs, lows)
    events = detect_structure_events(htf_candles, swings)

    # Calculate bias strength (0 - 1)
    # Based on how many confirmations align
    score = 0.0
    total = 4.0

    h = highs[-3:] if len(highs) >= 3 else highs
    l = lows[-3:]  if len(lows)  >= 3 else lows

    if bias == "BULLISH":
        if all(h[i]["price"] < h[i+1]["price"] for i in range(len(h)-1)):
            score += 1.0   # HH
        if all(l[i]["price"] < l[i+1]["price"] for i in range(len(l)-1)):
            score += 1.0   # HL
        bos_count = sum(
            1 for e in events
            if e["type"] == "BOS" and e["direction"] == "BULLISH"
        )
        score += min(bos_count, 2) * 0.5
        trade_with = "LONG"

    elif bias == "BEARISH":
        if all(h[i]["price"] > h[i+1]["price"] for i in range(len(h)-1)):
            score += 1.0   # LH
        if all(l[i]["price"] > l[i+1]["price"] for i in range(len(l)-1)):
            score += 1.0   # LL
        bos_count = sum(
            1 for e in events
            if e["type"] == "BOS" and e["direction"] == "BEARISH"
        )
        score += min(bos_count, 2) * 0.5
        trade_with = "SHORT"

    else:
        score      = 0.3
        trade_with = "WAIT"

    strength = round(min(score / total, 1.0), 2)

    # Recent MSS overrides bias
    mss_events = [e for e in events if e["type"] == "MSS"]
    if mss_events:
        last_mss   = mss_events[-1]
        bias       = last_mss["direction"]
        trade_with = "LONG" if bias == "BULLISH" else "SHORT"
        strength   = max(strength, 0.7)

    last_high = highs[-1]["price"] if highs else 0.0
    last_low  = lows[-1]["price"]  if lows  else 0.0

    desc_map = {
        "BULLISH": f"HTF bullish — HH/HL structure. Bias: LONG only.",
        "BEARISH": f"HTF bearish — LH/LL structure. Bias: SHORT only.",
        "RANGING": f"HTF ranging — wait for direction.",
        "UNKNOWN": f"HTF unclear — insufficient data.",
    }

    return {
        "bias":        bias,
        "strength":    strength,
        "last_high":   last_high,
        "last_low":    last_low,
        "description": desc_map.get(bias, ""),
        "trade_with":  trade_with,
        "events":      events,
        "swings":      swings,
    }


# ─────────────────────────────────────────────────────────────
# FULL STRUCTURE ANALYSIS
# ─────────────────────────────────────────────────────────────

def analyse_structure(
    candles:         list[dict],
    htf_candles:     Optional[list[dict]] = None,
    swing_lookback:  int   = 5,
    atr_mult:        float = 0.3,
) -> dict:
    """
    Full market structure analysis.
    Main entry point for the ICT engine.

    Returns complete structure dict with:
      - swings, trend, events
      - HTF bias (if htf_candles provided)
      - key levels (last high/low, prev high/low)
      - setup_type: REVERSAL | CONTINUATION | WAIT
    """
    if not candles or len(candles) < 20:
        return {
            "error":      "Insufficient candle data",
            "trend":      "UNKNOWN",
            "setup_type": "WAIT",
        }

    # ── LTF Structure ─────────────────────────────
    swings    = find_swings(candles, swing_lookback, atr_mult)
    highs     = swings["highs"]
    lows      = swings["lows"]
    trend     = _classify_structure(highs, lows)
    events    = detect_structure_events(candles, swings)
    atr_value = _atr(candles)

    last_high = highs[-1]["price"] if highs else candles[-1]["high"]
    last_low  = lows[-1]["price"]  if lows  else candles[-1]["low"]
    prev_high = highs[-2]["price"] if len(highs) >= 2 else last_high
    prev_low  = lows[-2]["price"]  if len(lows)  >= 2 else last_low

    # ── HTF Bias ──────────────────────────────────
    htf_bias = None
    if htf_candles:
        htf_bias = get_htf_bias(htf_candles, swing_lookback)

    # ── Determine Setup Type ──────────────────────
    mss_events   = [e for e in events if e["type"] == "MSS"]
    bos_events   = [e for e in events if e["type"] == "BOS"]
    choch_events = [e for e in events if e["type"] == "CHoCH"]

    if mss_events:
        last_mss   = mss_events[-1]
        setup_type = "REVERSAL"
        setup_dir  = last_mss["direction"]
    elif bos_events:
        last_bos   = bos_events[-1]
        setup_type = "CONTINUATION"
        setup_dir  = last_bos["direction"]
    elif choch_events:
        last_choch = choch_events[-1]
        setup_type = "REVERSAL"
        setup_dir  = last_choch["direction"]
    else:
        setup_type = "WAIT"
        setup_dir  = "NONE"

    # ── HTF Filter ────────────────────────────────
    htf_aligned = True
    if htf_bias and htf_bias["bias"] != "UNKNOWN":
        if setup_dir == "BULLISH" and htf_bias["trade_with"] == "SHORT":
            htf_aligned = False
        if setup_dir == "BEARISH" and htf_bias["trade_with"] == "LONG":
            htf_aligned = False

    return {
        # Core
        "trend":      trend,
        "setup_type": setup_type,
        "setup_dir":  setup_dir,
        "htf_aligned": htf_aligned,

        # Swings
        "swings":     swings,
        "last_high":  last_high,
        "last_low":   last_low,
        "prev_high":  prev_high,
        "prev_low":   prev_low,

        # Events
        "events":     events,
        "mss_events":   mss_events,
        "bos_events":   bos_events,
        "choch_events": choch_events,

        # HTF
        "htf_bias":   htf_bias,

        # Meta
        "atr":        atr_value,
        "candle_count": len(candles),
        "analysed_at":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─────────────────────────────────────────────────────────────
# FORMATTER
# ─────────────────────────────────────────────────────────────

def format_structure(result: dict) -> str:
    """Human readable structure summary."""
    if "error" in result:
        return f"[Structure] Error: {result['error']}"

    lines = [
        "🏗️  MARKET STRUCTURE",
        "─" * 42,
        f"Trend:       {result['trend']}",
        f"Setup Type:  {result['setup_type']}",
        f"Direction:   {result['setup_dir']}",
        f"HTF Aligned: {'✅ YES' if result['htf_aligned'] else '❌ NO (against HTF)'}",
        f"ATR:         {result['atr']:.5f}",
        "",
        f"Last High:   {result['last_high']:.5f}",
        f"Last Low:    {result['last_low']:.5f}",
        f"Prev High:   {result['prev_high']:.5f}",
        f"Prev Low:    {result['prev_low']:.5f}",
    ]

    if result["events"]:
        lines += ["", "Events:"]
        for e in result["events"][-5:]:
            confirmed = "✅" if e["confirmed"] else "⏳"
            lines.append(
                f"  {confirmed} [{e['type']}] {e['direction']} "
                f"@ {e['price']:.5f} — {e['tag']}"
            )

    htf = result.get("htf_bias")
    if htf:
        lines += [
            "", "📡 HTF BIAS",
            "─" * 42,
            f"Bias:       {htf['bias']}",
            f"Strength:   {htf['strength'] * 100:.0f}%",
            f"Trade With: {htf['trade_with']}",
            f"Note:       {htf['description']}",
        ]

    return "\n".join(lines)