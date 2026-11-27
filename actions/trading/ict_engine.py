# actions/trading/ict_engine.py
"""
ICT Sequence Engine
────────────────────
The brain of the trading system.
Validates the full ICT sequence:

  REVERSAL:
    1. Liquidity Sweep  (BSL or SSL taken)
    2. MSS / CHoCH      (market structure shifts)
    3. Retest of OB/FVG (price pulls back to entry zone)
    4. Target           (next opposing liquidity pool)

  CONTINUATION:
    1. BOS confirmed    (trend continues)
    2. Pullback to      (demand/supply zone)
    3. Sweep + MSS      (inside the zone)
    4. Retest of OB/FVG (entry on the zone retest)
    5. Target           (next liquidity in trend direction)

Outputs:
  - Setup type      (REVERSAL | CONTINUATION | WAIT)
  - Setup quality   (0.0 - 1.0)
  - Entry price     (OB 50% or FVG CE)
  - Stop loss       (beyond sweep wick or OB extreme)
  - TP1             (1:1 R:R)
  - TP2             (next liquidity target)
  - Confirmations   (list of what aligned)
  - Warnings        (list of what is missing)
"""

from datetime import datetime
from typing   import Optional
import numpy  as np

from actions.trading.market_structure import analyse_structure, format_structure
from actions.trading.liquidity        import analyse_liquidity,  format_liquidity
from actions.trading.fvg              import analyse_fvg,        format_fvg
from actions.trading.orderblock       import analyse_orderblocks, format_orderblocks


# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────

# Minimum setup quality to consider valid
MIN_SETUP_QUALITY   = 0.45

# Minimum R:R ratio to consider the trade
MIN_RR_RATIO        = 1.5

# Max candles between sweep and MSS
MAX_SWEEP_TO_MSS    = 10

# Max candles between MSS and retest
MAX_MSS_TO_RETEST   = 20

# SL buffer beyond sweep wick (ATR multiple)
SL_BUFFER_ATR       = 0.3

# Partial TP at 1:1
TP1_RR              = 1.0

# Max open trades
MAX_OPEN_TRADES     = 2


# ─────────────────────────────────────────────────────────────
# SEQUENCE VALIDATOR
# ─────────────────────────────────────────────────────────────

