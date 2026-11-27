# actions/trading_agent.py
"""
JARVIS Pro Trading Agent
─────────────────────────
Upgraded Features:
  - Full ICT Strategy Engine    (Sweep → MSS → Retest → Target)
  - Multi-Timeframe Analysis    (HTF bias + LTF entry)
  - MT5 Live/Demo Trading       (any broker, Windows + Linux Wine)
  - Risk Manager                (1% risk, daily limits, kill switch)
  - Session Filter              (London/NY killzones)
  - Trade Journal               (JSON + CSV logging)
  - Performance Stats           (win rate, R:R, profit factor)
  - Symbol Scanner              (scan watchlist for setups)
  - TradingView Integration     (auto-draw zones on chart)
  - Pine Script Generator       (paste analysis to chart)
  - Position Manager            (partial close, BE, trailing)
  - Kept all original features  (fibonacci, risk calc, open TV)
"""

import json
import sys
import time
import math
import platform
import threading
from pathlib import Path
from datetime import datetime, timedelta

_OS = platform.system()


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()


# ─────────────────────────────────────────────────────────────
# SYMBOL RESOLVER (kept from original)
# ─────────────────────────────────────────────────────────────

_SYMBOL_MAP = {
    "XAUUSD": {"yfinance": "GC=F",      "ccxt": "XAU/USDT", "display": "XAUUSD"},
    "GOLD":   {"yfinance": "GC=F",      "ccxt": "XAU/USDT", "display": "GOLD"},
    "XAGUSD": {"yfinance": "SI=F",      "ccxt": "XAG/USDT", "display": "XAGUSD"},
    "USOIL":  {"yfinance": "CL=F",      "ccxt": None,        "display": "USOIL"},
    "XTIUSD": {"yfinance": "CL=F",      "ccxt": None,        "display": "XTIUSD"},
    "WTI":    {"yfinance": "CL=F",      "ccxt": None,        "display": "WTI"},
    "BRENT":  {"yfinance": "BZ=F",      "ccxt": None,        "display": "BRENT"},
    "EURUSD": {"yfinance": "EURUSD=X",  "ccxt": None,        "display": "EURUSD"},
    "GBPUSD": {"yfinance": "GBPUSD=X",  "ccxt": None,        "display": "GBPUSD"},
    "USDJPY": {"yfinance": "JPY=X",     "ccxt": None,        "display": "USDJPY"},
    "AUDUSD": {"yfinance": "AUDUSD=X",  "ccxt": None,        "display": "AUDUSD"},
    "USDCAD": {"yfinance": "CAD=X",     "ccxt": None,        "display": "USDCAD"},
    "USDCHF": {"yfinance": "CHF=X",     "ccxt": None,        "display": "USDCHF"},
    "NZDUSD": {"yfinance": "NZDUSD=X",  "ccxt": None,        "display": "NZDUSD"},
    "GBPJPY": {"yfinance": "GBPJPY=X",  "ccxt": None,        "display": "GBPJPY"},
    "EURJPY": {"yfinance": "EURJPY=X",  "ccxt": None,        "display": "EURJPY"},
    "EURGBP": {"yfinance": "EURGBP=X",  "ccxt": None,        "display": "EURGBP"},
    "CADJPY": {"yfinance": "CADJPY=X",  "ccxt": None,        "display": "CADJPY"},
    "CHFJPY": {"yfinance": "CHFJPY=X",  "ccxt": None,        "display": "CHFJPY"},
    "US30":   {"yfinance": "^DJI",      "ccxt": None,        "display": "US30"},
    "US500":  {"yfinance": "^GSPC",     "ccxt": None,        "display": "US500"},
    "SPX":    {"yfinance": "^GSPC",     "ccxt": None,        "display": "SPX"},
    "NAS100": {"yfinance": "^IXIC",     "ccxt": None,        "display": "NAS100"},
    "DAX":    {"yfinance": "^GDAXI",    "ccxt": None,        "display": "DAX"},
    "FTSE":   {"yfinance": "^FTSE",     "ccxt": None,        "display": "FTSE"},
    "JP225":  {"yfinance": "^N225",     "ccxt": None,        "display": "JP225"},
    "BTCUSD": {"yfinance": "BTC-USD",   "ccxt": "BTC/USDT",  "display": "BTCUSD"},
    "ETHUSD": {"yfinance": "ETH-USD",   "ccxt": "ETH/USDT",  "display": "ETHUSD"},
    "SOLUSD": {"yfinance": "SOL-USD",   "ccxt": "SOL/USDT",  "display": "SOLUSD"},
}

_TV_SYMBOL_MAP = {
    "XAUUSD": "OANDA:XAUUSD", "GOLD":   "OANDA:XAUUSD",
    "XAGUSD": "OANDA:XAGUSD", "USOIL":  "NYMEX:CL1!",
    "EURUSD": "OANDA:EURUSD", "GBPUSD": "OANDA:GBPUSD",
    "USDJPY": "OANDA:USDJPY", "AUDUSD": "OANDA:AUDUSD",
    "USDCAD": "OANDA:USDCAD", "USDCHF": "OANDA:USDCHF",
    "NZDUSD": "OANDA:NZDUSD", "GBPJPY": "OANDA:GBPJPY",
    "EURJPY": "OANDA:EURJPY", "EURGBP": "OANDA:EURGBP",
    "CADJPY": "OANDA:CADJPY", "CHFJPY": "OANDA:CHFJPY",
    "US30":   "DJ:DJI",       "US500":  "SP:SPX",
    "NAS100": "NASDAQ:NDX",   "DAX":    "XETR:DAX",
    "BTCUSD": "BINANCE:BTCUSDT", "ETHUSD": "BINANCE:ETHUSDT",
}


def _resolve_symbol(symbol: str) -> dict:
    symbol_upper = symbol.upper().strip()
    if symbol_upper in _SYMBOL_MAP:
        return _SYMBOL_MAP[symbol_upper]
    clean = symbol_upper.replace("=X", "").replace("-USD", "")
    if clean in _SYMBOL_MAP:
        return _SYMBOL_MAP[clean]
    if len(symbol_upper) == 6 and symbol_upper.isalpha():
        return {
            "yfinance": f"{symbol_upper}=X",
            "ccxt":     None,
            "display":  symbol_upper,
        }
    return {
        "yfinance": symbol_upper,
        "ccxt":     symbol_upper,
        "display":  symbol_upper,
    }


# ─────────────────────────────────────────────────────────────
# GLOBAL MT5 EXECUTOR INSTANCE
# ─────────────────────────────────────────────────────────────

_mt5_executor  = None
_risk_manager  = None
_mtf_engine    = None
_executor_lock = threading.Lock()


def _get_mt5(player=None, speak=None):
    """Get or create global MT5 executor."""
    global _mt5_executor
    with _executor_lock:
        if _mt5_executor is None:
            from actions.trading.mt5_executor import MT5Executor
            _mt5_executor = MT5Executor(player=player, speak=speak)
        return _mt5_executor


