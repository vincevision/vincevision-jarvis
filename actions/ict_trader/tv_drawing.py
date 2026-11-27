"""
TradingView Drawing Engine
Draws ICT/SMC analysis directly on TradingView charts
using keyboard shortcuts and mouse automation.
"""

import time
import pyautogui
from typing import Optional

pyautogui.FAILSAFE = False
pyautogui.PAUSE    = 0.1

COLORS = {
    "demand":      "#00E676",
    "supply":      "#FF1744",
    "bos":         "#2196F3",
    "choch":       "#FF9800",
    "mss":         "#E040FB",
    "fvg":         "#FFD740",
    "liquidity":   "#00BCD4",
    "inducement":  "#FF6E40",
    "entry":       "#00E5FF",
    "stop_loss":   "#FF1744",
    "take_profit": "#00E676",
    "equilibrium": "#9E9E9E",
}


class TVDrawingEngine:

    def __init__(self, tv_controller=None, player=None, speak=None):
        self.tv             = tv_controller
        self.player         = player
        self.speak          = speak
        self._chart_bounds  = None
        self._price_range   = None

    def log(self, msg: str):
        print(f"[TV-DRAW] {msg}")
        if self.player:
            try:
                self.player.write_log(f"[TV-DRAW] {msg}")
            except Exception:
                pass

    # ── Calibration ──────────────────────────────────────────────────────
    def calibrate_chart(
        self,
        price_high:     float,
        price_low:      float,
        chart_top_y:    int = None,
        chart_bottom_y: int = None,
    ):
        """Map price levels to screen Y coordinates."""
        sw, sh = pyautogui.size()
        if chart_top_y    is None: chart_top_y    = int(sh * 0.09)
        if chart_bottom_y is None: chart_bottom_y = int(sh * 0.88)

        self._chart_bounds = {
            "top_y":    chart_top_y,
            "bottom_y": chart_bottom_y,
            "left_x":   int(sw * 0.04),
            "right_x":  int(sw * 0.86),
        }
        self._price_range = {
            "high": price_high,
            "low":  price_low,
        }
        self.log(
            f"Calibrated [{price_low:.5f} — {price_high:.5f}] "
            f"Y:[{chart_top_y}—{chart_bottom_y}]"
        )

    def price_to_y(self, price: float) -> int:
        """Convert a price to screen Y coordinate."""
        if not self._chart_bounds or not self._price_range:
            sh = pyautogui.size()[1]
            return int(sh * 0.5)
        pr = self._price_range["high"] - self._price_range["low"]
        if pr <= 0:
            return self._chart_bounds["top_y"]
        pct    = (self._price_range["high"] - price) / pr
        yr     = self._chart_bounds["bottom_y"] - self._chart_bounds["top_y"]
        return int(self._chart_bounds["top_y"] + pct * yr)

    # ── Primitive Drawing ────────────────────────────────────────────────
    def draw_horizontal_line(
        self,
        price:  float,
        color:  str = "#FFFFFF",
        label:  str = "",
        style:  str = "solid",
    ) -> bool:
        try:
            if self.tv: self.tv._focus_tv_window()
            time.sleep(0.15)

            y  = self.price_to_y(price)
            sw = pyautogui.size()[0]
            cx = int(sw * 0.44)

            pyautogui.hotkey("alt", "h")
            time.sleep(0.4)
            pyautogui.click(cx, y)
            time.sleep(0.3)
            pyautogui.press("escape")
            time.sleep(0.15)
            return True
        except Exception as e:
            self.log(f"draw_horizontal_line failed: {e}")
            return False

    def draw_zone(
        self,
        high:       float,
        low:        float,
        color:      str   = "#00E676",
        label:      str   = "",
        zone_type:  str   = "demand",
    ) -> bool:
        try:
            if self.tv: self.tv._focus_tv_window()
            time.sleep(0.15)

            y_top    = self.price_to_y(high)
            y_bottom = self.price_to_y(low)
            sw       = pyautogui.size()[0]
            left_x   = int(sw * 0.09)
            right_x  = int(sw * 0.84)

            pyautogui.hotkey("alt", "shift", "r")
            time.sleep(0.45)

            # Click top-left then bottom-right
            pyautogui.click(left_x, y_top)
            time.sleep(0.18)
            pyautogui.click(right_x, y_bottom)
            time.sleep(0.3)
            pyautogui.press("escape")
            time.sleep(0.15)

            self.log(f"Zone: {zone_type} [{low:.5f}—{high:.5f}]")
            return True
        except Exception as e:
            self.log(f"draw_zone failed: {e}")
            return False

    def draw_label(
        self,
        price:  float,
        text:   str,
        x_pct:  float = 0.87,
    ) -> bool:
        try:
            if self.tv: self.tv._focus_tv_window()
            time.sleep(0.1)

            sw  = pyautogui.size()[0]
            x   = int(sw * x_pct)
            y   = self.price_to_y(price)

            pyautogui.hotkey("alt", "shift", "t")
            time.sleep(0.4)
            pyautogui.click(x, y)
            time.sleep(0.25)
            pyautogui.typewrite(text[:40], interval=0.025)
            time.sleep(0.15)
            pyautogui.press("escape")
            time.sleep(0.12)
            return True
        except Exception as e:
            self.log(f"draw_label failed: {e}")
            return False

    def draw_trendline(
        self,
        x1_pct:  float,
        y1_price: float,
        x2_pct:  float,
        y2_price: float,
    ) -> bool:
        try:
            if self.tv: self.tv._focus_tv_window()
            time.sleep(0.15)

            sw = pyautogui.size()[0]
            x1 = int(sw * x1_pct)
            y1 = self.price_to_y(y1_price)
            x2 = int(sw * x2_pct)
            y2 = self.price_to_y(y2_price)

            pyautogui.hotkey("alt", "t")
            time.sleep(0.4)
            pyautogui.click(x1, y1)
            time.sleep(0.2)
            pyautogui.click(x2, y2)
            time.sleep(0.3)
            pyautogui.press("escape")
            time.sleep(0.15)
            return True
        except Exception as e:
            self.log(f"draw_trendline failed: {e}")
            return False

    def draw_fib_retracement(
        self,
        high: float,
        low:  float,
        x1:   float = 0.18,
        x2:   float = 0.78,
    ) -> bool:
        try:
            if self.tv: self.tv._focus_tv_window()
            time.sleep(0.15)

            sw  = pyautogui.size()[0]
            ax1 = int(sw * x1)
            ay1 = self.price_to_y(high)
            ax2 = int(sw * x2)
            ay2 = self.price_to_y(low)

            pyautogui.hotkey("alt", "f")
            time.sleep(0.4)
            pyautogui.click(ax1, ay1)
            time.sleep(0.2)
            pyautogui.click(ax2, ay2)
            time.sleep(0.3)
            pyautogui.press("escape")
            time.sleep(0.15)
            return True
        except Exception as e:
            self.log(f"draw_fib failed: {e}")
            return False

    # ── Clear ────────────────────────────────────────────────────────────
    def clear_all_drawings(self):
        try:
            if self.tv: self.tv._focus_tv_window()
            time.sleep(0.2)
            pyautogui.hotkey("alt", "shift", "backspace")
            time.sleep(0.6)
            pyautogui.press("enter")
            time.sleep(0.3)
            self.log("All drawings cleared")
        except Exception as e:
            self.log(f"clear_all_drawings failed: {e}")

    # ── High-Level ICT Drawing ───────────────────────────────────────────
    def draw_supply_zone(
        self, high: float, low: float,
        label: str = "SUPPLY", strength: int = 5,
    ):
        self.draw_zone(high, low, color=COLORS["supply"], zone_type="supply")
        self.draw_label(high, f"SUPPLY S:{strength}")

    def draw_demand_zone(
        self, high: float, low: float,
        label: str = "DEMAND", strength: int = 5,
    ):
        self.draw_zone(high, low, color=COLORS["demand"], zone_type="demand")
        self.draw_label(low, f"DEMAND S:{strength}")

    def draw_fvg(self, high: float, low: float, fvg_type: str = "bullish"):
        arrow = "↑" if fvg_type == "bullish" else "↓"
        self.draw_zone(high, low, color=COLORS["fvg"], zone_type="fvg")
        self.draw_label((high + low) / 2, f"FVG {arrow}")

    def draw_bos(self, level: float, direction: str = "bullish"):
        arrow = "↑" if direction == "bullish" else "↓"
        self.draw_horizontal_line(level, color=COLORS["bos"])
        self.draw_label(level, f"BOS {arrow}", x_pct=0.72)

    def draw_choch(self, level: float, direction: str = "bullish"):
        arrow = "↑" if direction == "bullish" else "↓"
        self.draw_horizontal_line(level, color=COLORS["choch"])
        self.draw_label(level, f"CHoCH {arrow}", x_pct=0.72)

    def draw_mss(self, level: float, direction: str = "bullish"):
        arrow = "↑" if direction == "bullish" else "↓"
        self.draw_horizontal_line(level, color=COLORS["mss"])
        self.draw_label(level, f"MSS {arrow}", x_pct=0.72)

    def draw_liquidity_level(
        self, level: float, liq_type: str = "BSL", swept: bool = False,
    ):
        status = "SWEPT" if swept else "TARGET"
        self.draw_horizontal_line(level, color=COLORS["liquidity"])
        self.draw_label(level, f"{liq_type} {status}", x_pct=0.88)

    def draw_inducement(
        self, level: float, direction: str = "bullish", taken: bool = False,
    ):
        status = "TAKEN" if taken else "ACTIVE"
        self.draw_horizontal_line(level, color=COLORS["inducement"])
        self.draw_label(level, f"IDM {direction} {status}", x_pct=0.88)

    def draw_entry_setup(
        self,
        entry:     float,
        sl:        float,
        tp1:       float,
        tp2:       float = 0,
        tp3:       float = 0,
        direction: str   = "long",
    ):
        side = "LONG" if direction == "long" else "SHORT"
        self.draw_horizontal_line(entry, color=COLORS["entry"])
        self.draw_label(entry, f"ENTRY {side}", x_pct=0.88)
        self.draw_horizontal_line(sl, color=COLORS["stop_loss"])
        self.draw_label(sl, "STOP LOSS", x_pct=0.88)
        self.draw_horizontal_line(tp1, color=COLORS["take_profit"])
        self.draw_label(tp1, "TP1", x_pct=0.88)
        if tp2 > 0:
            self.draw_horizontal_line(tp2, color=COLORS["take_profit"])
            self.draw_label(tp2, "TP2", x_pct=0.88)
        if tp3 > 0:
            self.draw_horizontal_line(tp3, color=COLORS["take_profit"])
            self.draw_label(tp3, "TP3", x_pct=0.88)

    def draw_equilibrium(self, price: float):
        self.draw_horizontal_line(price, color=COLORS["equilibrium"])
        self.draw_label(price, "EQ 50%", x_pct=0.88)

    # ── Full Analysis Draw ───────────────────────────────────────────────
    def draw_full_analysis(
        self,
        analysis:    dict,
        confluence:  dict = None,
        clear_first: bool = True,
    ) -> int:
        """Draw complete ICT analysis on the chart."""
        self.log("Drawing full ICT analysis...")

        if clear_first:
            self.clear_all_drawings()
            time.sleep(0.6)

        drawn = 0

        # ── Calibrate from data ──────────────────────────────────────────
        prices = []
        for z in analysis.get("supply_zones", []):
            if isinstance(z, dict):
                prices += [z.get("high", 0), z.get("low", 0)]
        for z in analysis.get("demand_zones", []):
            if isinstance(z, dict):
                prices += [z.get("high", 0), z.get("low", 0)]
        for z in analysis.get("fvg", []):
            if isinstance(z, dict):
                prices += [z.get("high", 0), z.get("low", 0)]

        st = analysis.get("structure", {})
        for ev_list in (
            st.get("swing_highs", []),
            st.get("swing_lows", []),
            st.get("bos_events", []),
            st.get("choch_events", []),
            st.get("mss_events", []),
        ):
            for ev in ev_list:
                if isinstance(ev, dict):
                    prices.append(ev.get("price", ev.get("level", 0)))

        cp = analysis.get("current_price", 0)
        if cp: prices.append(cp)

        valid = [p for p in prices if p and p > 0]
        if valid:
            margin = (max(valid) - min(valid)) * 0.12
            self.calibrate_chart(
                max(valid) + margin,
                min(valid) - margin,
            )
        else:
            self.log("⚠️ No price data to calibrate — skipping draw")
            return 0

        # ── Supply Zones ─────────────────────────────────────────────────
        for zone in analysis.get("supply_zones", [])[:6]:
            if not isinstance(zone, dict): continue
            if zone.get("type") == "mitigated": continue
            h, l = zone.get("high", 0), zone.get("low", 0)
            if h > 0 and l > 0 and h > l:
                strength = zone.get("strength", 5)
                ob_tag   = " OB" if zone.get("is_order_block") else ""
                self.draw_supply_zone(h, l, strength=strength)
                drawn += 1
                time.sleep(0.25)

        # ── Demand Zones ─────────────────────────────────────────────────
        for zone in analysis.get("demand_zones", [])[:6]:
            if not isinstance(zone, dict): continue
            if zone.get("type") == "mitigated": continue
            h, l = zone.get("high", 0), zone.get("low", 0)
            if h > 0 and l > 0 and h > l:
                strength = zone.get("strength", 5)
                self.draw_demand_zone(h, l, strength=strength)
                drawn += 1
                time.sleep(0.25)

        # ── FVGs ─────────────────────────────────────────────────────────
        for fvg in analysis.get("fvg", [])[:6]:
            if not isinstance(fvg, dict): continue
            if fvg.get("filled"): continue
            h, l = fvg.get("high", 0), fvg.get("low", 0)
            if h > 0 and l > 0 and h > l:
                self.draw_fvg(h, l, fvg.get("type", "bullish"))
                drawn += 1
                time.sleep(0.22)

        # ── Structure Events ─────────────────────────────────────────────
        for bos in st.get("bos_events", [])[-4:]:
            if isinstance(bos, dict) and bos.get("level", 0):
                self.draw_bos(bos["level"], bos.get("type", "bullish"))
                drawn += 1
                time.sleep(0.22)

        for choch in st.get("choch_events", [])[-3:]:
            if isinstance(choch, dict) and choch.get("level", 0):
                self.draw_choch(choch["level"], choch.get("type", "bullish"))
                drawn += 1
                time.sleep(0.22)

        for mss in st.get("mss_events", [])[-3:]:
            if isinstance(mss, dict) and mss.get("level", 0):
                self.draw_mss(mss["level"], mss.get("type", "bullish"))
                drawn += 1
                time.sleep(0.22)

        # ── Liquidity ────────────────────────────────────────────────────
        liq = analysis.get("liquidity", {})
        for lv in liq.get("buy_side", [])[-4:]:
            if isinstance(lv, dict) and lv.get("level", 0):
                self.draw_liquidity_level(
                    lv["level"], lv.get("type", "BSL"), lv.get("swept", False)
                )
                drawn += 1
                time.sleep(0.2)

        for lv in liq.get("sell_side", [])[-4:]:
            if isinstance(lv, dict) and lv.get("level", 0):
                self.draw_liquidity_level(
                    lv["level"], lv.get("type", "SSL"), lv.get("swept", False)
                )
                drawn += 1
                time.sleep(0.2)

        # ── Inducements ──────────────────────────────────────────────────
        for ind in analysis.get("inducements", [])[-4:]:
            if isinstance(ind, dict) and ind.get("level", 0):
                self.draw_inducement(
                    ind["level"], ind.get("type", "bullish"), ind.get("taken", False)
                )
                drawn += 1
                time.sleep(0.2)

        # ── Equilibrium ──────────────────────────────────────────────────
        pd = analysis.get("premium_discount", {})
        if pd.get("equilibrium", 0):
            self.draw_equilibrium(pd["equilibrium"])
            drawn += 1
            time.sleep(0.2)

        # ── Entry Setup from Confluence ──────────────────────────────────
        if confluence:
            entries = confluence.get("entry_zones", [])
            direction = confluence.get("trade_direction", "no_trade")
            if entries and direction != "no_trade":
                best = entries[0]
                ep   = best.get("entry_price", 0)
                sl   = best.get("stop_loss",   0)
                tp1  = best.get("take_profit_1", 0)
                tp2  = best.get("take_profit_2", 0)
                tp3  = best.get("take_profit_3", 0)
                if ep and sl and tp1:
                    self.draw_entry_setup(
                        entry=ep, sl=sl,
                        tp1=tp1, tp2=tp2, tp3=tp3,
                        direction=direction,
                    )
                    drawn += 1

        self.log(f"✅ Drew {drawn} elements on chart")
        return drawn