def _validate_reversal_sequence(
    structure:  dict,
    liquidity:  dict,
    fvg_data:   dict,
    ob_data:    dict,
    candles:    list[dict],
    atr:        float,
) -> dict:
    """
    Validate the full REVERSAL sequence:
    Sweep → MSS → Retest OB/FVG → Target next liquidity

    Returns sequence validation result.
    """
    result = {
        "valid":         False,
        "direction":     "NONE",
        "sequence":      [],
        "missing":       [],
        "confirmations": [],
        "warnings":      [],
        "score":         0.0,
        "entry_zone":    None,
        "stop_level":    None,
        "sweep_used":    None,
        "mss_used":      None,
        "entry_type":    None,  # OB | FVG | OB+FVG
    }

    last_sweep  = liquidity.get("last_sweep")
    mss_events  = structure.get("mss_events", [])
    events      = structure.get("events",     [])

    # ── Step 1: Liquidity Sweep ───────────────────
    if not last_sweep:
        result["missing"].append("No liquidity sweep detected")
        result["warnings"].append(
            "Wait for BSL or SSL to be swept before entry"
        )
        return result

    sweep_type = last_sweep["type"]          # BSL_SWEPT | SSL_SWEPT
    sweep_bias = last_sweep["bias_after"]    # BULLISH   | BEARISH
    sweep_candle_idx = last_sweep["candle_idx"]

    result["sequence"].append(
        f"✅ STEP 1: {sweep_type} @ {last_sweep['pool_price']:.5f} "
        f"— strength {last_sweep['strength']*100:.0f}%"
    )
    result["confirmations"].append(f"Liquidity sweep: {last_sweep['desc']}")
    result["sweep_used"] = last_sweep

    # ── Step 2: MSS After Sweep ───────────────────
    # Find MSS that happened AFTER the sweep
    mss_after_sweep = None
    for mss in mss_events:
        mss_candle = mss.get("candle", {})
        # MSS direction must match sweep bias
        if mss["direction"] == sweep_bias:
            mss_after_sweep = mss
            break

    if not mss_after_sweep:
        # Check for CHoCH as weaker confirmation
        choch_events = structure.get("choch_events", [])
        choch_aligned = [
            c for c in choch_events
            if c["direction"] == sweep_bias
        ]
        if choch_aligned:
            result["sequence"].append(
                f"⏳ STEP 2: CHoCH detected (MSS not yet confirmed) "
                f"@ {choch_aligned[-1]['price']:.5f}"
            )
            result["warnings"].append(
                "CHoCH seen but MSS not confirmed — wait for full shift"
            )
            result["score"] += 0.1
        else:
            result["missing"].append("No MSS after sweep")
            result["warnings"].append(
                f"Sweep done — waiting for {sweep_bias} MSS to confirm reversal"
            )
        return result

    result["sequence"].append(
        f"✅ STEP 2: MSS {mss_after_sweep['direction']} "
        f"@ {mss_after_sweep['price']:.5f} — reversal confirmed"
    )
    result["confirmations"].append(
        f"MSS confirmed: {mss_after_sweep['desc']}"
    )
    result["mss_used"]  = mss_after_sweep
    result["direction"] = sweep_bias
    result["score"]    += 0.25

    # ── Step 3: Retest OB or FVG ──────────────────
    current_price  = candles[-1]["close"]
    entry_zone     = None
    entry_type     = None
    stop_level     = None

    # Priority: OB+FVG confluence > OB alone > FVG alone
    active_ob  = ob_data.get("active_retest")
    active_fvg = fvg_data.get("active_retest")
    best_ob    = ob_data.get(
        f"best_{'bullish' if sweep_bias == 'BULLISH' else 'bearish'}"
    )
    best_fvg   = fvg_data.get(
        f"best_{'bullish' if sweep_bias == 'BULLISH' else 'bearish'}"
    )

    # Check confluence OBs first
    confluence = ob_data.get("confluence_obs", [])
    aligned_conf = [
        ob for ob in confluence
        if ob["direction"] == sweep_bias
    ]

    if active_ob and active_ob.get("has_fvg"):
        # Best case: OB + FVG being retested right now
        entry_zone = active_ob
        entry_type = "OB+FVG"
        result["sequence"].append(
            f"✅ STEP 3: OB+FVG confluence retest "
            f"@ {active_ob['bottom']:.5f}—{active_ob['top']:.5f}"
        )
        result["confirmations"].append(
            "Highest quality: OB with FVG inside — active retest"
        )
        result["score"] += 0.35

    elif active_ob:
        # OB retest active
        entry_zone = active_ob
        entry_type = "OB"
        result["sequence"].append(
            f"✅ STEP 3: OB retest active "
            f"@ {active_ob['bottom']:.5f}—{active_ob['top']:.5f}"
        )
        result["confirmations"].append("Order Block actively retested")
        result["score"] += 0.25

    elif active_fvg:
        # FVG retest active
        entry_zone = active_fvg
        entry_type = "FVG"
        result["sequence"].append(
            f"✅ STEP 3: FVG retest active "
            f"@ {active_fvg['bottom']:.5f}—{active_fvg['top']:.5f}"
        )
        result["confirmations"].append("Fair Value Gap actively retested")
        result["score"] += 0.20

    elif aligned_conf:
        # Confluence OB nearby — approaching
        entry_zone = aligned_conf[0]
        entry_type = "OB+FVG"
        result["sequence"].append(
            f"⏳ STEP 3: Approaching OB+FVG confluence "
            f"@ {aligned_conf[0]['bottom']:.5f}—{aligned_conf[0]['top']:.5f}"
        )
        result["warnings"].append(
            "Price approaching entry zone — wait for touch"
        )
        result["score"] += 0.15

    elif best_ob:
        # Best OB nearby — approaching
        entry_zone = best_ob
        entry_type = "OB"
        result["sequence"].append(
            f"⏳ STEP 3: Approaching OB "
            f"@ {best_ob['bottom']:.5f}—{best_ob['top']:.5f}"
        )
        result["warnings"].append(
            "Price approaching OB — wait for retest confirmation"
        )
        result["score"] += 0.10

    elif best_fvg:
        # Best FVG nearby
        entry_zone = best_fvg
        entry_type = "FVG"
        result["sequence"].append(
            f"⏳ STEP 3: Approaching FVG "
            f"@ {best_fvg['bottom']:.5f}—{best_fvg['top']:.5f}"
        )
        result["warnings"].append(
            "Price approaching FVG — wait for retest confirmation"
        )
        result["score"] += 0.08

    else:
        result["missing"].append("No OB or FVG retest found")
        result["warnings"].append(
            "Sweep + MSS confirmed but no entry zone found — "
            "wait for OB/FVG to form on LTF"
        )
        return result

    result["entry_zone"] = entry_zone
    result["entry_type"] = entry_type

    # ── Stop Loss ─────────────────────────────────
    sweep_wick = last_sweep["candle"]
    if sweep_bias == "BULLISH":
        # SL below sweep wick low
        stop_level = sweep_wick["low"] - (atr * SL_BUFFER_ATR)
    else:
        # SL above sweep wick high
        stop_level = sweep_wick["high"] + (atr * SL_BUFFER_ATR)

    result["stop_level"] = round(stop_level, 5)

    # ── HTF Alignment ─────────────────────────────
    htf_bias = structure.get("htf_bias")
    if htf_bias:
        htf_trade = htf_bias.get("trade_with", "WAIT")
        if htf_trade == "WAIT":
            result["warnings"].append(
                "HTF is ranging — reduced confidence"
            )
            result["score"] *= 0.8
        elif (
            (sweep_bias == "BULLISH" and htf_trade == "LONG") or
            (sweep_bias == "BEARISH" and htf_trade == "SHORT")
        ):
            result["confirmations"].append(
                f"HTF aligned: {htf_bias['bias']} "
                f"(strength {htf_bias['strength']*100:.0f}%)"
            )
            result["score"] += 0.15
        else:
            result["warnings"].append(
                f"⚠️ AGAINST HTF bias ({htf_bias['bias']}) — "
                f"reduce size or skip"
            )
            result["score"] *= 0.6

    # ── Final Validity ────────────────────────────
    result["valid"] = (
        result["score"] >= MIN_SETUP_QUALITY
        and entry_zone is not None
        and stop_level is not None
    )

    return result


