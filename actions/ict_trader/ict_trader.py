"""
ICT Smart Money Trader — Main Orchestrator
Full autonomous ICT/SMC trading system.
Opens TradingView, fetches live data, performs multi-TF analysis,
draws on charts, generates institutional-grade trade setups.
Dual AI: Groq (speed) + Gemini (depth + vision).
"""

import json
import time
import subprocess
import traceback
from pathlib  import Path
from datetime import datetime

from .ai_brain      import AIBrain
from .market_structure import MarketStructureEngine, TrendState
from .supply_demand import SupplyDemandEngine
from .liquidity     import LiquidityEngine
from .confluence    import ConfluenceEngine, TF_PAIRS
from .tv_controller import TVController
from .tv_drawing    import TVDrawingEngine
from .entry_engine  import EntryEngine, TradeSetup


# ── Paths ────────────────────────────────────────────────────────────────
ANALYSIS_DIR = Path.home() / ".jarvis" / "ict_trader"
for _sub in ["screenshots", "analysis", "setups", "reports"]:
    (ANALYSIS_DIR / _sub).mkdir(parents=True, exist_ok=True)

DEFAULT_HTF = "4h"
DEFAULT_LTF = "1h"


# ── API Key Retrieval ────────────────────────────────────────────────────
def _get_keys() -> tuple:
    gemini_key = groq_key = ""
    try:
        from core.credential_manager import get_credential
        gemini_key = get_credential("gemini", "api_key") or ""
        groq_key   = get_credential("groq",   "api_key") or ""
    except Exception:
        pass
    if not gemini_key or not groq_key:
        try:
            cfg_path = Path(__file__).resolve().parents[2] / "config" / "api_keys.json"
            with open(cfg_path) as f:
                cfg = json.load(f)
            gemini_key = gemini_key or cfg.get("gemini_api_key", "")
            groq_key   = groq_key   or (
                cfg.get("groq_api_key") or
                cfg.get("GROQ_API_KEY") or
                cfg.get("groq", "")
            )
        except Exception:
            pass
    return gemini_key, groq_key


# ── Live Candle Fetcher ──────────────────────────────────────────────────
def _fetch_live_candles(symbol: str, timeframe: str) -> list:
    """
    Fetch live OHLCV data from Yahoo Finance or Binance.
    Used when screenshot-based analysis is unavailable.
    """
    yf_sym_map = {
        "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X",
        "USDJPY": "USDJPY=X", "AUDUSD": "AUDUSD=X",
        "USDCAD": "USDCAD=X", "NZDUSD": "NZDUSD=X",
        "USDCHF": "USDCHF=X", "EURGBP": "EURGBP=X",
        "EURJPY": "EURJPY=X", "GBPJPY": "GBPJPY=X",
        "XAUUSD": "GC=F",     "XAGUSD": "SI=F",
        "BTCUSD": "BTC-USD",  "ETHUSD": "ETH-USD",
        "US30":   "^DJI",     "NAS100": "^IXIC",
        "SPX500": "^GSPC",    "US500":  "^GSPC",
    }
    yf_interval = {
        "1m":  "1m",  "5m":  "5m",  "15m": "15m",
        "30m": "30m", "1h":  "1h",  "4h":  "1h",
        "1d":  "1d",  "1w":  "1wk", "1M":  "1mo",
    }
    yf_period = {
        "1m":  "1d",  "5m":  "5d",  "15m": "5d",
        "30m": "1mo", "1h":  "1mo", "4h":  "3mo",
        "1d":  "1y",  "1w":  "2y",  "1M":  "5y",
    }

    yf_s   = yf_sym_map.get(symbol.upper(), symbol)
    intv   = yf_interval.get(timeframe, "1h")
    period = yf_period.get(timeframe, "1mo")

    # ── Try yfinance ─────────────────────────────────────────────────────
    try:
        import yfinance as yf
        df = yf.Ticker(yf_s).history(period=period, interval=intv)
        if df is not None and not df.empty:
            candles = [
                {
                    "open":   float(r["Open"]),
                    "high":   float(r["High"]),
                    "low":    float(r["Low"]),
                    "close":  float(r["Close"]),
                    "volume": float(r.get("Volume", 0)),
                }
                for _, r in df.iterrows()
            ]
            print(
                f"[ICT-TRADER] ✅ yfinance: "
                f"{len(candles)} candles {symbol} {timeframe}"
            )
            return candles
    except ImportError:
        print("[ICT-TRADER] yfinance missing — installing...")
        subprocess.run(
            ["pip", "install", "yfinance", "-q"],
            capture_output=True, timeout=60,
        )
        try:
            import yfinance as yf
            df = yf.Ticker(yf_s).history(period=period, interval=intv)
            if df is not None and not df.empty:
                return [
                    {
                        "open":   float(r["Open"]),
                        "high":   float(r["High"]),
                        "low":    float(r["Low"]),
                        "close":  float(r["Close"]),
                        "volume": float(r.get("Volume", 0)),
                    }
                    for _, r in df.iterrows()
                ]
        except Exception as e:
            print(f"[ICT-TRADER] yfinance retry failed: {e}")
    except Exception as e:
        print(f"[ICT-TRADER] yfinance error: {e}")

    # ── Try Binance for crypto ───────────────────────────────────────────
    if any(x in symbol.upper() for x in ["BTC", "ETH", "BNB", "SOL", "ADA"]):
        try:
            return _binance_candles(symbol, timeframe)
        except Exception as e:
            print(f"[ICT-TRADER] Binance error: {e}")

    return []


