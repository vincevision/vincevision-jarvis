# actions/trading/mtf_engine.py
"""
Multi-Timeframe Engine
───────────────────────
Handles:
  - HTF data fetching  (D1 / H4 / H1 for bias)
  - LTF data fetching  (H1 / M15 / M5 for entry)
  - Automatic timeframe pairing
  - Top-down analysis  (HTF bias → LTF entry)
  - HTF → LTF confluence scoring
  - Single timeframe mode (fallback)
  - Data caching (avoid repeated API calls)
  - MT5 live data + yfinance fallback
"""

import time
import threading
from datetime import datetime, timedelta
from typing   import Optional
from pathlib  import Path
import pytz


# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────

# Timeframe hierarchy (highest → lowest)
TF_HIERARCHY = [
    "1M", "1W", "1D",
    "4h", "1h", "30m",
    "15m", "5m", "1m",
]

# Automatic HTF/LTF pairing
TF_PAIRS = {
    # Entry TF  → (Bias TF,  Context TF)
    "1m":  ("15m", "1h"),
    "5m":  ("1h",  "4h"),
    "15m": ("1h",  "4h"),
    "30m": ("4h",  "1D"),
    "1h":  ("4h",  "1D"),
    "4h":  ("1D",  "1W"),
    "1D":  ("1W",  "1M"),
}

# Candle limits per timeframe
TF_CANDLE_LIMITS = {
    "1m":  500,
    "5m":  500,
    "15m": 300,
    "30m": 300,
    "1h":  250,
    "4h":  200,
    "1D":  200,
    "1W":  100,
    "1M":  60,
}

# Cache expiry seconds per timeframe
TF_CACHE_EXPIRY = {
    "1m":  30,
    "5m":  60,
    "15m": 120,
    "30m": 180,
    "1h":  300,
    "4h":  600,
    "1D":  1800,
    "1W":  3600,
    "1M":  7200,
}

# yfinance interval mapping
YF_INTERVAL_MAP = {
    "1m":  "1m",
    "5m":  "5m",
    "15m": "15m",
    "30m": "30m",
    "1h":  "1h",
    "4h":  "1h",    # yfinance has no 4h — use 1h and resample
    "1D":  "1d",
    "1W":  "1wk",
    "1M":  "1mo",
}

# yfinance period mapping
YF_PERIOD_MAP = {
    "1m":  "1d",
    "5m":  "5d",
    "15m": "60d",
    "30m": "60d",
    "1h":  "730d",
    "4h":  "730d",
    "1D":  "5y",
    "1W":  "10y",
    "1M":  "10y",
}

# MT5 timeframe constants mapping
MT5_TF_MAP = {
    "1m":  1,
    "5m":  5,
    "15m": 15,
    "30m": 30,
    "1h":  16385,
    "4h":  16388,
    "1D":  16408,
    "1W":  32769,
    "1M":  49153,
}


# ─────────────────────────────────────────────────────────────
# CANDLE CACHE
# ─────────────────────────────────────────────────────────────

class CandleCache:
    """
    Thread-safe in-memory candle cache.
    Avoids repeated API calls for same symbol/timeframe.
    """

    def __init__(self):
        self._cache = {}
        self._lock  = threading.Lock()

    def _key(self, symbol: str, timeframe: str) -> str:
        return f"{symbol.upper()}_{timeframe.lower()}"

    def get(
        self,
        symbol:    str,
        timeframe: str,
    ) -> Optional[list[dict]]:
        """Get cached candles if not expired."""
        key    = self._key(symbol, timeframe)
        expiry = TF_CACHE_EXPIRY.get(timeframe, 60)

        with self._lock:
            if key not in self._cache:
                return None

            entry      = self._cache[key]
            age        = time.time() - entry["timestamp"]

            if age > expiry:
                del self._cache[key]
                return None

            return entry["candles"]

    def set(
        self,
        symbol:    str,
        timeframe: str,
        candles:   list[dict],
    ):
        """Store candles in cache."""
        key = self._key(symbol, timeframe)
        with self._lock:
            self._cache[key] = {
                "candles":   candles,
                "timestamp": time.time(),
            }

    def invalidate(self, symbol: str = None, timeframe: str = None):
        """Clear cache for symbol/timeframe or all."""
        with self._lock:
            if symbol and timeframe:
                key = self._key(symbol, timeframe)
                self._cache.pop(key, None)
            elif symbol:
                sym = symbol.upper()
                keys = [k for k in self._cache if k.startswith(sym)]
                for k in keys:
                    del self._cache[k]
            else:
                self._cache.clear()

    def stats(self) -> dict:
        """Cache statistics."""
        with self._lock:
            return {
                "entries": len(self._cache),
                "symbols": list({
                    k.split("_")[0]
                    for k in self._cache
                }),
            }