def _validate_continuation_sequence(
    structure: dict,
    liquidity: dict,
    fvg_data:  dict,
    ob_data:   dict,
    candles:   list[dict],
    atr:       float,
) -> dict:
    """
    Validate the CONTINUATION sequence:
    BOS → Pullback to D/S zone → Sweep+MSS inside → Retest → Target

    Returns sequence validation result.
    """
    result = {
        "valid":         False,
        "direction":     "NONE",
        "sequence":      [],
        "missing":       [],
        "confirmations": [],
        "warnings":      [],
        "score":         0.0,
        "entry_zone":    None,
        "stop_level":    None,
        "sweep_used":    None,
        "mss_used":      None,
        "entry_type":    None,
    }

    trend      = structure.get("trend",      "UNKNOWN")
    bos_events = structure.get("bos_events", [])
    last_sweep = liquidity.get("last_sweep")
    pd_zones   = liquidity.get("pd_zones",   {})

    # ── Step 1: BOS Confirms Trend ────────────────
    aligned_bos = [
        b for b in bos_events
        if (b["direction"] == "BULLISH" and trend == "BULLISH") or
           (b["direction"] == "BEARISH" and trend == "BEARISH")
    ]

    if not aligned_bos:
        result["missing"].append("No BOS confirming trend direction")
        return result

    last_bos = aligned_bos[-1]
    result["sequence"].append(
        f"✅ STEP 1: BOS {last_bos['direction']} "
        f"@ {last_bos['price']:.5f} — trend confirmed"
    )
    result["confirmations"].append(f"BOS: {last_bos['desc']}")
    result["score"]    += 0.20
    result["direction"] = last_bos["direction"]

    # ── Step 2: Pullback to PD Zone ───────────────
    current_price = candles[-1]["close"]
    eq            = pd_zones.get("equilibrium", 0)
    in_discount   = current_price < eq and trend == "BULLISH"
    in_premium    = current_price > eq and trend == "BEARISH"

    if in_discount or in_premium:
        zone_name = "discount" if in_discount else "premium"
        result["sequence"].append(
            f"✅ STEP 2: Price in {zone_name} zone "
            f"(EQ: {eq:.5f})"
        )
        result["confirmations"].append(
            f"Price pulled back to {zone_name} zone"
        )
        result["score"] += 0.20
    else:
        result["sequence"].append(
            f"⏳ STEP 2: Waiting for pullback to "
            f"{'discount' if trend == 'BULLISH' else 'premium'} zone"
        )
        result["warnings"].append(
            f"Price not yet in optimal zone (EQ: {eq:.5f})"
        )
        result["score"] += 0.05

    # ── Step 3: Sweep + MSS Inside Zone ──────────
    if last_sweep:
        sweep_bias = last_sweep["bias_after"]
        is_aligned = (
            (sweep_bias == "BULLISH" and trend == "BULLISH") or
            (sweep_bias == "BEARISH" and trend == "BEARISH")
        )
        if is_aligned:
            result["sequence"].append(
                f"✅ STEP 3: Sweep inside zone: "
                f"{last_sweep['type']} @ {last_sweep['pool_price']:.5f}"
            )
            result["confirmations"].append(
                f"Zone sweep confirmed: {last_sweep['desc']}"
            )
            result["score"]    += 0.20
            result["sweep_used"] = last_sweep
        else:
            result["warnings"].append(
                "Sweep direction does not match trend"
            )
    else:
        result["sequence"].append(
            "⏳ STEP 3: Waiting for sweep inside zone"
        )
        result["warnings"].append(
            "No sweep detected inside demand/supply zone yet"
        )

    # ── Step 4: OB/FVG Retest ─────────────────────
    mss_events = structure.get("mss_events", [])
    active_ob  = ob_data.get("active_retest")
    active_fvg = fvg_data.get("active_retest")
    best_ob    = ob_data.get(
        f"best_{'bullish' if trend == 'BULLISH' else 'bearish'}"
    )
    best_fvg   = fvg_data.get(
        f"best_{'bullish' if trend == 'BULLISH' else 'bearish'}"
    )

    entry_zone = None
    entry_type = None
    stop_level = None

    if active_ob and active_ob.get("has_fvg"):
        entry_zone = active_ob
        entry_type = "OB+FVG"
        result["sequence"].append(
            f"✅ STEP 4: OB+FVG retest "
            f"@ {active_ob['bottom']:.5f}—{active_ob['top']:.5f}"
        )
        result["score"] += 0.30

    elif active_ob:
        entry_zone = active_ob
        entry_type = "OB"
        result["sequence"].append(
            f"✅ STEP 4: OB retest "
            f"@ {active_ob['bottom']:.5f}—{active_ob['top']:.5f}"
        )
        result["score"] += 0.20

    elif active_fvg:
        entry_zone = active_fvg
        entry_type = "FVG"
        result["sequence"].append(
            f"✅ STEP 4: FVG retest "
            f"@ {active_fvg['bottom']:.5f}—{active_fvg['top']:.5f}"
        )
        result["score"] += 0.15

    elif best_ob:
        entry_zone = best_ob
        entry_type = "OB"
        result["sequence"].append(
            f"⏳ STEP 4: Approaching OB "
            f"@ {best_ob['bottom']:.5f}—{best_ob['top']:.5f}"
        )
        result["warnings"].append("Wait for OB touch before entry")
        result["score"] += 0.08

    elif best_fvg:
        entry_zone = best_fvg
        entry_type = "FVG"
        result["sequence"].append(
            f"⏳ STEP 4: Approaching FVG "
            f"@ {best_fvg['bottom']:.5f}—{best_fvg['top']:.5f}"
        )
        result["warnings"].append("Wait for FVG touch before entry")
        result["score"] += 0.05

    else:
        result["missing"].append("No entry zone found in PD zone")
        result["warnings"].append(
            "BOS confirmed but no OB/FVG in pullback zone"
        )

    result["entry_zone"] = entry_zone
    result["entry_type"] = entry_type

    # ── Stop Loss ─────────────────────────────────
    if last_sweep and entry_zone:
        sweep_wick = last_sweep["candle"]
        if trend == "BULLISH":
            stop_level = sweep_wick["low"] - (atr * SL_BUFFER_ATR)
        else:
            stop_level = sweep_wick["high"] + (atr * SL_BUFFER_ATR)
        result["stop_level"] = round(stop_level, 5)
    elif entry_zone:
        # Fallback SL: beyond entry zone
        if trend == "BULLISH":
            stop_level = entry_zone["bottom"] - (atr * SL_BUFFER_ATR)
        else:
            stop_level = entry_zone["top"] + (atr * SL_BUFFER_ATR)
        result["stop_level"] = round(stop_level, 5)

    # ── HTF Alignment ─────────────────────────────
    htf_bias = structure.get("htf_bias")
    if htf_bias:
        htf_trade = htf_bias.get("trade_with", "WAIT")
        if (
            (trend == "BULLISH" and htf_trade == "LONG") or
            (trend == "BEARISH" and htf_trade == "SHORT")
        ):
            result["confirmations"].append(
                f"HTF aligned: {htf_bias['bias']} continuation"
            )
            result["score"] += 0.10
        elif htf_trade == "WAIT":
            result["warnings"].append("HTF ranging — lower confidence")
            result["score"] *= 0.8
        else:
            result["warnings"].append(
                "⚠️ Continuation against HTF — skip or reduce size"
            )
            result["score"] *= 0.5

    result["valid"] = (
        result["score"] >= MIN_SETUP_QUALITY
        and entry_zone is not None
        and result["stop_level"] is not None
    )

    return result