def _binance_candles(symbol: str, timeframe: str) -> list:
    import urllib.request
    tf_map = {
        "1m":  "1m",  "5m":  "5m",  "15m": "15m",
        "30m": "30m", "1h":  "1h",  "4h":  "4h",
        "1d":  "1d",  "1w":  "1w",
    }
    sym = symbol.upper().replace("USD", "USDT")
    tf  = tf_map.get(timeframe, "1h")
    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={sym}&interval={tf}&limit=200"
    )
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    return [
        {
            "open":   float(k[1]), "high":   float(k[2]),
            "low":    float(k[3]), "close":  float(k[4]),
            "volume": float(k[5]),
        }
        for k in data
    ]


# ── Build Analysis from Algo Engines ────────────────────────────────────
def _build_algo_analysis(
    ms_result,
    sd_result:  dict,
    liq_result: dict,
    candles:    list,
) -> dict:
    """Convert algorithmic engine results to standard analysis dict."""
    trend = ms_result.trend
    bias  = (
        "bullish" if trend == TrendState.BULLISH else
        "bearish" if trend == TrendState.BEARISH else
        "neutral"
    )

    # Current price
    current_price = 0.0
    if candles:
        last = candles[-1]
        current_price = float(
            last.get("close", 0) if isinstance(last, dict) else last[3]
        )

    # Structure
    structure = {
        "swing_highs": [
            {
                "price": sh.price, "index": sh.index,
                "type":  sh.swing_type.name if sh.swing_type else "HH",
                "significant": sh.significant,
            }
            for sh in ms_result.swing_highs[-12:]
        ],
        "swing_lows": [
            {
                "price": sl.price, "index": sl.index,
                "type":  sl.swing_type.name if sl.swing_type else "HL",
                "significant": sl.significant,
            }
            for sl in ms_result.swing_lows[-12:]
        ],
        "bos_events": [
            {
                "type": b.direction, "level": b.level,
                "index": b.index, "confirmed": b.confirmed,
            }
            for b in ms_result.bos_events[-6:]
        ],
        "choch_events": [
            {
                "type": c.direction, "level": c.level, "index": c.index,
            }
            for c in ms_result.choch_events[-4:]
        ],
        "mss_events": [
            {
                "type": m.direction, "level": m.level,
                "index": m.index, "displacement": m.displacement,
            }
            for m in ms_result.mss_events[-4:]
        ],
    }

    # Zones
    supply_zones = [
        {
            "high": z.high, "low": z.low,
            "origin_index": z.origin_index,
            "type": "fresh" if z.is_fresh else "mitigated",
            "strength": z.strength,
            "is_order_block": z.is_order_block,
        }
        for z in sd_result.get("supply", [])
    ]
    demand_zones = [
        {
            "high": z.high, "low": z.low,
            "origin_index": z.origin_index,
            "type": "fresh" if z.is_fresh else "mitigated",
            "strength": z.strength,
            "is_order_block": z.is_order_block,
        }
        for z in sd_result.get("demand", [])
    ]
    fvg_list = [
        {
            "high": f.high, "low": f.low, "index": f.index,
            "type": f.gap_type, "filled": f.filled,
        }
        for f in sd_result.get("fvg", [])
    ]

    # Liquidity
    buy_side = [
        {"level": lv.price, "type": lv.level_type, "swept": lv.swept}
        for lv in liq_result.get("buy_side", [])
    ]
    sell_side = [
        {"level": lv.price, "type": lv.level_type, "swept": lv.swept}
        for lv in liq_result.get("sell_side", [])
    ]
    inducements = [
        {
            "level": ind.price, "type": ind.direction,
            "taken": ind.taken, "index": ind.index,
        }
        for ind in liq_result.get("inducements", [])
    ]

    # Premium / Discount
    sh_prices = [s.price for s in ms_result.swing_highs[-6:]]
    sl_prices = [s.price for s in ms_result.swing_lows[-6:]]
    all_sp    = sh_prices + sl_prices
    if all_sp:
        hi      = max(all_sp)
        lo      = min(all_sp)
        eq      = (hi + lo) / 2
        premium = hi - (hi - lo) * 0.25
        disc    = lo + (hi - lo) * 0.25
        pos     = (
            "premium"     if current_price > premium else
            "discount"    if current_price < disc    else
            "equilibrium"
        )
    else:
        eq = premium = disc = current_price
        pos = "equilibrium"

    # Confidence
    conf = 45
    if ms_result.bos_events:   conf += 8
    if ms_result.choch_events: conf += 8
    if ms_result.mss_events:   conf += 12
    if supply_zones:           conf += 5
    if demand_zones:           conf += 5
    conf = min(conf, 72)

    return {
        "trend":         bias,
        "bias":          bias,
        "confidence":    conf,
        "current_price": current_price,
        "structure":     structure,
        "supply_zones":  supply_zones,
        "demand_zones":  demand_zones,
        "fvg":           fvg_list,
        "liquidity":     {"buy_side": buy_side, "sell_side": sell_side},
        "inducements":   inducements,
        "premium_discount": {
            "equilibrium":    eq,
            "premium_zone":   premium,
            "discount_zone":  disc,
            "current_position": pos,
        },
        "_source": "algorithmic",
    }