def _get_risk_manager(player=None, speak=None):
    """Get or create global risk manager."""
    global _risk_manager
    with _executor_lock:
        if _risk_manager is None:
            from actions.trading.risk_manager import RiskManager
            _risk_manager = RiskManager(player=player, speak=speak)
        return _risk_manager


def _get_mtf_engine(player=None, speak=None):
    """Get or create global MTF engine."""
    global _mtf_engine
    with _executor_lock:
        if _mtf_engine is None:
            from actions.trading.mtf_engine import MTFEngine
            _mtf_engine = MTFEngine(
                mt5_executor = _mt5_executor,
                player       = player,
                speak        = speak,
            )
        return _mtf_engine


# ─────────────────────────────────────────────────────────────
# ORIGINAL FUNCTIONS (kept fully intact)
# ─────────────────────────────────────────────────────────────

def _fetch_candles(
    symbol:    str,
    timeframe: str = "1h",
    limit:     int = 200,
    exchange:  str = "binance",
) -> list[dict]:
    """Fetch candles — MT5 first then yfinance/ccxt fallback."""
    # Try MT5 first if connected
    global _mt5_executor
    if _mt5_executor and _mt5_executor.connected:
        try:
            from actions.trading.mtf_engine import DataFetcher, normalize_tf
            fetcher = DataFetcher(_mt5_executor)
            candles = fetcher.fetch(symbol, normalize_tf(timeframe), limit)
            if candles:
                return candles
        except Exception as e:
            print(f"[Trading] MT5 fetch failed: {e}")

    # Fallback to original yfinance/ccxt logic
    resolved = _resolve_symbol(symbol)
    print(f"[Trading] Symbol resolved: {symbol} → {resolved}")

    ccxt_symbol = resolved.get("ccxt")
    if ccxt_symbol:
        try:
            import ccxt as ccxt_lib
            ex    = getattr(ccxt_lib, exchange)({"enableRateLimit": True})
            ohlcv = ex.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit)
            candles = []
            for row in ohlcv:
                candles.append({
                    "timestamp": row[0],
                    "time":      datetime.fromtimestamp(row[0] / 1000).strftime("%Y-%m-%d %H:%M"),
                    "open":      row[1],
                    "high":      row[2],
                    "low":       row[3],
                    "close":     row[4],
                    "volume":    row[5],
                })
            if candles:
                return candles
        except Exception as e:
            print(f"[Trading] CCXT failed: {e}")

    yf_symbol = resolved.get("yfinance", symbol)
    tf_map = {
        "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
        "1h": "1h", "4h": "1h", "1d": "1d", "1w": "1wk",
    }
    period_map = {
        "1m": "1d", "5m": "5d", "15m": "60d", "30m": "60d",
        "1h": "730d", "4h": "730d", "1d": "5y", "1w": "10y",
    }

    try:
        import yfinance as yf
        yf_tf     = tf_map.get(timeframe.lower(), "1h")
        yf_period = period_map.get(timeframe.lower(), "60d")
        ticker    = yf.Ticker(yf_symbol)
        df        = ticker.history(
            period=yf_period, interval=yf_tf, auto_adjust=True
        )
        if df.empty:
            raise ValueError(f"No data for {yf_symbol}")
        candles = []
        for idx, row in df.iterrows():
            candles.append({
                "timestamp": int(idx.timestamp() * 1000),
                "time":      str(idx)[:16],
                "open":      float(row["Open"]),
                "high":      float(row["High"]),
                "low":       float(row["Low"]),
                "close":     float(row["Close"]),
                "volume":    float(row.get("Volume", 0)),
            })
        return candles[-limit:]
    except Exception as e:
        print(f"[Trading] yfinance failed: {e}")

    return []


def _find_swing_highs_lows(candles, lookback=5):
    highs, lows = [], []
    for i in range(lookback, len(candles) - lookback):
        window  = candles[i - lookback : i + lookback + 1]
        current = candles[i]
        if current["high"] == max(c["high"] for c in window):
            highs.append({"index": i, "price": current["high"], "time": current["time"]})
        if current["low"] == min(c["low"] for c in window):
            lows.append({"index": i, "price": current["low"],  "time": current["time"]})
    return {"highs": highs, "lows": lows}


def _calculate_fibonacci(swing_high, swing_low, direction="bullish"):
    diff   = swing_high - swing_low
    levels = {}
    ratios = {
        "0.0": 0.0, "0.236": 0.236, "0.382": 0.382,
        "0.5": 0.5, "0.618": 0.618, "0.705": 0.705,
        "0.786": 0.786, "1.0": 1.0, "1.272": 1.272, "1.618": 1.618,
    }
    for label, ratio in ratios.items():
        levels[label] = (
            swing_high - (diff * ratio)
            if direction == "bullish"
            else swing_low + (diff * ratio)
        )
    return {
        "swing_high": swing_high, "swing_low": swing_low,
        "direction":  direction,  "levels":    levels,
        "premium_zone":  {"top": swing_high, "bottom": (swing_high + swing_low) / 2},
        "discount_zone": {"top": (swing_high + swing_low) / 2, "bottom": swing_low},
        "ote_zone":      {"top": levels["0.618"], "bottom": levels["0.786"]},
    }


def _calculate_risk(account_size, risk_percent, entry, stop_loss, symbol=""):
    risk_amount   = account_size * (risk_percent / 100)
    risk_per_pip  = abs(entry - stop_loss)
    position_size = risk_amount / risk_per_pip if risk_per_pip > 0 else 0
    return {
        "account_size":  account_size,
        "risk_percent":  risk_percent,
        "risk_amount":   round(risk_amount,   2),
        "risk_per_unit": round(risk_per_pip,  5),
        "position_size": round(position_size, 4),
        "entry":         entry,
        "stop_loss":     stop_loss,
    }


# ─────────────────────────────────────────────────────────────
# PINE SCRIPT GENERATOR (upgraded with ICT zones)
# ─────────────────────────────────────────────────────────────