# Global cache instance
_CACHE = CandleCache()


# ─────────────────────────────────────────────────────────────
# TIMEFRAME UTILITIES
# ─────────────────────────────────────────────────────────────

def get_tf_pair(entry_tf: str) -> tuple[str, str]:
    """
    Get HTF bias and context timeframes for a given entry TF.

    Returns:
        (bias_tf, context_tf)
    """
    entry_tf = entry_tf.lower()
    pair     = TF_PAIRS.get(entry_tf)
    if pair:
        return pair

    # Fallback
    idx = TF_HIERARCHY.index(entry_tf) if entry_tf in TF_HIERARCHY else -1
    if idx > 0:
        bias_tf    = TF_HIERARCHY[idx - 1]
        context_tf = TF_HIERARCHY[max(idx - 2, 0)]
        return bias_tf, context_tf

    return "4h", "1D"


def tf_to_minutes(tf: str) -> int:
    """Convert timeframe string to minutes."""
    tf = tf.lower()
    mapping = {
        "1m": 1, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "4h": 240,
        "1d": 1440, "1w": 10080, "1mo": 43200,
    }
    for key, val in mapping.items():
        if tf.startswith(key[0]) and (
            tf == key or tf.replace("m", "") == key.replace("m", "")
        ):
            return val

    # Parse manually
    if tf.endswith("m"):
        try:
            return int(tf[:-1])
        except ValueError:
            pass
    if tf.endswith("h"):
        try:
            return int(tf[:-1]) * 60
        except ValueError:
            pass
    if tf.endswith("d"):
        return 1440
    if tf.endswith("w"):
        return 10080

    return 60


def normalize_tf(tf: str) -> str:
    """Normalize timeframe string to standard format."""
    tf = tf.lower().strip()
    mapping = {
        "m1": "1m", "m5": "5m", "m15": "15m", "m30": "30m",
        "h1": "1h", "h4": "4h",
        "d1": "1D", "w1": "1W", "mn": "1M",
        "1min": "1m", "5min": "5m", "15min": "15m",
        "hourly": "1h", "daily": "1D", "weekly": "1W",
        "60": "1h", "240": "4h", "1440": "1D",
        "15": "15m", "5": "5m", "30": "30m",
    }
    return mapping.get(tf, tf)


# ─────────────────────────────────────────────────────────────
# DATA FETCHER
# ─────────────────────────────────────────────────────────────