def _empty_analysis() -> dict:
    return {
        "trend": "ranging", "bias": "neutral", "confidence": 5,
        "current_price": 0,
        "supply_zones": [], "demand_zones": [], "fvg": [],
        "structure": {
            "swing_highs": [], "swing_lows": [],
            "bos_events": [], "choch_events": [], "mss_events": [],
        },
        "liquidity": {"buy_side": [], "sell_side": []},
        "inducements": [],
        "premium_discount": {},
    }


# ── Analyze One Timeframe ────────────────────────────────────────────────
def _analyze_timeframe(
    symbol:    str,
    timeframe: str,
    tv:        TVController,
    brain:     AIBrain,
    ms_eng:    MarketStructureEngine,
    sd_eng:    SupplyDemandEngine,
    liq_eng:   LiquidityEngine,
    log,
    screenshot_dir: Path,
) -> dict:
    """
    Full analysis pipeline for one timeframe.
    1. Try screenshot → Gemini Vision
    2. Fallback → yfinance candles → AI + algo analysis
    3. Last resort → pure algo analysis
    """
    # Switch timeframe
    tv.change_timeframe(timeframe)
    time.sleep(3)

    analysis = {}

    # ── Step 1: Screenshot + Vision ──────────────────────────────────────
    ss_path = str(
        screenshot_dir / f"{symbol}_{timeframe}_{int(time.time())}.png"
    )
    ss = tv.take_screenshot(ss_path)

    if ss and brain.gemini_key:
        log(f"Running Gemini Vision on {timeframe} screenshot...")
        analysis = brain.analyze_chart_image(ss, symbol, timeframe)
        if analysis.get("confidence", 0) >= 40:
            log(
                f"Vision OK: bias={analysis.get('bias')} "
                f"conf={analysis.get('confidence')}%"
            )
            return analysis
        else:
            log(f"Vision confidence too low ({analysis.get('confidence')}%) — using candles")

    # ── Step 2: Live candles + AI ────────────────────────────────────────
    log(f"Fetching live candles: {symbol} {timeframe}...")
    candles = _fetch_live_candles(symbol, timeframe)

    if candles and len(candles) >= 30:
        log(f"{len(candles)} candles fetched — running AI analysis...")

        # Algo engines first
        ms_result  = ms_eng.analyze(candles)
        sd_result  = sd_eng.find_zones(candles)
        liq_result = liq_eng.analyze(
            candles, ms_result.swing_highs, ms_result.swing_lows
        )

        # AI candle analysis (Groq fast → Gemini fallback)
        ai_analysis = brain.analyze_candles(candles, timeframe, symbol)

        if ai_analysis.get("confidence", 0) >= 35:
            log(
                f"AI candle analysis OK: "
                f"bias={ai_analysis.get('bias')} "
                f"conf={ai_analysis.get('confidence')}%"
            )
            # Merge: keep AI analysis but fill gaps from algo
            algo = _build_algo_analysis(ms_result, sd_result, liq_result, candles)
            if not ai_analysis.get("supply_zones"):
                ai_analysis["supply_zones"] = algo["supply_zones"]
            if not ai_analysis.get("demand_zones"):
                ai_analysis["demand_zones"] = algo["demand_zones"]
            if not ai_analysis.get("fvg"):
                ai_analysis["fvg"] = algo["fvg"]
            return ai_analysis
        else:
            # ── Step 3: Pure algo ────────────────────────────────────────
            log("AI analysis weak — using pure algorithmic analysis")
            return _build_algo_analysis(
                ms_result, sd_result, liq_result, candles
            )
    else:
        log(f"⚠️ No candle data for {symbol} {timeframe}")
        return _empty_analysis()