# ─────────────────────────────────────────────────────────────
# ENTRY PRICE CALCULATOR
# ─────────────────────────────────────────────────────────────

def _calculate_entry(
    entry_zone: dict,
    entry_type: str,
    direction:  str,
) -> float:
    """
    Calculate optimal entry price from entry zone.

    OB:      entry at 50% of OB body
    FVG:     entry at CE (50% of FVG)
    OB+FVG:  entry at FVG CE inside OB if available
              else OB 50%
    """
    if entry_type == "OB+FVG":
        fvg_inside = entry_zone.get("fvg_inside")
        if fvg_inside:
            return fvg_inside["mid"]
        return entry_zone.get("entry_50", entry_zone["mid"])

    elif entry_type == "OB":
        return entry_zone.get("entry_50", entry_zone["mid"])

    elif entry_type == "FVG":
        return entry_zone.get("ce", entry_zone["mid"])

    return entry_zone["mid"]


# ─────────────────────────────────────────────────────────────
# TARGET CALCULATOR
# ─────────────────────────────────────────────────────────────

def _calculate_targets(
    entry:       float,
    stop_loss:   float,
    next_target: Optional[dict],
    direction:   str,
    structure:   dict,
    atr:         float,
) -> dict:
    """
    Calculate TP1 and TP2.

    TP1 = 1:1 R:R (partial close here, move SL to BE)
    TP2 = next liquidity pool or swing extreme
    """
    risk = abs(entry - stop_loss)
    if risk == 0:
        risk = atr

    if direction == "BULLISH":
        tp1 = entry + (risk * TP1_RR)
        # TP2 = next BSL pool or last high
        if next_target and next_target["type"] == "BSL":
            tp2 = next_target["price"]
        else:
            tp2 = structure.get("last_high", entry + risk * 2)
            # Push beyond if too close
            if tp2 <= tp1:
                tp2 = entry + risk * 2.5

    else:  # BEARISH
        tp1 = entry - (risk * TP1_RR)
        # TP2 = next SSL pool or last low
        if next_target and next_target["type"] == "SSL":
            tp2 = next_target["price"]
        else:
            tp2 = structure.get("last_low", entry - risk * 2)
            if tp2 >= tp1:
                tp2 = entry - risk * 2.5

    rr_tp1 = abs(tp1 - entry) / risk if risk > 0 else 0
    rr_tp2 = abs(tp2 - entry) / risk if risk > 0 else 0

    return {
        "tp1":     round(tp1, 5),
        "tp2":     round(tp2, 5),
        "rr_tp1":  round(rr_tp1, 2),
        "rr_tp2":  round(rr_tp2, 2),
        "risk":    round(risk,   5),
    }