def _generate_pine_script(analysis: dict, symbol: str) -> str:
    """Generate Pine Script from ICT analysis."""
    setup     = analysis.get("setup") or analysis
    fvg_data  = analysis.get("fvg_data",  {})
    ob_data   = analysis.get("ob_data",   {})
    liquidity = analysis.get("liquidity", {})
    structure = analysis.get("structure", {})
    fib       = analysis.get("fibonacci", {})
    trend     = structure.get("trend", "UNKNOWN") if structure else "UNKNOWN"
    price     = analysis.get("current_price", 0)

    fvgs = fvg_data.get("valid_fvgs",  []) if fvg_data else analysis.get("fvgs", [])
    obs  = ob_data.get("valid_obs",    []) if ob_data  else analysis.get("order_blocks", [])
    bsl  = liquidity.get("bsl_pools",  []) if liquidity else []
    ssl  = liquidity.get("ssl_pools",  []) if liquidity else []
    swept = liquidity.get("sweeps",    []) if liquidity else []

    lines = [
        "//@version=5",
        f'indicator("JARVIS ICT — {symbol}", overlay=true, '
        f'max_boxes_count=500, max_lines_count=500, max_labels_count=500)',
        "",
        f"// JARVIS AI Pro Trading | {symbol}",
        f"// Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"// Trend: {trend} | Price: {price:.5f}",
        "",
        "c_fvg_b  = color.new(color.teal,   80)",
        "c_fvg_r  = color.new(color.orange, 80)",
        "c_ob_b   = color.new(color.blue,   70)",
        "c_ob_r   = color.new(color.red,    70)",
        "c_sweep  = color.new(color.yellow, 60)",
        "c_bsl    = color.new(color.green,  30)",
        "c_ssl    = color.new(color.red,    30)",
        "",
    ]

    # ── FVGs ──────────────────────────────────────
    if fvgs:
        lines.append("// ── Fair Value Gaps ──")
        for fvg in fvgs[:8]:
            is_bull  = "BULLISH" in fvg.get("type", "")
            b_col    = "color.teal"   if is_bull else "color.orange"
            bg_col   = "c_fvg_b"     if is_bull else "c_fvg_r"
            label    = "Bull FVG"    if is_bull else "Bear FVG"
            top      = fvg.get("top",    0)
            bot      = fvg.get("bottom", 0)
            mid      = fvg.get("mid",    0)
            score    = int(fvg.get("score", 0) * 100)
            lines += [
                f'box.new(bar_index-80, {top}, bar_index+5, {bot}, '
                f'border_color={b_col}, bgcolor={bg_col}, border_width=1)',
                f'label.new(bar_index-75, {mid}, "{label} {score}%", '
                f'color=color.new({b_col},85), textcolor={b_col}, '
                f'size=size.tiny, style=label.style_label_right)',
            ]
            # CE line
            lines.append(
                f'line.new(bar_index-80, {mid}, bar_index+5, {mid}, '
                f'color=color.new({b_col},50), style=line.style_dotted, width=1)'
            )

    lines.append("")

    # ── Order Blocks ──────────────────────────────
    if obs:
        lines.append("// ── Order Blocks ──")
        for ob in obs[:6]:
            is_bull  = "BULLISH" in ob.get("type", "")
            b_col    = "color.blue"  if is_bull else "color.red"
            bg_col   = "c_ob_b"     if is_bull else "c_ob_r"
            label    = "Bull OB"    if is_bull else "Bear OB"
            fvg_tag  = " ⚡" if ob.get("has_fvg") else ""
            top      = ob.get("top",      0)
            bot      = ob.get("bottom",   0)
            mid      = ob.get("mid",      0)
            e50      = ob.get("entry_50", mid)
            score    = int(ob.get("score", 0) * 100)
            lines += [
                f'box.new(bar_index-60, {top}, bar_index+5, {bot}, '
                f'border_color={b_col}, bgcolor={bg_col}, border_width=2)',
                f'label.new(bar_index-55, {mid}, "{label}{fvg_tag} {score}%", '
                f'color=color.new({b_col},80), textcolor={b_col}, '
                f'size=size.tiny, style=label.style_label_right)',
                # 50% entry line
                f'line.new(bar_index-60, {e50}, bar_index+5, {e50}, '
                f'color=color.new({b_col},40), style=line.style_dashed, width=1)',
            ]

    lines.append("")

    # ── Liquidity Zones ───────────────────────────
    if bsl or ssl:
        lines.append("// ── Liquidity Pools ──")
        for zone in bsl[:4]:
            p = zone.get("price", 0)
            lines += [
                f'line.new(bar_index-80, {p}, bar_index+5, {p}, '
                f'color=c_bsl, style=line.style_dotted, width=2)',
                f'label.new(bar_index-75, {p}, "BSL {p:.5f}", '
                f'color=color.new(color.green,80), textcolor=color.green, '
                f'size=size.tiny, style=label.style_label_right)',
            ]
        for zone in ssl[:4]:
            p = zone.get("price", 0)
            lines += [
                f'line.new(bar_index-80, {p}, bar_index+5, {p}, '
                f'color=c_ssl, style=line.style_dotted, width=2)',
                f'label.new(bar_index-75, {p}, "SSL {p:.5f}", '
                f'color=color.new(color.red,80), textcolor=color.red, '
                f'size=size.tiny, style=label.style_label_right)',
            ]

    # ── Sweeps ────────────────────────────────────
    if swept:
        lines.append("// ── Sweeps ──")
        for sw in swept[-3:]:
            p   = sw.get("pool_price", 0)
            col = "color.green" if "SSL" in sw.get("type", "") else "color.red"
            lines.append(
                f'label.new(bar_index-5, {p}, "⚡ SWEPT {p:.5f}", '
                f'color=color.new({col},60), textcolor={col}, '
                f'size=size.small, style=label.style_label_up)'
            )

    lines.append("")

    # ── Structure Events ──────────────────────────
    events = structure.get("events", []) if structure else []
    if events:
        lines.append("// ── Structure Events ──")
        for e in events[-4:]:
            col   = "color.green" if e["direction"] == "BULLISH" else "color.red"
            style = "label.style_label_up" if e["direction"] == "BULLISH" else "label.style_label_down"
            lines.append(
                f'label.new(bar_index-3, {e["price"]}, "{e["type"]} {e["direction"]}", '
                f'color=color.new({col},60), textcolor={col}, '
                f'size=size.small, style={style})'
            )

    lines.append("")

    # ── Trade Setup ───────────────────────────────
    entry    = setup.get("entry",     0) if isinstance(setup, dict) else 0
    sl       = setup.get("stop_loss", 0) if isinstance(setup, dict) else 0
    tp1      = setup.get("tp1",       0) if isinstance(setup, dict) else 0
    tp2      = setup.get("tp2",       0) if isinstance(setup, dict) else 0
    rr       = setup.get("rr_tp2",    0) if isinstance(setup, dict) else 0
    s_type   = setup.get("setup_type","") if isinstance(setup, dict) else ""
    s_dir    = setup.get("direction", "") if isinstance(setup, dict) else ""
    s_score  = int(setup.get("score", 0) * 100) if isinstance(setup, dict) else 0

    if entry and sl and tp2:
        lines += [
            "// ── Trade Setup ──",
            f"// {s_type} {s_dir} | Score: {s_score}% | R:R: {rr:.1f}:1",
            "",
            # Entry
            f'line.new(bar_index-50, {entry}, bar_index+15, {entry}, '
            f'color=color.yellow, width=2)',
            f'label.new(bar_index+12, {entry}, '
            f'"✦ {s_dir} {s_type} | RR:{rr:.1f} Score:{s_score}%", '
            f'color=color.new(color.yellow,60), textcolor=color.yellow, '
            f'size=size.small, style=label.style_label_left)',
            # SL
            f'line.new(bar_index-50, {sl}, bar_index+15, {sl}, '
            f'color=color.red, width=1, style=line.style_dashed)',
            f'label.new(bar_index+12, {sl}, "✕ SL {sl:.5f}", '
            f'color=color.new(color.red,60), textcolor=color.red, '
            f'size=size.tiny, style=label.style_label_left)',
        ]

        if tp1:
            lines += [
                f'line.new(bar_index-50, {tp1}, bar_index+15, {tp1}, '
                f'color=color.green, width=1, style=line.style_dashed)',
                f'label.new(bar_index+12, {tp1}, "✓ TP1 {tp1:.5f} (50% close)", '
                f'color=color.new(color.green,60), textcolor=color.green, '
                f'size=size.tiny, style=label.style_label_left)',
            ]

        lines += [
            f'line.new(bar_index-50, {tp2}, bar_index+15, {tp2}, '
            f'color=color.green, width=2)',
            f'label.new(bar_index+12, {tp2}, "✓ TP2 {tp2:.5f} (liquidity)", '
            f'color=color.new(color.green,60), textcolor=color.green, '
            f'size=size.small, style=label.style_label_left)',
            # Entry zone box
            f'box.new(bar_index-50, {entry * 1.0002}, '
            f'bar_index+15, {entry * 0.9998}, '
            f'border_color=color.new(color.yellow,60), '
            f'bgcolor=color.new(color.yellow,90))',
        ]

    # ── Fibonacci ─────────────────────────────────
    fib_levels = fib.get("levels", {}) if fib else {}
    if fib_levels:
        lines.append("// ── Fibonacci ──")
        key_fibs = {
            "0.382": ("color.yellow", False),
            "0.5":   ("color.white",  False),
            "0.618": ("color.purple", True),
            "0.786": ("color.purple", True),
        }
        for label, (col, is_ote) in key_fibs.items():
            if label in fib_levels:
                p     = fib_levels[label]
                width = 2 if is_ote else 1
                tag   = " OTE" if is_ote else ""
                lines += [
                    f'line.new(bar_index-100, {p}, bar_index+10, {p}, '
                    f'color={col}, style=line.style_dashed, width={width})',
                    f'label.new(bar_index-95, {p}, "Fib {label}{tag}", '
                    f'color=color.new({col},80), textcolor={col}, '
                    f'size=size.tiny, style=label.style_label_right)',
                ]

    # ── Watermark ─────────────────────────────────
    lines += [
        "",
        f'label.new(bar_index-10, high, '
        f'"JARVIS AI PRO | {symbol} | {datetime.now().strftime("%Y-%m-%d %H:%M")}", '
        f'color=color.new(color.blue,95), textcolor=color.new(color.white,60), '
        f'size=size.tiny, style=label.style_label_down)',
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# TRADINGVIEW DRAWER (kept from original + upgrades)
# ─────────────────────────────────────────────────────────────

class TradingViewDrawer:
    """Draws ICT analysis on TradingView in real-time."""

    def __init__(self, symbol, timeframe, player=None, speak=None):
        self.symbol    = symbol
        self.timeframe = timeframe
        self.player    = player
        self.speak     = speak
        self.sess      = None

    def _log(self, msg):
        print(f"[TradingView] {msg}")
        if self.player:
            self.player.write_log(f"[TV] {msg}")

    def open(self) -> bool:
        try:
            from actions.browser_control import _registry
            tf_map   = {
                "1m": "1", "5m": "5", "15m": "15", "30m": "30",
                "1h": "60", "4h": "240", "1d": "D", "1w": "W",
                "1D": "D", "4H": "240",
            }
            tv_tf    = tf_map.get(self.timeframe, "60")
            display  = _resolve_symbol(self.symbol).get("display", self.symbol).upper()
            tv_sym   = _TV_SYMBOL_MAP.get(display, display)
            url      = f"https://www.tradingview.com/chart/?symbol={tv_sym}&interval={tv_tf}"
            self.sess = _registry.get("brave") or _registry.get("chrome")
            if self.sess:
                self.sess.run(self.sess.go_to(url), timeout=20)
                time.sleep(4)
                self._log(f"✅ TradingView: {tv_sym} {self.timeframe}")
                return True
        except Exception as e:
            self._log(f"TV open error: {e}")
        return False

    def _run_js(self, js: str) -> str:
        try:
            import asyncio
            async def _exec():
                page = await self.sess._get_page()
                return await page.evaluate(js)
            return self.sess.run(_exec(), timeout=10)
        except Exception as e:
            return f"JS error: {e}"

    def _show_notification(self, message: str, color: str = "#00d4ff"):
        safe = message.replace("'", "\\'").replace('"', '\\"')
        self._run_js(f"""
        (function(){{
            var e=document.getElementById('jv-notif');
            if(e)e.remove();
            var d=document.createElement('div');
            d.id='jv-notif';
            d.style.cssText='position:fixed;top:20px;left:50%;'
            +'transform:translateX(-50%);background:rgba(0,6,10,0.96);'
            +'color:{color};border:1px solid {color};border-radius:6px;'
            +'padding:12px 24px;font-family:monospace;font-size:13px;'
            +'font-weight:bold;z-index:99999;max-width:600px;text-align:center;';
            d.innerHTML='🤖 JARVIS | {safe}';
            document.body.appendChild(d);
            setTimeout(()=>{{if(d.parentNode)d.remove();}},4000);
        }})();
        """)

    def _show_panel(self, trend: str, phase: str, progress: int):
        colors = {
            "BULLISH": "#00ff88", "BEARISH": "#ff3355",
            "RANGING": "#ffcc00", "ANALYSING": "#00d4ff",
        }
        tc = colors.get(trend, "#00d4ff")
        self._run_js(f"""
        (function(){{
            var p=document.getElementById('jv-panel');
            if(!p){{
                p=document.createElement('div');
                p.id='jv-panel';
                p.style.cssText='position:fixed;top:60px;right:20px;width:280px;'
                +'background:rgba(0,6,10,0.97);border:1px solid #0d3347;'
                +'border-radius:8px;padding:16px;font-family:monospace;'
                +'font-size:11px;z-index:99998;color:#8ffcff;';
                document.body.appendChild(p);
            }}
            p.innerHTML=`
                <div style="color:#00d4ff;font-size:13px;font-weight:bold;
                margin-bottom:10px;">🤖 JARVIS PRO ANALYSIS</div>
                <div><span style="color:#5ab8cc;">Symbol:</span>
                <span style="color:#fff;float:right;">{self.symbol}</span></div>
                <div><span style="color:#5ab8cc;">TF:</span>
                <span style="color:#fff;float:right;">{self.timeframe}</span></div>
                <div><span style="color:#5ab8cc;">Trend:</span>
                <span style="color:{tc};float:right;font-weight:bold;">{trend}</span></div>
                <div style="margin:6px 0;"><span style="color:#5ab8cc;">Phase:</span>
                <span style="color:#ffcc00;float:right;">{phase}</span></div>
                <div style="background:#011520;border-radius:4px;height:6px;overflow:hidden;">
                <div style="background:#00d4ff;height:100%;width:{progress}%;
                transition:width 0.5s;border-radius:4px;"></div></div>
                <div style="color:#3a8a9a;font-size:9px;text-align:center;
                margin-top:8px;">JARVIS AI Pro Trading</div>
            `;
        }})();
        """)

    def _update_final_panel(self, result: dict):
        setup     = result if result.get("entry") else None
        structure = result.get("structure", {})
        fvg_data  = result.get("fvg_data",  {})
        ob_data   = result.get("ob_data",   {})
        trend     = result.get("trend", structure.get("trend", "?"))
        price     = result.get("current_price", 0)
        score     = int(result.get("score", 0) * 100)
        s_type    = result.get("setup_type", "WAIT")

        fvg_count = fvg_data.get("count",      0) if fvg_data else 0
        ob_count  = ob_data.get("count",       0) if ob_data  else 0
        conf_count = len(ob_data.get("confluence_obs", [])) if ob_data else 0

        colors = {
            "BULLISH": "#00ff88",
            "BEARISH": "#ff3355",
            "RANGING": "#ffcc00",
        }
        tc = colors.get(trend, "#00d4ff")

        setup_html = ""
        if setup and setup.get("valid"):
            dc  = "#00ff88" if setup["direction"] == "BULLISH" else "#ff3355"
            em  = "🟢" if setup["direction"] == "BULLISH" else "🔴"
            setup_html = f"""
            <div style="margin-top:8px;padding-top:8px;border-top:1px solid #0d3347;">
            <div style="color:{dc};font-weight:bold;">{em} {setup['direction']} {s_type}</div>
            <div><span style="color:#5ab8cc;">Entry:</span>
            <span style="float:right;">{setup.get('entry',0):.5f}</span></div>
            <div><span style="color:#5ab8cc;">SL:</span>
            <span style="color:#ff3355;float:right;">{setup.get('stop_loss',0):.5f}</span></div>
            <div><span style="color:#5ab8cc;">TP1:</span>
            <span style="color:#00ff88;float:right;">{setup.get('tp1',0):.5f}</span></div>
            <div><span style="color:#5ab8cc;">TP2:</span>
            <span style="color:#00ff88;float:right;">{setup.get('tp2',0):.5f}</span></div>
            <div><span style="color:#5ab8cc;">R:R:</span>
            <span style="color:#ffcc00;float:right;font-weight:bold;">
            {setup.get('rr_tp2',0):.1f}:1</span></div>
            <div><span style="color:#5ab8cc;">Score:</span>
            <span style="color:#ffcc00;float:right;">{score}%</span></div>
            </div>"""
        else:
            setup_html = (
                '<div style="margin-top:8px;color:#3a8a9a;font-size:10px;'
                'text-align:center;">⏳ Waiting for full ICT sequence</div>'
            )

        self._run_js(f"""
        (function(){{
            var p=document.getElementById('jv-panel');
            if(!p)return;
            p.innerHTML=`
                <div style="color:#00d4ff;font-size:13px;font-weight:bold;
                margin-bottom:8px;">🤖 JARVIS PRO ✅</div>
                <div><span style="color:#5ab8cc;">Price:</span>
                <span style="float:right;">{price:.5f}</span></div>
                <div><span style="color:#5ab8cc;">Trend:</span>
                <span style="color:{tc};float:right;font-weight:bold;">{trend}</span></div>
                <div><span style="color:#5ab8cc;">FVGs:</span>
                <span style="float:right;">{fvg_count}</span></div>
                <div><span style="color:#5ab8cc;">OBs:</span>
                <span style="float:right;">{ob_count}</span></div>
                <div><span style="color:#5ab8cc;">OB+FVG:</span>
                <span style="color:#ffcc00;float:right;">{conf_count}</span></div>
                {setup_html}
                <div style="color:#3a8a9a;font-size:9px;text-align:center;
                margin-top:8px;">⚠️ Not financial advice</div>
            `;
        }})();
        """)

    def _apply_pine_script(self, pine: str) -> str:
        import asyncio
        async def _paste():
            try:
                page = await self.sess._get_page()
                await page.keyboard.press("Alt+p")
                await asyncio.sleep(2)
                for sel in [".cm-content", ".cm-editor", '[data-role="text-area"]']:
                    try:
                        await page.click(sel, timeout=2000)
                        await asyncio.sleep(0.5)
                        break
                    except Exception:
                        continue
                await page.keyboard.press("Control+a")
                await asyncio.sleep(0.3)
                await page.keyboard.press("Delete")
                await asyncio.sleep(0.3)
                try:
                    import pyperclip
                    pyperclip.copy(pine)
                    await page.keyboard.press("Control+v")
                except Exception:
                    await page.keyboard.type(pine[:3000])
                await asyncio.sleep(1)
                for sel in [
                    'button[data-name="add-script-to-chart"]',
                    'button:has-text("Add to chart")',
                ]:
                    try:
                        await page.click(sel, timeout=2000)
                        await asyncio.sleep(1)
                        return "✅ Pine Script applied!"
                    except Exception:
                        continue
                return "Script pasted — click Add to chart manually"
            except Exception as e:
                return f"Pine error: {e}"
        try:
            return self.sess.run(_paste(), timeout=25)
        except Exception as e:
            return f"Could not apply Pine Script: {e}"


# ─────────────────────────────────────────────────────────────
# FULL ICT ANALYSIS (upgraded)
# ─────────────────────────────────────────────────────────────

def _full_ict_analysis(
    symbol:    str,
    timeframe: str   = "1h",
    htf:       bool  = True,
    bias_tf:   str   = None,
    exchange:  str   = "binance",
    player     = None,
    speak      = None,
) -> dict:
    """
    Run full ICT analysis with MTF engine.
    Draws on TradingView in real-time.
    """
    if player:
        player.write_log(f"[Trading] ICT Analysis: {symbol} {timeframe}")

    # ── Open TradingView ─────────────────────────
    drawer = TradingViewDrawer(symbol, timeframe, player, speak)
    drawer.open()

    if speak:
        speak(
            f"Opening TradingView for {symbol} on {timeframe}. "
            "Beginning full ICT analysis, sir."
        )

    drawer._show_notification("Initialising ICT engine...", "#00d4ff")
    drawer._show_panel("ANALYSING", "Starting", 5)

    try:
        engine = _get_mtf_engine(player, speak)
        engine._mt5    = _mt5_executor
        engine.player  = player
        engine.speak   = speak

        drawer._show_notification("Fetching market data...", "#00d4ff")
        drawer._show_panel("ANALYSING", "Fetching Data", 10)

        drawer._show_notification("Analysing Market Structure...", "#00d4ff")
        drawer._show_panel("ANALYSING", "Market Structure", 25)

        drawer._show_notification("Scanning Liquidity Pools...", "#ffcc00")
        drawer._show_panel("ANALYSING", "Liquidity", 40)

        drawer._show_notification("Detecting FVGs & Order Blocks...", "#8844ff")
        drawer._show_panel("ANALYSING", "FVG + OB", 55)

        # Run full analysis
        result = engine.analyse(
            symbol    = symbol,
            timeframe = timeframe,
            htf       = htf,
            bias_tf   = bias_tf,
            exchange  = exchange,
        )

        trend = result.get("trend", "UNKNOWN")

        drawer._show_notification("Validating ICT Sequence...", "#ff6b00")
        drawer._show_panel(trend, "ICT Sequence", 72)

        drawer._show_notification("Calculating targets...", "#00ff88")
        drawer._show_panel(trend, "Targets", 85)

        # Draw on chart
        drawer._show_notification("Applying to TradingView...", "#00d4ff")
        drawer._show_panel(trend, "Drawing", 94)

        pine = _generate_pine_script(result, symbol)

        # Save Pine Script
        save_path = (
            Path.home() / "Desktop" /
            f"jarvis_{symbol.replace('/', '')}_ict.pine"
        )
        save_path.write_text(pine, encoding="utf-8")
        print(f"[Trading] Pine saved: {save_path}")

        pine_result = drawer._apply_pine_script(pine)
        print(f"[Trading] {pine_result}")

        drawer._show_panel(trend, "✅ Complete", 100)
        drawer._update_final_panel(result)
        drawer._show_notification("✅ ICT Analysis complete", "#00ff88")

        # Voice summary
        if speak:
            setup_type = result.get("setup_type", "WAIT")
            valid      = result.get("valid", False)
            score      = result.get("score", 0)

            if valid:
                direction = result.get("direction", "")
                entry     = result.get("entry",     0)
                sl        = result.get("stop_loss", 0)
                tp1       = result.get("tp1",       0)
                tp2       = result.get("tp2",       0)
                rr        = result.get("rr_tp2",    0)
                e_type    = result.get("entry_type","")

                speak(
                    f"ICT analysis complete, sir. "
                    f"{symbol} shows a {setup_type} {direction} setup. "
                    f"Entry type is {e_type}. "
                    f"Quality score is {int(score*100)} percent. "
                    f"Entry at {entry:.5f}. "
                    f"Stop loss at {sl:.5f}. "
                    f"First target at {tp1:.5f}. "
                    f"Final target at {tp2:.5f}. "
                    f"Risk reward is {rr:.1f} to 1. "
                    f"All zones drawn on the chart, sir."
                )
            else:
                missing = result.get("missing", [])
                miss_str = (
                    missing[0] if missing
                    else "waiting for full sequence"
                )
                speak(
                    f"Analysis complete, sir. "
                    f"{symbol} is {trend} on {timeframe}. "
                    f"No valid setup yet. {miss_str}. "
                    f"All zones are drawn on the chart."
                )

        return result

    except Exception as e:
        import traceback
        traceback.print_exc()
        drawer._show_notification(f"❌ Analysis error: {e}", "#ff3355")
        return {"error": str(e), "valid": False, "setup_type": "WAIT"}


# ─────────────────────────────────────────────────────────────
# FORMAT OUTPUT (upgraded)
# ─────────────────────────────────────────────────────────────

def _format_result(result: dict) -> str:
    """Format full ICT result for display."""
    if "error" in result:
        return f"Analysis error: {result['error']}"

    from actions.trading.ict_engine import format_ict_setup
    setup_text = format_ict_setup(result)

    # Add MTF summary if available
    summary = result.get("summary", "")
    if summary:
        return f"{summary}\n\n{setup_text}"

    return setup_text


# ─────────────────────────────────────────────────────────────
# MAIN AGENT (fully upgraded)
# ─────────────────────────────────────────────────────────────

def trading_agent(
    parameters: dict,
    player      = None,
    speak       = None,
) -> str:
    params    = parameters or {}
    action    = params.get("action",         "analyse").lower().strip()
    symbol    = params.get("symbol",         "EURUSD").upper().strip()
    timeframe = params.get("timeframe",      "1h").lower().strip()
    exchange  = params.get("exchange",       "binance").lower().strip()
    htf_mode  = params.get("htf",            True)
    bias_tf   = params.get("bias_tf",        None)

    if player:
        player.write_log(f"[Trading] {action} {symbol} {timeframe}")

    # ════════════════════════════════════════════
    # ANALYSE / SCAN
    # ════════════════════════════════════════════
    if action in ("analyse", "analyze", "scan", "check", "ict"):
        result = _full_ict_analysis(
            symbol    = symbol,
            timeframe = timeframe,
            htf       = htf_mode,
            bias_tf   = bias_tf,
            exchange  = exchange,
            player    = player,
            speak     = speak,
        )
        return _format_result(result)

    # ════════════════════════════════════════════
    # MULTI-SYMBOL SCAN
    # ════════════════════════════════════════════
    elif action in ("watchlist", "multi_scan", "scan_all"):
        from actions.trading.mtf_engine import (
            MTFEngine, ALL_WATCHLIST, FOREX_MAJORS
        )
        symbols = params.get("symbols", FOREX_MAJORS)
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",")]

        min_score = float(params.get("min_score", 0.5))

        if speak:
            speak(
                f"Scanning {len(symbols)} pairs for ICT setups, sir. "
                "This will take a moment."
            )

        engine  = _get_mtf_engine(player, speak)
        results = engine.scan_symbols(
            symbols   = symbols,
            timeframe = timeframe,
            min_score = min_score,
        )

        if not results:
            if speak:
                speak(
                    f"No valid ICT setups found on {len(symbols)} pairs "
                    f"at {timeframe} timeframe, sir."
                )
            return f"No setups found on {len(symbols)} pairs ({timeframe})."

        lines = [
            f"📊 WATCHLIST SCAN — {timeframe.upper()}",
            f"{'─' * 42}",
            f"Found {len(results)} setups:\n",
        ]
        for r in results:
            em  = "🟢" if r["direction"] == "BULLISH" else "🔴"
            lines.append(
                f"{em} {r['symbol']:8s} | "
                f"{r['setup_type']:13s} | "
                f"Score: {r['score']*100:.0f}% | "
                f"R:R {r.get('rr_tp2', 0):.1f}:1"
            )

        if speak:
            best = results[0]
            speak(
                f"Scan complete, sir. Found {len(results)} setups. "
                f"Best is {best['symbol']} — "
                f"{best['direction']} {best['setup_type']} "
                f"with {int(best['score']*100)} percent quality "
                f"and {best.get('rr_tp2',0):.1f} to 1 risk reward."
            )

        return "\n".join(lines)

    # ════════════════════════════════════════════
    # MT5 CONNECT
    # ════════════════════════════════════════════
    elif action in ("connect", "login", "mt5_connect"):
        login    = params.get("mt5_login",    None)
        password = params.get("mt5_password", None)
        server   = params.get("mt5_server",   None)
        broker   = params.get("broker",       "default")
        path     = params.get("mt5_path",     None)

        executor = _get_mt5(player, speak)
        result   = executor.connect(
            login    = int(login) if login else None,
            password = password,
            server   = server,
            path     = path,
        )

        if result["success"]:
            # Save credentials for future use
            if login and password and server:
                from actions.trading.mt5_executor import save_mt5_credentials
                save_mt5_credentials(
                    int(login), password, server, broker
                )

            info = result.get("info", {})
            msg  = (
                f"Connected to {info.get('company', 'MT5')}, sir. "
                f"{info.get('type', 'DEMO')} account. "
                f"Balance: {info.get('balance', 0):.2f} "
                f"{info.get('currency', 'USD')}. "
                f"Leverage: 1:{info.get('leverage', 0)}."
            )
            if speak:
                speak(msg)

            # Set starting balance for risk manager
            rm = _get_risk_manager(player, speak)
            rm.guard.set_starting_balance(info.get("balance", 0))

            return f"MT5 Connected: {result['message']}\n{json.dumps(info, indent=2)}"
        else:
            if speak:
                speak(f"MT5 connection failed, sir. {result['message']}")
            return f"MT5 connection failed: {result['message']}"

    # ════════════════════════════════════════════
    # MT5 DISCONNECT
    # ════════════════════════════════════════════
    elif action in ("disconnect", "mt5_disconnect"):
        global _mt5_executor
        if _mt5_executor:
            _mt5_executor.disconnect()
            _mt5_executor = None
        if speak:
            speak("Disconnected from MT5, sir.")
        return "MT5 disconnected."

    # ════════════════════════════════════════════
    # TRADE (analyse + execute)
    # ════════════════════════════════════════════
    elif action in ("trade", "execute", "place_trade"):
        executor = _get_mt5(player, speak)
        if not executor.connected:
            # Try auto-connect with saved credentials
            from actions.trading.mt5_executor import get_executor
            executor, conn = get_executor(player=player, speak=speak)
            if not conn.get("success"):
                msg = (
                    "MT5 not connected, sir. "
                    "Please connect first with your broker credentials."
                )
                if speak:
                    speak(msg)
                return msg

        rm = _get_risk_manager(player, speak)

        # Run ICT analysis
        result = _full_ict_analysis(
            symbol    = symbol,
            timeframe = timeframe,
            htf       = htf_mode,
            exchange  = exchange,
            player    = player,
            speak     = speak,
        )

        if not result.get("valid"):
            msg = (
                f"No valid ICT setup on {symbol} {timeframe}, sir. "
                "Cannot place trade without full sequence confirmation."
            )
            if speak:
                speak(msg)
            return msg

        # Pre-trade checks
        account = executor.get_account_info()
        balance = account.get("balance", 0)

        pre_check = rm.pre_trade_check(
            symbol          = symbol,
            setup_score     = result.get("score", 0),
            account_balance = balance,
        )

        if not pre_check["allowed"]:
            msg = f"Trade blocked, sir. {pre_check['reason']}"
            if speak:
                speak(msg)
            return msg

        # Place trade
        risk_pct = float(params.get("risk_percent", 1.0))
        trade    = executor.place_trade(result, risk_pct)

        if trade.get("success"):
            rm.log_trade_entry(trade, result)
            return (
                f"✅ TRADE PLACED\n"
                f"{'─'*40}\n"
                f"Ticket:    #{trade['ticket']}\n"
                f"Symbol:    {trade['symbol']}\n"
                f"Direction: {trade['direction']}\n"
                f"Lots:      {trade['lot_size']}\n"
                f"Entry:     {trade['entry']:.5f}\n"
                f"SL:        {trade['stop_loss']:.5f}\n"
                f"TP1:       {trade['tp1']:.5f}\n"
                f"TP2:       {trade['tp2']:.5f}\n"
                f"Risk:      ${trade['risk_amount']:.2f}\n"
                f"SL Pips:   {trade['sl_pips']:.1f}\n"
            )
        else:
            return f"Trade failed: {trade.get('message', 'Unknown error')}"

    # ════════════════════════════════════════════
    # CLOSE TRADE
    # ════════════════════════════════════════════
    elif action in ("close", "close_trade"):
        ticket  = params.get("ticket",  None)
        percent = float(params.get("percent", 100.0))

        if not ticket:
            return "Please provide ticket number to close."

        executor = _get_mt5(player, speak)
        if not executor.connected:
            return "MT5 not connected."

        result = executor.close_trade(int(ticket), percent)
        if speak:
            speak(
                f"{'Full' if percent >= 100 else f'Partial {percent:.0f}%'} "
                f"close on ticket {ticket}: "
                f"{'done' if result['success'] else 'failed'}."
            )
        return result.get("message", "Done.")

    # ════════════════════════════════════════════
    # POSITIONS
    # ════════════════════════════════════════════
    elif action in ("positions", "open_trades", "portfolio"):
        executor = _get_mt5(player, speak)
        if not executor.connected:
            return "MT5 not connected. Use action='connect' first."

        text = executor.get_positions()
        pos  = executor.get_positions_raw()

        if speak:
            count = len(pos)
            if count == 0:
                speak("No open positions, sir.")
            else:
                total_pnl = sum(p.get("profit", 0) for p in pos)
                sign      = "up" if total_pnl >= 0 else "down"
                speak(
                    f"You have {count} open position"
                    f"{'s' if count > 1 else ''}. "
                    f"Total P and L is {sign} "
                    f"{abs(total_pnl):.2f}."
                )
        return text

    # ════════════════════════════════════════════
    # ACCOUNT INFO
    # ════════════════════════════════════════════
    elif action in ("account", "balance", "account_info"):
        executor = _get_mt5(player, speak)
        if not executor.connected:
            return "MT5 not connected."

        info = executor.get_account_info()
        if "error" in info:
            return info["error"]

        result = (
            f"💰 MT5 ACCOUNT\n{'─'*40}\n"
            f"Name:       {info['name']}\n"
            f"Login:      {info['login']}\n"
            f"Server:     {info['server']}\n"
            f"Broker:     {info['company']}\n"
            f"Type:       {info['type']}\n"
            f"Balance:    {info['balance']:.2f} {info['currency']}\n"
            f"Equity:     {info['equity']:.2f} {info['currency']}\n"
            f"Margin:     {info['margin']:.2f} {info['currency']}\n"
            f"Free:       {info['free_margin']:.2f} {info['currency']}\n"
            f"P&L:        {info['profit']:+.2f} {info['currency']}\n"
            f"Leverage:   1:{info['leverage']}\n"
        )

        if speak:
            speak(
                f"Account balance is "
                f"{info['balance']:.2f} {info['currency']}. "
                f"Equity is {info['equity']:.2f}. "
                f"Open P and L is {info['profit']:+.2f}."
            )
        return result

    # ════════════════════════════════════════════
    # MODIFY TRADE
    # ════════════════════════════════════════════
    elif action in ("modify", "modify_sl", "modify_tp"):
        ticket = params.get("ticket", None)
        new_sl = params.get("new_sl",  None)
        new_tp = params.get("new_tp",  None)

        if not ticket:
            return "Please provide ticket number."

        executor = _get_mt5(player, speak)
        if not executor.connected:
            return "MT5 not connected."

        result = executor.modify_sl_tp(
            int(ticket),
            float(new_sl) if new_sl else None,
            float(new_tp) if new_tp else None,
        )
        if speak:
            speak(result.get("message", "Modified."))
        return result.get("message", "Done.")

    # ════════════════════════════════════════════
    # PERFORMANCE / JOURNAL
    # ════════════════════════════════════════════
    elif action in ("performance", "stats", "journal", "report"):
        rm     = _get_risk_manager(player, speak)
        period = params.get("period", "all")
        report = rm.stats.format_stats(period=period)

        if speak:
            stats = rm.stats.calculate(period=period)
            if stats["total_trades"] > 0:
                speak(
                    f"Performance report for {period}. "
                    f"{stats['total_trades']} trades. "
                    f"Win rate {stats['win_rate']:.0f} percent. "
                    f"Average R:R {stats['avg_rr']:.1f} to 1. "
                    f"Total P and L {stats['total_pnl']:+.2f}."
                )
            else:
                speak("No completed trades in journal yet, sir.")

        return report

    # ════════════════════════════════════════════
    # RISK STATUS
    # ════════════════════════════════════════════
    elif action in ("risk_status", "risk", "limits"):
        rm       = _get_risk_manager(player, speak)
        executor = _get_mt5(player, speak)
        balance  = None

        if executor.connected:
            info    = executor.get_account_info()
            balance = info.get("balance")

        report = rm.guard.format_status(balance)
        if speak:
            check = rm.guard.can_trade(account_balance=balance)
            if check["allowed"]:
                speak("All risk limits are within bounds, sir.")
            else:
                speak(f"Risk warning, sir. {check['reason']}")
        return report

    # ════════════════════════════════════════════
    # SESSION INFO
    # ════════════════════════════════════════════
    elif action in ("session", "sessions", "killzone"):
        rm   = _get_risk_manager(player, speak)
        text = rm.session.format_sessions()

        if speak:
            active = rm.session.get_active_sessions()
            kz     = rm.session.is_killzone()
            if kz:
                speak(
                    "We are currently in an ICT killzone, sir. "
                    "Optimal time for entries."
                )
            elif active:
                names = ", ".join(s["name"] for s in active)
                nxt   = rm.session.get_next_killzone()
                speak(
                    f"Active sessions: {names}. "
                    f"Next killzone in "
                    f"{nxt.get('hours_away', 0):.1f} hours."
                    if nxt else f"Active sessions: {names}."
                )
            else:
                nxt = rm.session.get_next_killzone()
                speak(
                    f"No active sessions right now, sir. "
                    f"Next killzone: {nxt.get('name', '?')} "
                    f"in {nxt.get('hours_away', 0):.1f} hours."
                    if nxt else "No active sessions."
                )
        return text

    # ════════════════════════════════════════════
    # SAVE MT5 CREDENTIALS
    # ════════════════════════════════════════════
    elif action in ("save_credentials", "save_mt5", "setup_mt5"):
        login    = params.get("mt5_login",    "")
        password = params.get("mt5_password", "")
        server   = params.get("mt5_server",   "")
        broker   = params.get("broker",       "default")

        if not login or not password or not server:
            return (
                "Please provide mt5_login, mt5_password, "
                "and mt5_server to save credentials."
            )

        from actions.trading.mt5_executor import save_mt5_credentials
        ok = save_mt5_credentials(int(login), password, server, broker)

        if speak:
            speak(
                f"MT5 credentials saved for {broker} broker, sir."
                if ok else "Failed to save credentials."
            )
        return (
            f"✅ MT5 credentials saved for broker: {broker}"
            if ok else "❌ Failed to save credentials."
        )

    # ════════════════════════════════════════════
    # RISK CALCULATOR (original kept)
    # ════════════════════════════════════════════
    elif action in ("risk_calc", "position", "size"):
        account   = float(params.get("account_size",  1000))
        risk_pct  = float(params.get("risk_percent",  1))
        entry     = float(params.get("entry",         0))
        stop_loss = float(params.get("stop_loss",     0))

        if not entry or not stop_loss:
            return "Please provide entry and stop_loss prices."

        risk = _calculate_risk(account, risk_pct, entry, stop_loss, symbol)
        result = (
            f"💰 RISK CALCULATOR\n{'─'*40}\n"
            f"Account:       ${risk['account_size']:,.2f}\n"
            f"Risk %:        {risk['risk_percent']}%\n"
            f"Risk Amount:   ${risk['risk_amount']:,.2f}\n"
            f"Entry:         {risk['entry']:.5f}\n"
            f"Stop Loss:     {risk['stop_loss']:.5f}\n"
            f"Risk/Unit:     {risk['risk_per_unit']:.5f}\n"
            f"Position Size: {risk['position_size']:,.4f} units\n"
        )
        if speak:
            speak(
                f"For {risk_pct}% risk on "
                f"${account:,.0f}, position size is "
                f"{risk['position_size']:.4f} units, "
                f"risking ${risk['risk_amount']:.2f}."
            )
        return result

    # ════════════════════════════════════════════
    # OPEN TRADINGVIEW (original kept)
    # ════════════════════════════════════════════
    elif action in ("open", "tradingview", "chart"):
        drawer = TradingViewDrawer(symbol, timeframe, player, speak)
        opened = drawer.open()
        if speak:
            speak(f"Opening TradingView for {symbol}, sir.")
        return f"TradingView {'opened' if opened else 'failed'}: {symbol}"

    # ════════════════════════════════════════════
    # FIBONACCI (original kept)
    # ════════════════════════════════════════════
    elif action in ("fibonacci", "fib", "retracement"):
        high      = float(params.get("high", 0))
        low       = float(params.get("low",  0))
        direction = params.get("direction", "bullish").lower()

        if not high or not low:
            return "Please provide high and low prices."

        fib   = _calculate_fibonacci(high, low, direction)
        lines = [
            f"📐 FIBONACCI RETRACEMENT",
            f"{'─'*40}",
            f"High: {high:.5f} | Low: {low:.5f}",
            f"Direction: {direction.upper()}",
            "",
            "Key Levels:",
        ]
        for label, price in fib["levels"].items():
            marker = " ← OTE" if label in ("0.618", "0.786") else ""
            marker = " ← EQ"  if label == "0.5" else marker
            lines.append(f"  {label}: {price:.5f}{marker}")
        lines += [
            "",
            f"Premium:  {fib['premium_zone']['bottom']:.5f} — {fib['premium_zone']['top']:.5f}",
            f"Discount: {fib['discount_zone']['bottom']:.5f} — {fib['discount_zone']['top']:.5f}",
            f"OTE:      {fib['ote_zone']['bottom']:.5f} — {fib['ote_zone']['top']:.5f}",
        ]
        return "\n".join(lines)

    # ════════════════════════════════════════════
    # FULL REPORT
    # ════════════════════════════════════════════
    elif action in ("full_report", "dashboard"):
        rm       = _get_risk_manager(player, speak)
        executor = _get_mt5(player, speak)

        lines = ["🤖 JARVIS TRADING DASHBOARD", "═"*50, ""]

        # Account
        if executor.connected:
            info = executor.get_account_info()
            lines += [
                "💰 ACCOUNT:",
                f"  Balance: {info.get('balance',0):.2f} "
                f"{info.get('currency','USD')}",
                f"  Equity:  {info.get('equity',0):.2f}",
                f"  P&L:     {info.get('profit',0):+.2f}",
                f"  Type:    {info.get('type','?')}",
                "",
            ]
            lines.append(executor.get_positions())
            lines.append("")
        else:
            lines += ["❌ MT5 not connected", ""]

        lines += [
            rm.guard.format_status(),
            "",
            rm.session.format_sessions(),
            "",
            rm.stats.format_stats("today"),
        ]

        return "\n".join(lines)

    else:
        return (
            f"Unknown trading action: '{action}'. "
            "Available: analyse, trade, connect, disconnect, "
            "positions, account, close, modify, performance, "
            "risk_status, session, watchlist, fibonacci, "
            "risk_calc, open, save_credentials, full_report"
        )