# ════════════════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ════════════════════════════════════════════════════════════════════════
def ict_trader(parameters: dict, player=None, speak=None) -> str:
    """
    ICT Smart Money Trader.

    Actions:
        analyze       — Full multi-TF top-down analysis + drawings
        quick         — Single TF analysis
        draw          — Draw a specific element
        setup         — Generate trade setup
        open          — Open TradingView
        change_tf     — Change timeframe
        change_symbol — Change symbol
        clear         — Clear all drawings
        screenshot    — Take chart screenshot
        scan          — Scan multiple pairs
        report        — Load last saved analysis
        install       — Install screenshot tools
        status        — System status
    """
    action = parameters.get("action", "analyze")
    symbol = parameters.get("symbol", "EURUSD").upper().replace("/", "")
    htf    = parameters.get("htf", parameters.get("timeframe", DEFAULT_HTF))
    ltf    = parameters.get("ltf", "")
    browser = parameters.get("browser", "firefox")

    def log(msg: str):
        print(f"[ICT-TRADER] {msg}")
        if player:
            try: player.write_log(f"[ICT] {msg}")
            except Exception: pass

    def say(msg: str):
        if speak:
            try: speak(msg)
            except Exception: pass

    try:
        gemini_key, groq_key = _get_keys()

        # ── Components ───────────────────────────────────────────────────
        brain      = AIBrain(gemini_key, groq_key)
        ms_eng     = MarketStructureEngine()
        sd_eng     = SupplyDemandEngine()
        liq_eng    = LiquidityEngine()
        conf_eng   = ConfluenceEngine()
        entry_eng  = EntryEngine(
            account_balance=float(parameters.get("account_balance", 10000))
        )
        tv         = TVController(browser=browser, player=player, speak=speak)
        drawing    = TVDrawingEngine(tv_controller=tv, player=player, speak=speak)
        ss_dir     = ANALYSIS_DIR / "screenshots"

        # ════════════════════════════════════════════════════════════════
        #  OPEN
        # ════════════════════════════════════════════════════════════════
        if action == "open":
            result = tv.open_tradingview(symbol)
            say(f"TradingView opened with {symbol}, sir.")
            return result

        # ════════════════════════════════════════════════════════════════
        #  CHANGE TF / SYMBOL
        # ════════════════════════════════════════════════════════════════
        elif action == "change_tf":
            tf = parameters.get("timeframe", htf)
            return tv.change_timeframe(tf)

        elif action == "change_symbol":
            return tv.change_symbol(symbol)

        # ════════════════════════════════════════════════════════════════
        #  CLEAR
        # ════════════════════════════════════════════════════════════════
        elif action == "clear":
            drawing.clear_all_drawings()
            return "All drawings cleared."

        # ════════════════════════════════════════════════════════════════
        #  SCREENSHOT
        # ════════════════════════════════════════════════════════════════
        elif action == "screenshot":
            path = tv.take_screenshot()
            return f"Screenshot: {path}" if path else "Screenshot failed."

        # ════════════════════════════════════════════════════════════════
        #  INSTALL TOOLS
        # ════════════════════════════════════════════════════════════════
        elif action == "install":
            tv.install_screenshot_tools()
            subprocess.run(
                ["pip", "install", "yfinance", "mss", "-q"],
                capture_output=True, timeout=120,
            )
            return "Screenshot tools and yfinance installed."

        # ════════════════════════════════════════════════════════════════
        #  STATUS
        # ════════════════════════════════════════════════════════════════
        elif action == "status":
            tv_open   = tv.is_tv_open()
            setups    = list((ANALYSIS_DIR / "setups").glob("*.json"))
            analyses  = list((ANALYSIS_DIR / "analysis").glob("*.json"))
            wayland   = tv._is_wayland
            return (
                f"ICT Trader Status\n"
                f"TradingView: {'Open ✅' if tv_open else 'Closed ❌'}\n"
                f"Display:     {'Wayland' if wayland else 'X11'}\n"
                f"Gemini:      {'✅' if gemini_key else '❌'}\n"
                f"Groq:        {'✅' if groq_key   else '❌'}\n"
                f"Analyses:    {len(analyses)}\n"
                f"Setups:      {len(setups)}\n"
            )

        # ════════════════════════════════════════════════════════════════
        #  REPORT
        # ════════════════════════════════════════════════════════════════
        elif action == "report":
            analyses = sorted(
                (ANALYSIS_DIR / "analysis").glob(f"{symbol}*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not analyses:
                return f"No analysis history for {symbol}."
            with open(analyses[0]) as f:
                data = json.load(f)
            lines = [
                f"═══ ICT Report: {symbol} ═══",
                f"Time:      {data.get('timestamp', 'unknown')}",
                f"HTF/LTF:   {data.get('htf')} / {data.get('ltf')}",
                f"Score:     {data.get('final_score', 0)}/100",
                f"Direction: {data.get('trade_direction', 'none').upper()}",
            ]
            conf = data.get("confluence", {})
            if conf.get("narrative"):
                lines.append(f"\n{conf['narrative'][:400]}")
            return "\n".join(lines)

        # ════════════════════════════════════════════════════════════════
        #  QUICK ANALYSIS (single TF)
        # ════════════════════════════════════════════════════════════════
        elif action == "quick":
            log(f"Quick analysis: {symbol} {htf}")
            say(f"Quick ICT analysis on {symbol} {htf}, sir.")

            if not tv.is_tv_open():
                tv.open_tradingview(symbol)
                time.sleep(4)
            else:
                tv.change_symbol(symbol)
                time.sleep(2)

            analysis = _analyze_timeframe(
                symbol, htf, tv, brain,
                ms_eng, sd_eng, liq_eng, log, ss_dir,
            )

            # Draw
            drawing.draw_full_analysis(analysis)

            bias  = analysis.get("bias", "neutral")
            conf  = analysis.get("confidence", 0)
            src   = analysis.get("_source", "ai_vision")
            result = (
                f"Quick Analysis: {symbol} {htf}\n"
                f"Bias:      {bias.upper()}\n"
                f"Confidence:{conf}%\n"
                f"Trend:     {analysis.get('trend', 'unknown')}\n"
                f"Supply:    {len(analysis.get('supply_zones', []))} zones\n"
                f"Demand:    {len(analysis.get('demand_zones', []))} zones\n"
                f"FVGs:      {len(analysis.get('fvg', []))}\n"
                f"Source:    {src}\n"
                f"Drawn on chart ✅"
            )
            say(
                f"Quick analysis done. {symbol} {htf} is {bias} "
                f"with {conf}% confidence, sir."
            )
            return result

        # ════════════════════════════════════════════════════════════════
        #  FULL ANALYSIS (multi-TF)
        # ════════════════════════════════════════════════════════════════
        elif action in ("analyze", "setup"):
            if not ltf:
                ltf = TF_PAIRS.get(htf, ["1h", "15m"])[0]

            log(f"Full ICT analysis: {symbol} HTF={htf} LTF={ltf}")
            say(
                f"Starting full ICT top-down analysis on {symbol}. "
                f"High timeframe {htf}, entry timeframe {ltf}."
            )

            # ── Open TradingView ─────────────────────────────────────────
            if not tv.is_tv_open():
                tv.open_tradingview(symbol)
                time.sleep(5)
            else:
                tv.change_symbol(symbol)
                time.sleep(2.5)

            # ── HTF Analysis ─────────────────────────────────────────────
            log(f"Analyzing HTF: {htf}")
            say(f"Analyzing {htf} structure for {symbol}.")
            htf_analysis = _analyze_timeframe(
                symbol, htf, tv, brain,
                ms_eng, sd_eng, liq_eng, log, ss_dir,
            )
            htf_bias = htf_analysis.get("bias", "neutral")
            htf_conf = htf_analysis.get("confidence", 0)
            log(f"HTF: bias={htf_bias} conf={htf_conf}%")

            # ── LTF Analysis ─────────────────────────────────────────────
            log(f"Analyzing LTF: {ltf}")
            say(f"Dropping to {ltf} for entry confirmation.")
            ltf_analysis = _analyze_timeframe(
                symbol, ltf, tv, brain,
                ms_eng, sd_eng, liq_eng, log, ss_dir,
            )
            ltf_bias = ltf_analysis.get("bias", "neutral")
            ltf_conf = ltf_analysis.get("confidence", 0)
            log(f"LTF: bias={ltf_bias} conf={ltf_conf}%")

            # ── Multi-TF Confluence ──────────────────────────────────────
            log("Computing multi-TF confluence...")
            current_price = (
                htf_analysis.get("current_price") or
                ltf_analysis.get("current_price") or 0.0
            )

            # AI confluence (Gemini deep analysis)
            ai_conf = brain.multi_tf_confluence(
                htf_analysis, ltf_analysis, htf, ltf, symbol
            )

            # Algorithmic confluence
            algo_conf = conf_eng.find_confluence(
                htf_analysis, ltf_analysis, htf, ltf, current_price
            )

            # Combine scores (60% AI, 40% algo)
            ai_score   = ai_conf.get("confluence_score", 0)
            algo_score = algo_conf.score
            final_score = int(ai_score * 0.6 + algo_score * 0.4)

            trade_dir  = ai_conf.get("trade_direction", "no_trade")
            narrative  = (
                ai_conf.get("narrative") or
                algo_conf.narrative or
                "Monitoring market structure."
            )

            log(
                f"Confluence: AI={ai_score} Algo={algo_score} "
                f"Final={final_score} Dir={trade_dir}"
            )

            # ── Draw HTF ─────────────────────────────────────────────────
            log("Drawing HTF analysis...")
            say("Drawing structure and zones on the chart.")
            tv.change_timeframe(htf)
            time.sleep(2)
            drawing.draw_full_analysis(htf_analysis, clear_first=True)
            time.sleep(1)

            # ── Draw LTF + Entry ─────────────────────────────────────────
            log("Drawing LTF analysis + entry setup...")
            tv.change_timeframe(ltf)
            time.sleep(2)
            drawing.draw_full_analysis(
                ltf_analysis,
                confluence=ai_conf if final_score >= 55 else None,
                clear_first=False,
            )

            # ── Generate Trade Setup ─────────────────────────────────────
            setup = None
            entry_zones = ai_conf.get("entry_zones", [])

            if final_score >= 55 and entry_zones and trade_dir != "no_trade":
                best = entry_zones[0]
                setup = entry_eng.create_setup(
                    symbol=symbol,
                    direction=trade_dir,
                    entry=best.get("entry_price",   0),
                    sl=best.get("stop_loss",        0),
                    tp1=best.get("take_profit_1",   0),
                    tp2=best.get("take_profit_2",   0),
                    tp3=best.get("take_profit_3",   0),
                    confidence=final_score,
                    entry_type=best.get("type",     ""),
                    htf=htf,
                    ltf=ltf,
                    narrative=narrative,
                )

            # ── Also try algo-generated setup ────────────────────────────
            if not setup and algo_conf.score >= 55 and algo_conf.direction != "no_trade":
                setup = entry_eng.create_setup(
                    symbol=symbol,
                    direction=algo_conf.direction,
                    entry=algo_conf.entry_price,
                    sl=algo_conf.stop_loss,
                    tp1=algo_conf.tp1,
                    tp2=algo_conf.tp2,
                    tp3=algo_conf.tp3,
                    confidence=algo_conf.score,
                    entry_type=algo_conf.entry_type,
                    htf=htf,
                    ltf=ltf,
                    narrative=algo_conf.narrative,
                )
                if setup:
                    drawing.draw_entry_setup(
                        entry=setup.entry_price,
                        sl=setup.stop_loss,
                        tp1=setup.tp1,
                        tp2=setup.tp2,
                        tp3=setup.tp3,
                        direction=setup.direction,
                    )

            # ── Save Analysis ────────────────────────────────────────────
            save_data = {
                "timestamp":      datetime.now().isoformat(),
                "symbol":         symbol,
                "htf":            htf,
                "ltf":            ltf,
                "htf_analysis":   {
                    k: v for k, v in htf_analysis.items()
                    if k != "_source"
                },
                "ltf_analysis":   {
                    k: v for k, v in ltf_analysis.items()
                    if k != "_source"
                },
                "confluence":     ai_conf,
                "ai_score":       ai_score,
                "algo_score":     algo_score,
                "final_score":    final_score,
                "trade_direction": trade_dir,
            }
            try:
                sp = (
                    ANALYSIS_DIR / "analysis" /
                    f"{symbol}_{htf}_{ltf}_{int(time.time())}.json"
                )
                with open(sp, "w") as f:
                    json.dump(save_data, f, indent=2, default=str)
                log(f"Analysis saved: {sp.name}")
            except Exception as e:
                log(f"Save failed: {e}")

            if setup:
                try:
                    sp2 = (
                        ANALYSIS_DIR / "setups" /
                        f"{symbol}_{trade_dir}_{int(time.time())}.json"
                    )
                    with open(sp2, "w") as f:
                        json.dump(vars(setup), f, indent=2, default=str)
                except Exception:
                    pass

            # ── Build Result ─────────────────────────────────────────────
            lines = [
                f"═══ ICT Analysis: {symbol} ═══",
                f"HTF ({htf}):  {htf_bias.upper()} | {htf_conf}% confidence",
                f"LTF ({ltf}):  {ltf_bias.upper()} | {ltf_conf}% confidence",
                f"",
                f"Confluence:   {final_score}/100  "
                f"(AI:{ai_score} | Algo:{algo_score})",
                f"Direction:    {trade_dir.upper()}",
                f"",
                f"Supply zones: {len(htf_analysis.get('supply_zones', []))}",
                f"Demand zones: {len(htf_analysis.get('demand_zones', []))}",
                f"FVGs:         {len(htf_analysis.get('fvg', []))}",
                f"",
                f"Narrative:",
                f"{narrative[:300]}",
            ]
            if setup:
                lines += ["", entry_eng.format_setup(setup)]

            result = "\n".join(lines)

            # ── Speak ────────────────────────────────────────────────────
            say_msg = (
                f"ICT analysis complete for {symbol}. "
                f"The {htf} bias is {htf_bias} with a confluence "
                f"score of {final_score} out of 100. "
            )
            if setup:
                say_msg += (
                    f"I found a {trade_dir} setup. "
                    f"Entry at {setup.entry_price:.5f}, "
                    f"stop at {setup.stop_loss:.5f}, "
                    f"risk reward {setup.risk_reward} to 1. "
                    f"All levels drawn on the chart, sir."
                )
            else:
                say_msg += (
                    "No high-confidence setup right now. "
                    "Structure and zones drawn on the chart."
                )
            say(say_msg)
            return result

        # ════════════════════════════════════════════════════════════════
        #  DRAW
        # ════════════════════════════════════════════════════════════════
        elif action == "draw":
            draw_type = parameters.get(
                "draw_type", parameters.get("type", "line")
            )
            price  = float(parameters.get("price",  0))
            price2 = float(parameters.get("price2", 0))
            label  = parameters.get("label", "")
            direction = parameters.get("direction", "bullish")

            if not tv.is_tv_open():
                return "TradingView is not open. Use action=open first."

            if price and price2:
                margin = abs(price - price2) * 0.5
                drawing.calibrate_chart(
                    max(price, price2) + margin,
                    min(price, price2) - margin,
                )

            dispatch = {
                "supply":     lambda: drawing.draw_supply_zone(price, price2),
                "demand":     lambda: drawing.draw_demand_zone(price2, price),
                "bos":        lambda: drawing.draw_bos(price, direction),
                "choch":      lambda: drawing.draw_choch(price, direction),
                "mss":        lambda: drawing.draw_mss(price, direction),
                "fvg":        lambda: drawing.draw_fvg(
                    price, price2, parameters.get("fvg_type", "bullish")
                ),
                "liquidity":  lambda: drawing.draw_liquidity_level(
                    price, parameters.get("liq_type", "BSL"),
                    parameters.get("swept", False),
                ),
                "inducement": lambda: drawing.draw_inducement(
                    price, direction, parameters.get("taken", False)
                ),
                "line":       lambda: drawing.draw_horizontal_line(price, label=label),
                "fib":        lambda: drawing.draw_fib_retracement(price, price2),
                "entry":      lambda: drawing.draw_entry_setup(
                    entry=price, sl=price2,
                    tp1=float(parameters.get("tp1", 0)),
                    tp2=float(parameters.get("tp2", 0)),
                    tp3=float(parameters.get("tp3", 0)),
                    direction=parameters.get("direction", "long"),
                ),
            }
            fn = dispatch.get(draw_type)
            if fn:
                fn()
                return f"Drew {draw_type} on chart."
            return f"Unknown draw type: {draw_type}"

        # ════════════════════════════════════════════════════════════════
        #  SCAN
        # ════════════════════════════════════════════════════════════════
        elif action == "scan":
            symbols = parameters.get("symbols", [])
            if not symbols:
                symbols = [
                    "EURUSD", "GBPUSD", "USDJPY",
                    "XAUUSD", "GBPJPY", "EURJPY",
                    "AUDUSD", "USDCAD",
                ]

            log(f"Scanning {len(symbols)} pairs on {htf}...")
            say(f"Scanning {len(symbols)} pairs for ICT setups on {htf}, sir.")

            results = []
            for sym in symbols:
                try:
                    log(f"Scanning {sym}...")
                    p = {"action": "quick", "symbol": sym, "htf": htf, "browser": browser}
                    r = ict_trader(p, player, None)
                    results.append({"symbol": sym, "result": r[:200]})
                    time.sleep(1.5)
                except Exception as e:
                    results.append({"symbol": sym, "result": f"Error: {e}"})

            summary = f"Scan complete ({len(symbols)} pairs on {htf}):\n"
            for r in results:
                summary += f"• {r['symbol']}: {r['result'][:120]}\n"

            say(f"Scan complete, sir. Checked {len(symbols)} pairs.")
            return summary

        else:
            return (
                f"Unknown action: {action}\n"
                f"Available: analyze, quick, draw, setup, open, "
                f"change_tf, change_symbol, clear, screenshot, "
                f"scan, report, install, status"
            )

    except Exception as e:
        msg = f"ICT Trader error: {e}"
        log(msg)
        traceback.print_exc()
        return msg