# ─────────────────────────────────────────────────────────────
# SETUP QUALITY SCORER
# ─────────────────────────────────────────────────────────────

def _score_setup(
    sequence_result: dict,
    rr_ratio:        float,
    entry_type:      str,
    htf_aligned:     bool,
) -> float:
    """
    Final setup quality score 0.0 - 1.0.
    Combines sequence score with additional factors.
    """
    score = sequence_result.get("score", 0.0)

    # R:R bonus
    if rr_ratio >= 3.0:
        score += 0.10
    elif rr_ratio >= 2.0:
        score += 0.05

    # Entry type bonus
    if entry_type == "OB+FVG":
        score += 0.05
    elif entry_type == "OB":
        score += 0.02

    # HTF bonus
    if htf_aligned:
        score += 0.05

    return round(min(score, 1.0), 2)


# ─────────────────────────────────────────────────────────────
# MAIN ICT ENGINE
# ─────────────────────────────────────────────────────────────

def run_ict_engine(
    candles:     list[dict],
    htf_candles: Optional[list[dict]] = None,
    symbol:      str = "",
    timeframe:   str = "",
    atr:         float = None,
) -> dict:
    """
    Main ICT engine entry point.
    Runs full analysis and validates both
    reversal and continuation sequences.

    Returns the best setup found, or WAIT.

    Args:
        candles:     LTF OHLCV data
        htf_candles: HTF OHLCV data for bias
        symbol:      Instrument symbol
        timeframe:   Chart timeframe
        atr:         Pre-calculated ATR (auto-calculated if None)

    Returns:
        Complete setup dict with all trade parameters.
    """
    if not candles or len(candles) < 50:
        return {
            "error":      "Need at least 50 candles",
            "setup_type": "WAIT",
            "valid":      False,
        }

    # ── ATR ───────────────────────────────────────
    if atr is None:
        from actions.trading.market_structure import _atr
        atr = _atr(candles)

    # ── Run All Analyses ──────────────────────────
    print(f"[ICT] Running structure analysis...")
    structure = analyse_structure(candles, htf_candles)

    print(f"[ICT] Running liquidity analysis...")
    liquidity = analyse_liquidity(
        candles,
        structure["swings"],
        atr,
        structure["trend"],
    )

    print(f"[ICT] Running FVG analysis...")
    fvg_data = analyse_fvg(
        candles,
        atr,
        structure["trend"],
        liquidity.get("pd_zones", {}),
    )

    print(f"[ICT] Running Order Block analysis...")
    ob_data = analyse_orderblocks(
        candles,
        atr,
        structure["trend"],
        liquidity.get("pd_zones", {}),
        fvg_data.get("valid_fvgs", []),
        structure["swings"],
    )

    current_price = candles[-1]["close"]
    trend         = structure.get("trend", "UNKNOWN")

    # ── Try Reversal Sequence ─────────────────────
    print(f"[ICT] Validating reversal sequence...")
    reversal = _validate_reversal_sequence(
        structure, liquidity, fvg_data, ob_data, candles, atr
    )

    # ── Try Continuation Sequence ─────────────────
    print(f"[ICT] Validating continuation sequence...")
    continuation = _validate_continuation_sequence(
        structure, liquidity, fvg_data, ob_data, candles, atr
    )

    # ── Pick Best Setup ───────────────────────────
    best_sequence  = None
    best_type      = "WAIT"

    if reversal["valid"] and continuation["valid"]:
        # Both valid — pick higher score
        if reversal["score"] >= continuation["score"]:
            best_sequence = reversal
            best_type     = "REVERSAL"
        else:
            best_sequence = continuation
            best_type     = "CONTINUATION"
    elif reversal["valid"]:
        best_sequence = reversal
        best_type     = "REVERSAL"
    elif continuation["valid"]:
        best_sequence = continuation
        best_type     = "CONTINUATION"
    else:
        # No valid setup — return analysis data anyway
        return {
            "valid":       False,
            "setup_type":  "WAIT",
            "direction":   "NONE",
            "symbol":      symbol,
            "timeframe":   timeframe,
            "trend":       trend,
            "score":       0.0,
            "sequence":    (
                reversal["sequence"]
                if len(reversal["sequence"]) > len(continuation["sequence"])
                else continuation["sequence"]
            ),
            "missing":     reversal["missing"] + continuation["missing"],
            "warnings":    reversal["warnings"] + continuation["warnings"],
            "confirmations": [],

            # Raw data for display
            "structure":   structure,
            "liquidity":   liquidity,
            "fvg_data":    fvg_data,
            "ob_data":     ob_data,
            "current_price": current_price,
            "atr":         atr,
            "analysed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    # ── Calculate Entry ───────────────────────────
    entry_zone  = best_sequence["entry_zone"]
    entry_type  = best_sequence["entry_type"]
    direction   = best_sequence["direction"]
    stop_loss   = best_sequence["stop_level"]

    entry_price = _calculate_entry(entry_zone, entry_type, direction)

    # ── Validate Entry vs Stop ────────────────────
    if direction == "BULLISH" and entry_price <= stop_loss:
        best_sequence["warnings"].append(
            "Entry below stop loss — skipping"
        )
        entry_price = entry_zone["bottom"] + atr * 0.5

    if direction == "BEARISH" and entry_price >= stop_loss:
        best_sequence["warnings"].append(
            "Entry above stop loss — skipping"
        )
        entry_price = entry_zone["top"] - atr * 0.5

    # ── Calculate Targets ─────────────────────────
    next_target = liquidity.get("next_target")
    targets     = _calculate_targets(
        entry_price, stop_loss,
        next_target, direction,
        structure, atr,
    )

    # ── Validate R:R ─────────────────────────────
    rr_ratio = targets["rr_tp2"]
    if rr_ratio < MIN_RR_RATIO:
        best_sequence["warnings"].append(
            f"R:R {rr_ratio:.1f}:1 below minimum {MIN_RR_RATIO}:1"
        )

    # ── Final Quality Score ───────────────────────
    quality = _score_setup(
        best_sequence,
        rr_ratio,
        entry_type,
        structure.get("htf_aligned", True),
    )

    # ── Build Trade Setup ─────────────────────────
    setup = {
        # Validity
        "valid":      quality >= MIN_SETUP_QUALITY,
        "setup_type": best_type,
        "direction":  direction,
        "symbol":     symbol,
        "timeframe":  timeframe,
        "score":      quality,

        # Trade levels
        "entry":      round(entry_price, 5),
        "stop_loss":  round(stop_loss,   5),
        "tp1":        targets["tp1"],
        "tp2":        targets["tp2"],
        "rr_tp1":     targets["rr_tp1"],
        "rr_tp2":     targets["rr_tp2"],
        "risk":       targets["risk"],

        # Entry info
        "entry_type": entry_type,
        "entry_zone": {
            "top":    entry_zone["top"],
            "bottom": entry_zone["bottom"],
            "mid":    entry_zone["mid"],
        },

        # Target info
        "next_target": next_target,

        # Sequence
        "sequence":      best_sequence["sequence"],
        "confirmations": best_sequence["confirmations"],
        "warnings":      best_sequence["warnings"],
        "missing":       best_sequence.get("missing", []),

        # ICT components used
        "sweep_used": best_sequence.get("sweep_used"),
        "mss_used":   best_sequence.get("mss_used"),

        # Trade management
        "move_sl_be_at_tp1": True,
        "partial_close_tp1": 50,   # Close 50% at TP1
        "max_open_trades":   MAX_OPEN_TRADES,

        # Market context
        "trend":         trend,
        "current_price": current_price,
        "atr":           atr,

        # Raw analysis
        "structure":  structure,
        "liquidity":  liquidity,
        "fvg_data":   fvg_data,
        "ob_data":    ob_data,

        "analysed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    print(
        f"[ICT] ✅ Setup found: {best_type} {direction} "
        f"| Entry: {entry_price:.5f} | SL: {stop_loss:.5f} "
        f"| TP2: {targets['tp2']:.5f} | R:R: {rr_ratio:.1f} "
        f"| Score: {quality*100:.0f}%"
    )

    return setup


# ─────────────────────────────────────────────────────────────
# FORMATTER
# ─────────────────────────────────────────────────────────────

def format_ict_setup(setup: dict) -> str:
    """Human readable ICT setup summary."""
    if not setup.get("valid"):
        lines = [
            "⏳ ICT SETUP — WAITING FOR CONFIRMATION",
            "─" * 42,
            f"Symbol:    {setup.get('symbol', '?')}",
            f"Timeframe: {setup.get('timeframe', '?')}",
            f"Trend:     {setup.get('trend', 'UNKNOWN')}",
            f"Price:     {setup.get('current_price', 0):.5f}",
            "",
            "📋 SEQUENCE STATUS:",
        ]
        for step in setup.get("sequence", []):
            lines.append(f"  {step}")

        if setup.get("missing"):
            lines += ["", "❌ MISSING:"]
            for m in setup["missing"]:
                lines.append(f"  • {m}")

        if setup.get("warnings"):
            lines += ["", "⚠️  WARNINGS:"]
            for w in setup["warnings"]:
                lines.append(f"  • {w}")

        lines += [
            "",
            "─" * 42,
            "Wait for full sequence before entering.",
        ]
        return "\n".join(lines)

    # Valid setup
    dir_emoji = "🟢 LONG" if setup["direction"] == "BULLISH" else "🔴 SHORT"
    border    = "═" * 50

    lines = [
        border,
        f"  {dir_emoji} | {setup['setup_type']} SETUP",
        f"  {setup['symbol']} {setup['timeframe']} | "
        f"Quality: {setup['score']*100:.0f}%",
        border,
        "",
        f"  Entry Type:  {setup['entry_type']}",
        f"  Entry Zone:  {setup['entry_zone']['bottom']:.5f}"
        f" — {setup['entry_zone']['top']:.5f}",
        f"  Entry Price: {setup['entry']:.5f}",
        f"  Stop Loss:   {setup['stop_loss']:.5f}",
        f"  TP1 (1:1):   {setup['tp1']:.5f}  "
        f"(R:R {setup['rr_tp1']:.1f}:1)",
        f"  TP2 (target):{setup['tp2']:.5f}  "
        f"(R:R {setup['rr_tp2']:.1f}:1)",
        f"  Risk/unit:   {setup['risk']:.5f}",
        "",
        "  📋 SEQUENCE:",
    ]

    for step in setup["sequence"]:
        lines.append(f"    {step}")

    if setup["confirmations"]:
        lines += ["", "  ✅ CONFIRMATIONS:"]
        for c in setup["confirmations"]:
            lines.append(f"    • {c}")

    if setup["warnings"]:
        lines += ["", "  ⚠️  WARNINGS:"]
        for w in setup["warnings"]:
            lines.append(f"    • {w}")

    lines += [
        "",
        "  🔧 TRADE MANAGEMENT:",
        f"    • Move SL to BE after TP1",
        f"    • Close 50% at TP1",
        f"    • Let 50% run to TP2",
        f"    • Max {MAX_OPEN_TRADES} trades open",
        "",
        "  ⚠️  Not financial advice.",
        border,
    ]

    return "\n".join(lines)