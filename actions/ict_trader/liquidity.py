"""
Liquidity & Inducement Detection Engine
Finds equal highs/lows, liquidity pools, stop hunts, and inducements.
"""

from dataclasses import dataclass
from typing import List


@dataclass
class LiquidityLevel:
    price:       float
    level_type:  str    # EQH | EQL | BSL | SSL
    side:        str    # buy_side | sell_side
    index:       int
    swept:       bool = False
    sweep_index: int  = -1
    count:       int  = 1


@dataclass
class Inducement:
    price:       float
    direction:   str
    index:       int
    taken:       bool = False
    taken_index: int  = -1


@dataclass
class LiquiditySweep:
    level:       float
    sweep_price: float
    direction:   str
    index:       int
    reclaimed:   bool = False


class LiquidityEngine:
    """Detects liquidity pools, sweeps, and inducements."""

    def __init__(self, eq_tolerance: float = 0.0004, lookback: int = 60):
        self.eq_tolerance = eq_tolerance
        self.lookback     = lookback

    def analyze(
        self,
        candles:     list,
        swing_highs: list,
        swing_lows:  list,
    ) -> dict:
        """Full liquidity analysis."""
        if not candles or len(candles) < 10:
            return {
                "buy_side":   [],
                "sell_side":  [],
                "inducements": [],
                "sweeps":     [],
            }

        buy_side  = self._find_buy_side(candles, swing_highs)
        sell_side = self._find_sell_side(candles, swing_lows)
        inds      = self._find_inducements(candles)
        sweeps    = self._find_sweeps(candles, buy_side + sell_side)

        return {
            "buy_side":    buy_side,
            "sell_side":   sell_side,
            "inducements": inds,
            "sweeps":      sweeps,
        }

    # ── Buy-Side Liquidity ───────────────────────────────────────────────
    def _find_buy_side(
        self, candles: list, swing_highs: list
    ) -> List[LiquidityLevel]:
        levels = []

        # Equal highs
        for eh in self._find_equal_levels(candles, is_high=True):
            levels.append(LiquidityLevel(
                price=eh["price"],
                level_type="EQH",
                side="buy_side",
                index=eh["index"],
                count=eh["count"],
            ))

        # Swing highs as BSL
        for sh in swing_highs:
            price = sh.price if hasattr(sh, "price") else sh.get("price", 0)
            idx   = sh.index if hasattr(sh, "index") else sh.get("index", 0)
            levels.append(LiquidityLevel(
                price=float(price),
                level_type="BSL",
                side="buy_side",
                index=int(idx),
            ))

        # Check swept
        for lv in levels:
            for i in range(lv.index + 1, len(candles)):
                if self._high(candles[i]) > lv.price:
                    lv.swept       = True
                    lv.sweep_index = i
                    break

        return levels

    # ── Sell-Side Liquidity ──────────────────────────────────────────────
    def _find_sell_side(
        self, candles: list, swing_lows: list
    ) -> List[LiquidityLevel]:
        levels = []

        for el in self._find_equal_levels(candles, is_high=False):
            levels.append(LiquidityLevel(
                price=el["price"],
                level_type="EQL",
                side="sell_side",
                index=el["index"],
                count=el["count"],
            ))

        for sl in swing_lows:
            price = sl.price if hasattr(sl, "price") else sl.get("price", 0)
            idx   = sl.index if hasattr(sl, "index") else sl.get("index", 0)
            levels.append(LiquidityLevel(
                price=float(price),
                level_type="SSL",
                side="sell_side",
                index=int(idx),
            ))

        for lv in levels:
            for i in range(lv.index + 1, len(candles)):
                if self._low(candles[i]) < lv.price:
                    lv.swept       = True
                    lv.sweep_index = i
                    break

        return levels

    # ── Equal Levels ─────────────────────────────────────────────────────
    def _find_equal_levels(self, candles: list, is_high: bool) -> list:
        prices = [
            (self._high(c) if is_high else self._low(c), i)
            for i, c in enumerate(candles)
        ]
        used    = set()
        equals  = []
        for i in range(len(prices)):
            if i in used:
                continue
            p0, i0 = prices[i]
            cluster = [(p0, i0)]
            for j in range(i + 1, min(i + self.lookback, len(prices))):
                if j in used:
                    continue
                pj, ij = prices[j]
                ref    = max(p0, 0.0001)
                if abs(p0 - pj) / ref <= self.eq_tolerance:
                    cluster.append((pj, ij))
                    used.add(j)
            if len(cluster) >= 2:
                avg = sum(c[0] for c in cluster) / len(cluster)
                equals.append({
                    "price": avg,
                    "index": cluster[-1][1],
                    "count": len(cluster),
                })
                used.add(i)
        return equals

    # ── Inducements ──────────────────────────────────────────────────────
    def _find_inducements(self, candles: list) -> List[Inducement]:
        inds = []
        for i in range(3, len(candles) - 2):
            # Minor bullish spike that immediately reversed
            if (self._high(candles[i]) > self._high(candles[i - 1]) and
                    self._high(candles[i]) > self._high(candles[i - 2])):
                if (i + 2 < len(candles) and
                        self._close(candles[i + 1]) < self._low(candles[i]) and
                        self._close(candles[i + 2]) < self._low(candles[i])):
                    inds.append(Inducement(
                        price=self._high(candles[i]),
                        direction="bearish",
                        index=i,
                        taken=True,
                        taken_index=i,
                    ))

            # Minor bearish spike that immediately reversed
            if (self._low(candles[i]) < self._low(candles[i - 1]) and
                    self._low(candles[i]) < self._low(candles[i - 2])):
                if (i + 2 < len(candles) and
                        self._close(candles[i + 1]) > self._high(candles[i]) and
                        self._close(candles[i + 2]) > self._high(candles[i])):
                    inds.append(Inducement(
                        price=self._low(candles[i]),
                        direction="bullish",
                        index=i,
                        taken=True,
                        taken_index=i,
                    ))

        return inds[-15:]

    # ── Sweeps ───────────────────────────────────────────────────────────
    def _find_sweeps(
        self,
        candles: list,
        all_levels: List[LiquidityLevel],
    ) -> List[LiquiditySweep]:
        sweeps = []
        for lv in all_levels:
            if not lv.swept or lv.sweep_index < 0:
                continue
            si     = lv.sweep_index
            if si >= len(candles):
                continue
            candle = candles[si]
            if lv.side == "buy_side":
                if (self._high(candle) > lv.price and
                        self._close(candle) < lv.price):
                    sweeps.append(LiquiditySweep(
                        level=lv.price,
                        sweep_price=self._high(candle),
                        direction="bearish",
                        index=si,
                        reclaimed=True,
                    ))
            else:
                if (self._low(candle) < lv.price and
                        self._close(candle) > lv.price):
                    sweeps.append(LiquiditySweep(
                        level=lv.price,
                        sweep_price=self._low(candle),
                        direction="bullish",
                        index=si,
                        reclaimed=True,
                    ))
        return sweeps

    # ── Helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _high(c) -> float:
        return float(c.get("high", c[1]) if isinstance(c, dict) else c[1])

    @staticmethod
    def _low(c) -> float:
        return float(c.get("low",  c[2]) if isinstance(c, dict) else c[2])

    @staticmethod
    def _close(c) -> float:
        return float(c.get("close", c[3]) if isinstance(c, dict) else c[3])