class DataFetcher:
    """
    Fetches OHLCV candle data from multiple sources.
    Priority: MT5 live → CCXT → yfinance → cache
    """

    def __init__(
        self,
        mt5_executor = None,
        player       = None,
    ):
        self._mt5    = mt5_executor
        self.player  = player

    def _log(self, msg: str):
        print(f"[MTF-Data] {msg}")
        if self.player:
            self.player.write_log(f"[MTF] {msg}")

    # ── Symbol resolver ───────────────────────────
    def _resolve_yf_symbol(self, symbol: str) -> str:
        """Map symbol to yfinance format."""
        mapping = {
            "XAUUSD": "GC=F",   "GOLD":  "GC=F",
            "XAGUSD": "SI=F",   "USOIL": "CL=F",
            "XTIUSD": "CL=F",   "WTI":   "CL=F",
            "EURUSD": "EURUSD=X","GBPUSD": "GBPUSD=X",
            "USDJPY": "JPY=X",  "AUDUSD": "AUDUSD=X",
            "USDCAD": "CAD=X",  "USDCHF": "CHF=X",
            "NZDUSD": "NZDUSD=X","GBPJPY": "GBPJPY=X",
            "EURJPY": "EURJPY=X","EURGBP": "EURGBP=X",
            "CADJPY": "CADJPY=X","CHFJPY": "CHFJPY=X",
            "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
            "US30":  "^DJI",    "NAS100": "^IXIC",
            "US500": "^GSPC",   "DAX":    "^GDAXI",
        }
        sym_up = symbol.upper().replace("/", "")
        return mapping.get(sym_up, f"{sym_up}=X")

    # ── MT5 fetch ─────────────────────────────────
    def _fetch_mt5(
        self,
        symbol:    str,
        timeframe: str,
        limit:     int,
    ) -> list[dict]:
        """Fetch candles directly from MT5."""
        if not self._mt5 or not self._mt5.connected:
            return []

        try:
            mt5    = self._mt5._mt5
            tf_int = MT5_TF_MAP.get(timeframe.lower())

            if tf_int is None:
                return []

            # Use TIMEFRAME constants from mt5
            tf_map_mt5 = {
                "1m":  mt5.TIMEFRAME_M1,
                "5m":  mt5.TIMEFRAME_M5,
                "15m": mt5.TIMEFRAME_M15,
                "30m": mt5.TIMEFRAME_M30,
                "1h":  mt5.TIMEFRAME_H1,
                "4h":  mt5.TIMEFRAME_H4,
                "1D":  mt5.TIMEFRAME_D1,
                "1W":  mt5.TIMEFRAME_W1,
                "1M":  mt5.TIMEFRAME_MN1,
            }

            mt5_tf = tf_map_mt5.get(timeframe)
            if mt5_tf is None:
                return []

            rates = mt5.copy_rates_from_pos(
                symbol, mt5_tf, 0, limit
            )

            if rates is None or len(rates) == 0:
                return []

            candles = []
            for r in rates:
                candles.append({
                    "timestamp": int(r["time"]) * 1000,
                    "time": datetime.fromtimestamp(
                        r["time"]
                    ).strftime("%Y-%m-%d %H:%M"),
                    "open":   float(r["open"]),
                    "high":   float(r["high"]),
                    "low":    float(r["low"]),
                    "close":  float(r["close"]),
                    "volume": float(r.get("tick_volume", 0)),
                    "source": "MT5",
                })

            self._log(
                f"MT5: {len(candles)} candles "
                f"{symbol} {timeframe}"
            )
            return candles

        except Exception as e:
            self._log(f"MT5 fetch error: {e}")
            return []

    # ── CCXT fetch ────────────────────────────────
    def _fetch_ccxt(
        self,
        symbol:    str,
        timeframe: str,
        limit:     int,
        exchange:  str = "binance",
    ) -> list[dict]:
        """Fetch candles from CCXT (crypto only)."""
        # Only use for crypto
        if not any(
            x in symbol.upper()
            for x in ["BTC", "ETH", "SOL", "BNB",
                       "XRP", "ADA", "DOT", "AVAX"]
        ):
            return []

        try:
            import ccxt as ccxt_lib

            ccxt_sym = (
                symbol.upper()
                .replace("USD", "/USDT")
                .replace("//", "/")
            )
            ex    = getattr(ccxt_lib, exchange)(
                {"enableRateLimit": True}
            )
            ohlcv = ex.fetch_ohlcv(ccxt_sym, timeframe, limit=limit)

            candles = []
            for row in ohlcv:
                candles.append({
                    "timestamp": row[0],
                    "time": datetime.fromtimestamp(
                        row[0] / 1000
                    ).strftime("%Y-%m-%d %H:%M"),
                    "open":   row[1],
                    "high":   row[2],
                    "low":    row[3],
                    "close":  row[4],
                    "volume": row[5],
                    "source": "CCXT",
                })

            self._log(
                f"CCXT: {len(candles)} candles "
                f"{ccxt_sym} {timeframe}"
            )
            return candles

        except Exception as e:
            self._log(f"CCXT error: {e}")
            return []

    # ── yfinance fetch ────────────────────────────
    def _fetch_yfinance(
        self,
        symbol:    str,
        timeframe: str,
        limit:     int,
    ) -> list[dict]:
        """Fetch candles from yfinance."""
        try:
            import yfinance as yf

            yf_sym    = self._resolve_yf_symbol(symbol)
            yf_tf     = YF_INTERVAL_MAP.get(timeframe.lower(), "1h")
            yf_period = YF_PERIOD_MAP.get(timeframe.lower(), "60d")

            self._log(
                f"yfinance: {yf_sym} "
                f"{yf_tf} period={yf_period}"
            )

            ticker = yf.Ticker(yf_sym)
            df     = ticker.history(
                period   = yf_period,
                interval = yf_tf,
                auto_adjust = True,
            )

            if df.empty:
                self._log(f"yfinance: empty for {yf_sym}")
                return []

            # Resample 1h → 4h if needed
            if timeframe.lower() == "4h":
                df = df.resample("4h").agg({
                    "Open":   "first",
                    "High":   "max",
                    "Low":    "min",
                    "Close":  "last",
                    "Volume": "sum",
                }).dropna()

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
                    "source":    "yfinance",
                })

            candles = candles[-limit:]
            self._log(
                f"yfinance: {len(candles)} candles "
                f"for {yf_sym}"
            )
            return candles

        except Exception as e:
            self._log(f"yfinance error: {e}")
            return []

    # ── Main fetch ────────────────────────────────
    def fetch(
        self,
        symbol:    str,
        timeframe: str,
        limit:     int   = None,
        exchange:  str   = "binance",
        force:     bool  = False,
    ) -> list[dict]:
        """
        Fetch candles with caching and fallback.
        Priority: cache → MT5 → CCXT → yfinance

        Args:
            symbol:    Trading symbol
            timeframe: Timeframe string
            limit:     Number of candles
            exchange:  CCXT exchange name
            force:     Force refresh (skip cache)

        Returns:
            List of OHLCV candle dicts
        """
        tf    = normalize_tf(timeframe)
        limit = limit or TF_CANDLE_LIMITS.get(tf, 200)

        # ── Cache check ───────────────────────────
        if not force:
            cached = _CACHE.get(symbol, tf)
            if cached:
                self._log(
                    f"Cache hit: {symbol} {tf} "
                    f"({len(cached)} candles)"
                )
                return cached

        # ── MT5 (live data) ───────────────────────
        candles = self._fetch_mt5(symbol, tf, limit)

        # ── CCXT ──────────────────────────────────
        if not candles:
            candles = self._fetch_ccxt(
                symbol, tf, limit, exchange
            )

        # ── yfinance ──────────────────────────────
        if not candles:
            candles = self._fetch_yfinance(symbol, tf, limit)

        if candles:
            _CACHE.set(symbol, tf, candles)
            self._log(
                f"✅ Fetched {len(candles)} candles: "
                f"{symbol} {tf}"
            )
        else:
            self._log(
                f"❌ All sources failed: {symbol} {tf}"
            )

        return candles


