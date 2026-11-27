"""
Supply & Demand Zone Detection Engine
Identifies institutional order blocks, supply/demand zones, and FVGs.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class Zone:
    high:           float
    low:            float
    origin_index:   int
    zone_type:      str           # "supply" | "demand"
    sub_type:       str = "zone"
    strength:       int = 5
    is_fresh:       bool = True
    touch_count:    int  = 0
    is_order_block: bool = False
    imbalance:      bool = False

    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2

    @property
    def size(self) -> float:
        return self.high - self.low


@dataclass
class FairValueGap:
    high:         float
    low:          float
    index:        int
    gap_type:     str    # "bullish" | "bearish"
    filled:       bool  = False
    fill_percent: float = 0.0

    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2

    @property
    def size(self) -> float:
        return self.high - self.low


class SupplyDemandEngine:
    """Detects supply/demand zones, order blocks, and FVGs."""

    def __init__(self, max_zones: int = 15):
        self.max_zones = max_zones

    def find_zones(self, candles: list) -> dict:
        """Find all supply/demand zones and FVGs."""
        if not candles or len(candles) < 10:
            return {"supply": [], "demand": [], "fvg": []}

        supply = self._find_supply(candles)
        demand = self._find_demand(candles)
        fvg    = self._find_fvg(candles)

        current_price = self._close(candles[-1])
        self._update_freshness(supply, demand, candles)
        self._score_zones(supply)
        self._score_zones(demand)

        supply.sort(key=lambda z: z.strength, reverse=True)
        demand.sort(key=lambda z: z.strength, reverse=True)

        return {
            "supply": supply[:self.max_zones],
            "demand": demand[:self.max_zones],
            "fvg":    fvg,
        }

    # ── Supply Zone Detection ────────────────────────────────────────────
    def _find_supply(self, candles: list) -> List[Zone]:
        zones = []
        for i in range(2, len(candles) - 1):
            c_prev = candles[i - 1]
            c_curr = candles[i]

            if not self._is_bearish(c_curr):
                continue

            move   = self._body(c_curr)
            avg_b  = self._avg_body(candles, i, 10)
            if avg_b <= 0 or move < avg_b * 1.2:
                continue

            # The last bullish candle before the drop = Order Block
            ob    = c_prev if self._is_bullish(c_prev) else c_curr
            is_ob = self._is_bullish(c_prev)

            zone = Zone(
                high=self._high(ob),
                low=min(self._open(ob), self._close(ob)),
                origin_index=i - (1 if is_ob else 0),
                zone_type="supply",
                is_order_block=is_ob,
            )

            # Check for imbalance (gap) after the move
            if i + 1 < len(candles):
                if self._low(candles[i + 1]) > self._high(c_prev):
                    zone.imbalance = True

            if zone.size > 0:
                zones.append(zone)

        return zones

    # ── Demand Zone Detection ────────────────────────────────────────────
    def _find_demand(self, candles: list) -> List[Zone]:
        zones = []
        for i in range(2, len(candles) - 1):
            c_prev = candles[i - 1]
            c_curr = candles[i]

            if not self._is_bullish(c_curr):
                continue

            move  = self._body(c_curr)
            avg_b = self._avg_body(candles, i, 10)
            if avg_b <= 0 or move < avg_b * 1.2:
                continue

            # The last bearish candle before the rally = Order Block
            ob    = c_prev if self._is_bearish(c_prev) else c_curr
            is_ob = self._is_bearish(c_prev)

            zone = Zone(
                high=max(self._open(ob), self._close(ob)),
                low=self._low(ob),
                origin_index=i - (1 if is_ob else 0),
                zone_type="demand",
                is_order_block=is_ob,
            )

            if i + 1 < len(candles):
                if self._high(candles[i + 1]) < self._low(c_prev):
                    zone.imbalance = True

            if zone.size > 0:
                zones.append(zone)

        return zones

    # ── FVG Detection ────────────────────────────────────────────────────
    def _find_fvg(self, candles: list) -> List[FairValueGap]:
        fvgs = []
        for i in range(2, len(candles)):
            c1 = candles[i - 2]
            c3 = candles[i]

            # Bullish FVG: gap between candle1 high and candle3 low
            if self._low(c3) > self._high(c1):
                fvg = FairValueGap(
                    high=self._low(c3),
                    low=self._high(c1),
                    index=i - 1,
                    gap_type="bullish",
                )
                # Check if filled
                for j in range(i + 1, min(i + 30, len(candles))):
                    if self._low(candles[j]) <= fvg.low:
                        fvg.filled = True
                        fvg.fill_percent = 100.0
                        break
                    elif self._low(candles[j]) < fvg.high:
                        pct = (fvg.high - self._low(candles[j])) / max(fvg.size, 0.00001) * 100
                        fvg.fill_percent = max(fvg.fill_percent, pct)
                if fvg.size > 0:
                    fvgs.append(fvg)

            # Bearish FVG: gap between candle3 high and candle1 low
            if self._high(c3) < self._low(c1):
                fvg = FairValueGap(
                    high=self._low(c1),
                    low=self._high(c3),
                    index=i - 1,
                    gap_type="bearish",
                )
                for j in range(i + 1, min(i + 30, len(candles))):
                    if self._high(candles[j]) >= fvg.high:
                        fvg.filled = True
                        fvg.fill_percent = 100.0
                        break
                    elif self._high(candles[j]) > fvg.low:
                        pct = (self._high(candles[j]) - fvg.low) / max(fvg.size, 0.00001) * 100
                        fvg.fill_percent = max(fvg.fill_percent, pct)
                if fvg.size > 0:
                    fvgs.append(fvg)

        return fvgs

    # ── Freshness & Scoring ──────────────────────────────────────────────
    def _update_freshness(
        self,
        supply: List[Zone],
        demand: List[Zone],
        candles: list,
    ):
        for zone in supply:
            for i in range(zone.origin_index + 1, len(candles)):
                if self._high(candles[i]) >= zone.low:
                    zone.touch_count += 1
                    if self._high(candles[i]) >= zone.midpoint:
                        zone.is_fresh = False
                        break

        for zone in demand:
            for i in range(zone.origin_index + 1, len(candles)):
                if self._low(candles[i]) <= zone.high:
                    zone.touch_count += 1
                    if self._low(candles[i]) <= zone.midpoint:
                        zone.is_fresh = False
                        break

    def _score_zones(self, zones: List[Zone]):
        for zone in zones:
            score = 5
            if zone.is_fresh:
                score += 2
            if zone.is_order_block:
                score += 1
            if zone.imbalance:
                score += 1
            if zone.touch_count == 0:
                score += 1
            elif zone.touch_count >= 3:
                score -= 2
            zone.strength = max(1, min(10, score))

    # ── Helpers ──────────────────────────────────────────────────────────
    def _avg_body(self, candles: list, index: int, lookback: int) -> float:
        start  = max(0, index - lookback)
        bodies = [self._body(c) for c in candles[start:index]]
        return sum(bodies) / len(bodies) if bodies else 0.0

    @staticmethod
    def _open(c) -> float:
        return float(c.get("open",  c[0]) if isinstance(c, dict) else c[0])

    @staticmethod
    def _high(c) -> float:
        return float(c.get("high",  c[1]) if isinstance(c, dict) else c[1])

    @staticmethod
    def _low(c) -> float:
        return float(c.get("low",   c[2]) if isinstance(c, dict) else c[2])

    @staticmethod
    def _close(c) -> float:
        return float(c.get("close", c[3]) if isinstance(c, dict) else c[3])

    def _is_bullish(self, c) -> bool:
        return self._close(c) > self._open(c)

    def _is_bearish(self, c) -> bool:
        return self._close(c) < self._open(c)

    def _body(self, c) -> float:
        return abs(self._close(c) - self._open(c))