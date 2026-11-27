"""
Market Structure Engine
Detects BOS, CHoCH, MSS, swing points algorithmically.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class StructureType(Enum):
    BOS   = "bos"
    CHOCH = "choch"
    MSS   = "mss"


class SwingType(Enum):
    HH = "higher_high"
    HL = "higher_low"
    LH = "lower_high"
    LL = "lower_low"


class TrendState(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    RANGING = "ranging"


@dataclass
class SwingPoint:
    price:      float
    index:      int
    is_high:    bool
    swing_type: Optional[SwingType] = None
    significant: bool = False
    broken:     bool  = False


@dataclass
class StructureBreak:
    type:        StructureType
    direction:   str    # bullish / bearish
    level:       float
    index:       int
    confirmed:   bool = True
    displacement: bool = False
    candle_index: int  = 0


@dataclass
class MarketStructure:
    trend:        TrendState             = TrendState.RANGING
    swing_highs:  List[SwingPoint]       = field(default_factory=list)
    swing_lows:   List[SwingPoint]       = field(default_factory=list)
    bos_events:   List[StructureBreak]   = field(default_factory=list)
    choch_events: List[StructureBreak]   = field(default_factory=list)
    mss_events:   List[StructureBreak]   = field(default_factory=list)
    current_price: float                 = 0.0


class MarketStructureEngine:
    """Algorithmic market structure detection."""

    def __init__(
        self,
        swing_lookback: int   = 5,
        min_swing_size: float = 0.0001,
    ):
        self.swing_lookback = swing_lookback
        self.min_swing_size = min_swing_size

    def analyze(self, candles: list) -> MarketStructure:
        """Full market structure analysis."""
        structure = MarketStructure()
        if not candles or len(candles) < self.swing_lookback * 2 + 2:
            return structure

        structure.current_price = self._close(candles[-1])

        highs = self._find_swing_highs(candles)
        lows  = self._find_swing_lows(candles)

        self._classify_swings(highs, lows)

        bos, choch, mss = self._detect_breaks(highs, lows, candles)

        structure.trend        = self._determine_trend(highs, lows, bos, choch)
        structure.swing_highs  = highs
        structure.swing_lows   = lows
        structure.bos_events   = bos
        structure.choch_events = choch
        structure.mss_events   = mss

        self._mark_significant(highs + lows, candles)
        return structure

    # ── Swing Detection ──────────────────────────────────────────────────
    def _find_swing_highs(self, candles: list) -> List[SwingPoint]:
        swings = []
        lb = self.swing_lookback
        for i in range(lb, len(candles) - lb):
            h = self._high(candles[i])
            if all(
                self._high(candles[i - j]) < h and
                self._high(candles[i + j]) < h
                for j in range(1, lb + 1)
            ):
                swings.append(SwingPoint(price=h, index=i, is_high=True))
        return swings

    def _find_swing_lows(self, candles: list) -> List[SwingPoint]:
        swings = []
        lb = self.swing_lookback
        for i in range(lb, len(candles) - lb):
            l = self._low(candles[i])
            if all(
                self._low(candles[i - j]) > l and
                self._low(candles[i + j]) > l
                for j in range(1, lb + 1)
            ):
                swings.append(SwingPoint(price=l, index=i, is_high=False))
        return swings

    # ── Swing Classification ─────────────────────────────────────────────
    def _classify_swings(
        self,
        highs: List[SwingPoint],
        lows:  List[SwingPoint],
    ):
        for i in range(len(highs)):
            if i == 0:
                highs[i].swing_type = SwingType.HH
            elif highs[i].price > highs[i - 1].price:
                highs[i].swing_type = SwingType.HH
            else:
                highs[i].swing_type = SwingType.LH

        for i in range(len(lows)):
            if i == 0:
                lows[i].swing_type = SwingType.HL
            elif lows[i].price > lows[i - 1].price:
                lows[i].swing_type = SwingType.HL
            else:
                lows[i].swing_type = SwingType.LL

    # ── Structure Break Detection ────────────────────────────────────────
    def _detect_breaks(
        self,
        highs:   List[SwingPoint],
        lows:    List[SwingPoint],
        candles: list,
    ):
        bos_events   = []
        choch_events = []
        mss_events   = []

        current_trend    = "neutral"
        last_valid_high: Optional[SwingPoint] = None
        last_valid_low:  Optional[SwingPoint] = None

        all_swings = sorted(highs + lows, key=lambda s: s.index)
        swing_idx  = 0

        for i, candle in enumerate(candles):
            # Update swing pointers
            while (swing_idx < len(all_swings) and
                   all_swings[swing_idx].index <= i):
                sp = all_swings[swing_idx]
                if sp.is_high:
                    last_valid_high = sp
                else:
                    last_valid_low = sp
                swing_idx += 1

            close = self._close(candle)

            # Check bullish break
            if last_valid_high and not last_valid_high.broken:
                if close > last_valid_high.price:
                    disp = self._is_displacement(candles, i)
                    if current_trend == "bearish":
                        ev = StructureBreak(
                            type=StructureType.CHOCH,
                            direction="bullish",
                            level=last_valid_high.price,
                            index=i,
                            displacement=disp,
                            candle_index=i,
                        )
                        choch_events.append(ev)
                        if disp:
                            mss_events.append(StructureBreak(
                                type=StructureType.MSS,
                                direction="bullish",
                                level=last_valid_high.price,
                                index=i,
                                displacement=True,
                                candle_index=i,
                            ))
                    else:
                        bos_events.append(StructureBreak(
                            type=StructureType.BOS,
                            direction="bullish",
                            level=last_valid_high.price,
                            index=i,
                            displacement=disp,
                            candle_index=i,
                        ))
                    last_valid_high.broken = True
                    current_trend = "bullish"

            # Check bearish break
            if last_valid_low and not last_valid_low.broken:
                if close < last_valid_low.price:
                    disp = self._is_displacement(candles, i)
                    if current_trend == "bullish":
                        ev = StructureBreak(
                            type=StructureType.CHOCH,
                            direction="bearish",
                            level=last_valid_low.price,
                            index=i,
                            displacement=disp,
                            candle_index=i,
                        )
                        choch_events.append(ev)
                        if disp:
                            mss_events.append(StructureBreak(
                                type=StructureType.MSS,
                                direction="bearish",
                                level=last_valid_low.price,
                                index=i,
                                displacement=True,
                                candle_index=i,
                            ))
                    else:
                        bos_events.append(StructureBreak(
                            type=StructureType.BOS,
                            direction="bearish",
                            level=last_valid_low.price,
                            index=i,
                            displacement=disp,
                            candle_index=i,
                        ))
                    last_valid_low.broken = True
                    current_trend = "bearish"

        return bos_events, choch_events, mss_events

    def _is_displacement(self, candles: list, index: int) -> bool:
        """Check for displacement candle (large body, strong momentum)."""
        if index < 1 or index >= len(candles):
            return False
        c          = candles[index]
        body       = abs(self._close(c) - self._open(c))
        total      = self._high(c) - self._low(c)
        if total == 0:
            return False
        body_ratio = body / total
        if body_ratio < 0.65:
            return False
        start      = max(0, index - 10)
        recent     = candles[start:index]
        if not recent:
            return body_ratio > 0.7
        avg = sum(
            self._high(rc) - self._low(rc) for rc in recent
        ) / len(recent)
        return total > avg * 1.4

    # ── Trend Determination ──────────────────────────────────────────────
    def _determine_trend(
        self,
        highs:  List[SwingPoint],
        lows:   List[SwingPoint],
        bos:    List[StructureBreak],
        choch:  List[StructureBreak],
    ) -> TrendState:
        if not highs or not lows:
            return TrendState.RANGING

        recent_h = highs[-4:]
        recent_l = lows[-4:]

        hh = sum(1 for h in recent_h if h.swing_type == SwingType.HH)
        lh = sum(1 for h in recent_h if h.swing_type == SwingType.LH)
        hl = sum(1 for l in recent_l if l.swing_type == SwingType.HL)
        ll = sum(1 for l in recent_l if l.swing_type == SwingType.LL)

        bull = hh + hl
        bear = lh + ll

        if choch:
            last = choch[-1]
            if last.direction == "bullish":
                bull += 2
            else:
                bear += 2

        if bull > bear + 1:
            return TrendState.BULLISH
        if bear > bull + 1:
            return TrendState.BEARISH
        return TrendState.RANGING

    def _mark_significant(self, swings: List[SwingPoint], candles: list):
        """Mark swings with strong rejection wicks as significant."""
        for sp in swings:
            if sp.index >= len(candles):
                continue
            c     = candles[sp.index]
            total = self._high(c) - self._low(c)
            if total == 0:
                continue
            if sp.is_high:
                wick = self._high(c) - max(self._open(c), self._close(c))
            else:
                wick = min(self._open(c), self._close(c)) - self._low(c)
            if wick / total > 0.38:
                sp.significant = True

    # ── Candle Accessors ─────────────────────────────────────────────────
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