# ─────────────────────────────────────────────────────────────
# HTF CONFLUENCE SCORER
# ─────────────────────────────────────────────────────────────

def score_htf_confluence(
    htf_bias:    dict,
    ltf_setup:   dict,
) -> dict:
    """
    Score how well LTF setup aligns with HTF bias.

    Returns:
      {
        "score":        0.0 - 1.0,
        "aligned":      bool,
        "boost":        score multiplier,
        "description":  str,
        "factors":      list of what aligned,
      }
    """
    if not htf_bias or not ltf_setup:
        return {
            "score":       0.5,
            "aligned":     True,
            "boost":       1.0,
            "description": "No HTF data — neutral",
            "factors":     [],
        }

    htf_dir    = htf_bias.get("bias",        "UNKNOWN")
    htf_trade  = htf_bias.get("trade_with",  "WAIT")
    htf_str    = htf_bias.get("strength",    0.5)
    ltf_dir    = ltf_setup.get("direction",  "NONE")
    ltf_type   = ltf_setup.get("setup_type", "WAIT")

    score   = 0.0
    factors = []
    boost   = 1.0

    # ── Direction alignment ───────────────────────
    directions_match = (
        (ltf_dir == "BULLISH" and htf_trade == "LONG") or
        (ltf_dir == "BEARISH" and htf_trade == "SHORT")
    )

    if directions_match:
        score += 0.40
        factors.append(
            f"✅ Direction aligned: HTF {htf_dir} + LTF {ltf_dir}"
        )
        boost = 1.0 + (htf_str * 0.3)
    else:
        score -= 0.20
        factors.append(
            f"❌ Against HTF: HTF says {htf_trade} "
            f"but LTF is {ltf_dir}"
        )
        boost = 0.6

    # ── HTF strength ──────────────────────────────
    if htf_str >= 0.7:
        score += 0.15
        factors.append(
            f"✅ Strong HTF bias: {htf_str*100:.0f}%"
        )
    elif htf_str >= 0.5:
        score += 0.08
        factors.append(
            f"⚠️ Moderate HTF bias: {htf_str*100:.0f}%"
        )
    else:
        factors.append(
            f"⚠️ Weak HTF bias: {htf_str*100:.0f}%"
        )

    # ── Setup type bonus ──────────────────────────
    if ltf_type == "REVERSAL" and htf_dir != ltf_dir:
        # Reversal aligns with HTF
        score += 0.15
        factors.append(
            "✅ Reversal setup aligns with HTF direction"
        )
    elif ltf_type == "CONTINUATION" and directions_match:
        score += 0.20
        factors.append(
            "✅ Continuation in HTF direction — highest confidence"
        )

    # ── HTF events bonus ──────────────────────────
    htf_events = htf_bias.get("events", [])
    htf_mss    = [
        e for e in htf_events
        if e["type"] == "MSS"
    ]
    if htf_mss:
        score += 0.10
        factors.append(
            f"✅ HTF MSS supports direction: "
            f"{htf_mss[-1]['direction']}"
        )

    # ── Last high/low context ─────────────────────
    ltf_entry = ltf_setup.get("entry", 0)
    htf_high  = htf_bias.get("last_high", 0)
    htf_low   = htf_bias.get("last_low",  0)

    if ltf_dir == "BULLISH" and htf_low > 0:
        if ltf_entry > htf_low:
            score += 0.10
            factors.append(
                f"✅ Entry above HTF structure low "
                f"({htf_low:.5f})"
            )
        else:
            factors.append(
                f"⚠️ Entry below HTF low — weak position"
            )

    elif ltf_dir == "BEARISH" and htf_high > 0:
        if ltf_entry < htf_high:
            score += 0.10
            factors.append(
                f"✅ Entry below HTF structure high "
                f"({htf_high:.5f})"
            )
        else:
            factors.append(
                f"⚠️ Entry above HTF high — weak position"
            )

    aligned = directions_match and score >= 0.3

    return {
        "score":       round(min(max(score, 0.0), 1.0), 2),
        "aligned":     aligned,
        "boost":       round(boost, 2),
        "description": (
            "HTF confluence confirmed" if aligned
            else "HTF misaligned — reduce size or skip"
        ),
        "factors":     factors,
    }


# ─────────────────────────────────────────────────────────────
# MULTI-TIMEFRAME ANALYSER
# ─────────────────────────────────────────────────────────────

class MTFEngine:
    """
    Multi-Timeframe Analysis Engine.
    Orchestrates HTF bias + LTF entry analysis.
    """

    def __init__(
        self,
        mt5_executor = None,
        player       = None,
        speak        = None,
    ):
        self._fetcher = DataFetcher(mt5_executor, player)
        self.player   = player
        self.speak    = speak

    def _log(self, msg: str):
        print(f"[MTF] {msg}")
        if self.player:
            self.player.write_log(f"[MTF] {msg}")

    def _say(self, msg: str):
        if self.speak:
            self.speak(msg)

    # ── Single timeframe analysis ─────────────────
    def analyse_single(
        self,
        symbol:    str,
        timeframe: str,
        exchange:  str = "binance",
    ) -> dict:
        """
        Single timeframe ICT analysis.
        Used when HTF data not needed or unavailable.

        Returns ICT engine result dict.
        """
        from actions.trading.ict_engine import run_ict_engine

        tf      = normalize_tf(timeframe)
        self._log(f"Single TF: {symbol} {tf}")

        candles = self._fetcher.fetch(symbol, tf, exchange=exchange)
        if not candles:
            return {
                "error":      f"No data for {symbol} {tf}",
                "valid":      False,
                "setup_type": "WAIT",
            }

        result = run_ict_engine(
            candles   = candles,
            symbol    = symbol,
            timeframe = tf,
        )

        result["mode"]      = "SINGLE_TF"
        result["timeframe"] = tf
        return result

    # ── Multi-timeframe analysis ──────────────────
    def analyse_mtf(
        self,
        symbol:     str,
        entry_tf:   str,
        bias_tf:    str   = None,
        context_tf: str   = None,
        exchange:   str   = "binance",
    ) -> dict:
        """
        Full multi-timeframe top-down analysis.

        Flow:
          1. Fetch context TF (highest) → broad bias
          2. Fetch bias TF (medium)     → directional bias
          3. Fetch entry TF (lowest)    → exact entry
          4. Run ICT engine on entry TF
             with HTF bias as filter
          5. Score HTF-LTF confluence

        Args:
            symbol:     Trading symbol
            entry_tf:   Entry timeframe (e.g. "15m")
            bias_tf:    HTF bias timeframe (auto if None)
            context_tf: Broader context TF (auto if None)
            exchange:   Exchange for CCXT

        Returns:
            Complete MTF analysis dict
        """
        from actions.trading.ict_engine    import run_ict_engine
        from actions.trading.market_structure import get_htf_bias

        # ── Auto pair timeframes ──────────────────
        entry_tf = normalize_tf(entry_tf)
        if bias_tf is None or context_tf is None:
            auto_bias, auto_ctx = get_tf_pair(entry_tf)
            bias_tf    = normalize_tf(bias_tf    or auto_bias)
            context_tf = normalize_tf(context_tf or auto_ctx)

        self._log(
            f"MTF Analysis: {symbol} | "
            f"Context: {context_tf} → "
            f"Bias: {bias_tf} → "
            f"Entry: {entry_tf}"
        )

        # ── Fetch all timeframes ──────────────────
        self._log(f"Fetching {context_tf} (context)...")
        ctx_candles = self._fetcher.fetch(
            symbol, context_tf, exchange=exchange
        )

        self._log(f"Fetching {bias_tf} (bias)...")
        bias_candles = self._fetcher.fetch(
            symbol, bias_tf, exchange=exchange
        )

        self._log(f"Fetching {entry_tf} (entry)...")
        entry_candles = self._fetcher.fetch(
            symbol, entry_tf, exchange=exchange
        )

        if not entry_candles:
            return {
                "error":      f"No entry TF data for {symbol} {entry_tf}",
                "valid":      False,
                "setup_type": "WAIT",
                "mode":       "MTF",
            }

        # ── Context bias (broadest view) ──────────
        ctx_bias = None
        if ctx_candles:
            from actions.trading.market_structure import find_swings
            from actions.trading.market_structure import _atr as calc_atr
            ctx_atr    = calc_atr(ctx_candles)
            ctx_swings = find_swings(ctx_candles)
            ctx_bias   = get_htf_bias(ctx_candles)
            self._log(
                f"Context ({context_tf}): "
                f"{ctx_bias.get('bias', 'UNKNOWN')} | "
                f"Strength: {ctx_bias.get('strength', 0)*100:.0f}%"
            )

        # ── HTF bias (directional) ────────────────
        htf_bias = None
        if bias_candles:
            htf_bias = get_htf_bias(bias_candles)
            self._log(
                f"HTF ({bias_tf}): "
                f"{htf_bias.get('bias', 'UNKNOWN')} | "
                f"Trade: {htf_bias.get('trade_with', '?')} | "
                f"Strength: {htf_bias.get('strength', 0)*100:.0f}%"
            )
        elif ctx_bias:
            # Use context as HTF if bias unavailable
            htf_bias = ctx_bias

        # ── Entry TF ICT analysis ─────────────────
        self._log(f"Running ICT engine on {entry_tf}...")
        ltf_result = run_ict_engine(
            candles     = entry_candles,
            htf_candles = bias_candles or ctx_candles,
            symbol      = symbol,
            timeframe   = entry_tf,
        )

        # ── HTF-LTF confluence ────────────────────
        confluence = score_htf_confluence(htf_bias, ltf_result)
        self._log(
            f"HTF-LTF Confluence: "
            f"{'✅' if confluence['aligned'] else '❌'} "
            f"score={confluence['score']*100:.0f}% "
            f"boost={confluence['boost']}x"
        )

        # ── Adjust setup score with confluence ────
        if ltf_result.get("valid"):
            original_score = ltf_result.get("score", 0)
            boosted_score  = min(
                original_score * confluence["boost"], 1.0
            )
            ltf_result["score"]          = round(boosted_score, 2)
            ltf_result["original_score"] = original_score
            self._log(
                f"Score adjusted: "
                f"{original_score*100:.0f}% → "
                f"{boosted_score*100:.0f}%"
            )

        # ── Build full result ─────────────────────
        result = {
            **ltf_result,

            # MTF metadata
            "mode":        "MTF",
            "entry_tf":    entry_tf,
            "bias_tf":     bias_tf,
            "context_tf":  context_tf,

            # Timeframe data
            "entry_candles":  entry_candles,
            "bias_candles":   bias_candles,
            "ctx_candles":    ctx_candles,

            # Bias results
            "htf_bias":    htf_bias,
            "ctx_bias":    ctx_bias,
            "confluence":  confluence,

            # Summary
            "summary": _build_summary(
                symbol, entry_tf, bias_tf, context_tf,
                ltf_result, htf_bias, ctx_bias, confluence,
            ),
        }

        return result

    # ── Auto mode ─────────────────────────────────
    def analyse(
        self,
        symbol:     str,
        timeframe:  str,
        htf:        bool  = True,
        bias_tf:    str   = None,
        context_tf: str   = None,
        exchange:   str   = "binance",
    ) -> dict:
        """
        Auto-select single or multi-TF mode.

        Args:
            symbol:    Trading symbol
            timeframe: Primary timeframe
            htf:       Use multi-TF (default True)
            bias_tf:   Manual HTF bias TF
            context_tf: Manual context TF
            exchange:  Exchange name

        Returns:
            Full analysis result
        """
        if htf:
            return self.analyse_mtf(
                symbol     = symbol,
                entry_tf   = timeframe,
                bias_tf    = bias_tf,
                context_tf = context_tf,
                exchange   = exchange,
            )
        else:
            return self.analyse_single(
                symbol    = symbol,
                timeframe = timeframe,
                exchange  = exchange,
            )

    # ── Scanner ───────────────────────────────────
    def scan_symbols(
        self,
        symbols:   list[str],
        timeframe: str,
        exchange:  str   = "binance",
        htf:       bool  = True,
        min_score: float = 0.5,
    ) -> list[dict]:
        """
        Scan multiple symbols for valid setups.

        Returns list of valid setups sorted by score.
        """
        results = []
        self._log(
            f"Scanning {len(symbols)} symbols "
            f"on {timeframe}..."
        )

        for sym in symbols:
            try:
                self._log(f"Scanning {sym}...")
                result = self.analyse(
                    symbol    = sym,
                    timeframe = timeframe,
                    htf       = htf,
                    exchange  = exchange,
                )

                if (
                    result.get("valid") and
                    result.get("score", 0) >= min_score
                ):
                    results.append(result)
                    self._log(
                        f"✅ Setup found: {sym} "
                        f"score={result['score']*100:.0f}%"
                    )
                else:
                    self._log(f"⏳ No setup: {sym}")

                # Avoid rate limiting
                time.sleep(0.5)

            except Exception as e:
                self._log(f"Scan error {sym}: {e}")
                continue

        # Sort by score
        results.sort(
            key=lambda x: x.get("score", 0),
            reverse=True,
        )

        self._log(
            f"Scan complete: "
            f"{len(results)}/{len(symbols)} setups found"
        )
        return results


# ─────────────────────────────────────────────────────────────
# SUMMARY BUILDER
# ─────────────────────────────────────────────────────────────

def _build_summary(
    symbol:     str,
    entry_tf:   str,
    bias_tf:    str,
    context_tf: str,
    ltf_result: dict,
    htf_bias:   dict,
    ctx_bias:   dict,
    confluence: dict,
) -> str:
    """Build human readable MTF summary."""
    lines = [
        "🔭 MULTI-TIMEFRAME ANALYSIS",
        "─" * 46,
        f"Symbol:       {symbol}",
        f"Context TF:   {context_tf}",
        f"Bias TF:      {bias_tf}",
        f"Entry TF:     {entry_tf}",
        "",
    ]

    # Context
    if ctx_bias:
        lines += [
            f"📡 {context_tf} (Context):",
            f"  Bias:     {ctx_bias.get('bias', '?')}",
            f"  Strength: {ctx_bias.get('strength', 0)*100:.0f}%",
            "",
        ]

    # HTF
    if htf_bias:
        lines += [
            f"📡 {bias_tf} (HTF Bias):",
            f"  Bias:     {htf_bias.get('bias', '?')}",
            f"  Strength: {htf_bias.get('strength', 0)*100:.0f}%",
            f"  Trade:    {htf_bias.get('trade_with', '?')}",
            "",
        ]

    # Confluence
    lines += [
        "🔗 HTF-LTF Confluence:",
        f"  Score:    {confluence.get('score', 0)*100:.0f}%",
        f"  Aligned:  {'✅ YES' if confluence.get('aligned') else '❌ NO'}",
        f"  Boost:    {confluence.get('boost', 1.0)}x",
    ]

    for factor in confluence.get("factors", []):
        lines.append(f"  {factor}")

    lines.append("")

    # LTF result
    if ltf_result.get("valid"):
        dir_em = (
            "🟢 LONG"
            if ltf_result["direction"] == "BULLISH"
            else "🔴 SHORT"
        )
        lines += [
            f"⚡ {entry_tf} SETUP: {dir_em}",
            f"  Type:    {ltf_result.get('setup_type', '?')}",
            f"  Score:   {ltf_result.get('score', 0)*100:.0f}%",
            f"  Entry:   {ltf_result.get('entry', 0):.5f}",
            f"  SL:      {ltf_result.get('stop_loss', 0):.5f}",
            f"  TP1:     {ltf_result.get('tp1', 0):.5f}",
            f"  TP2:     {ltf_result.get('tp2', 0):.5f}",
            f"  R:R:     {ltf_result.get('rr_tp2', 0):.1f}:1",
        ]
    else:
        lines += [
            f"⏳ {entry_tf}: No valid setup found",
            f"  Status: {ltf_result.get('setup_type', 'WAIT')}",
        ]
        missing = ltf_result.get("missing", [])
        if missing:
            lines.append("  Missing:")
            for m in missing[:3]:
                lines.append(f"    • {m}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# COMMON FOREX PAIRS
# ─────────────────────────────────────────────────────────────

FOREX_MAJORS = [
    "EURUSD", "GBPUSD", "USDJPY",
    "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
]

FOREX_MINORS = [
    "EURGBP", "EURJPY", "GBPJPY",
    "AUDJPY", "CADJPY", "CHFJPY",
    "EURAUD", "GBPAUD",
]

METALS = ["XAUUSD", "XAGUSD"]

INDICES = ["US30", "NAS100", "US500", "DAX"]

ALL_WATCHLIST = FOREX_MAJORS + METALS


# ─────────────────────────────────────────────────────────────
# CONVENIENCE FUNCTIONS
# ─────────────────────────────────────────────────────────────

def quick_analyse(
    symbol:      str,
    entry_tf:    str    = "1h",
    htf:         bool   = True,
    mt5_executor = None,
    player       = None,
    speak        = None,
) -> dict:
    """
    Quick single-symbol analysis.
    Convenience wrapper around MTFEngine.
    """
    engine = MTFEngine(mt5_executor, player, speak)
    return engine.analyse(
        symbol    = symbol,
        timeframe = entry_tf,
        htf       = htf,
    )


def quick_scan(
    symbols:     list[str] = None,
    entry_tf:    str       = "1h",
    min_score:   float     = 0.5,
    mt5_executor = None,
    player       = None,
    speak        = None,
) -> list[dict]:
    """
    Quick multi-symbol scan.
    Convenience wrapper around MTFEngine.
    """
    symbols = symbols or ALL_WATCHLIST
    engine  = MTFEngine(mt5_executor, player, speak)
    return engine.scan_symbols(
        symbols   = symbols,
        timeframe = entry_tf,
        min_score = min_score,
    )