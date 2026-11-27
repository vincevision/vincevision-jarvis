"""
Multi-Timeframe Confluence Engine
Combines HTF bias with LTF confirmation for high-probability entries.
"""

from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class ConfluenceSignal:
    score:            int   = 0
    direction:        str   = "no_trade"
    htf_bias:         str   = "neutral"
    ltf_confirmation: bool  = False
    entry_price:      float = 0.0
    stop_loss:        float = 0.0
    tp1:              float = 0.0
    tp2:              float = 0.0
    tp3:              float = 0.0
    risk_reward:      float = 0.0
    entry_type:       str   = ""
    reasoning:        str   = ""
    invalidation:     float = 0.0
    narrative:        str   = ""


TF_PAIRS = {
    "1M": ["1w", "1d"],
    "1w": ["1d", "4h"],
    "1d": ["4h", "1h"],
    "4h": ["1h", "15m"],
    "2h": ["30m", "15m"],
    "1h": ["15m", "5m"],
    "30m": ["5m", "3m"],
    "15m": ["5m", "1m"],
    "5m":  ["1m"],
}


class ConfluenceEngine:

    def __init__(self, min_score: int = 55):
        self.min_score = min_score

    def find_confluence(
        self,
        htf_analysis:  dict,
        ltf_analysis:  dict,
        htf_tf:        str,
        ltf_tf:        str,
        current_price: float,
    ) -> ConfluenceSignal:
        signal = ConfluenceSignal()

        htf_bias = self._determine_bias(htf_analysis)
        signal.htf_bias = htf_bias

        if htf_bias == "neutral":
            signal.reasoning = "HTF bias unclear — monitoring"
            signal.score     = 15
            return signal

        htf_poi = self._find_poi(htf_analysis, htf_bias, current_price)
        at_poi  = self._is_at_poi(current_price, htf_poi)

        ltf_confirm = self._check_ltf_confirmation(
            ltf_analysis, htf_bias, current_price
        )

        score          = self._score(
            htf_bias, htf_poi, at_poi,
            ltf_confirm, htf_analysis, ltf_analysis, current_price,
        )
        signal.score   = score

        if score >= self.min_score:
            signal.direction        = "long" if htf_bias == "bullish" else "short"
            signal.ltf_confirmation = ltf_confirm.get("confirmed", False)
            entry = self._calc_entry(
                htf_bias, htf_poi, ltf_confirm,
                htf_analysis, ltf_analysis, current_price,
            )
            signal.entry_price  = entry.get("entry",        0)
            signal.stop_loss    = entry.get("sl",           0)
            signal.tp1          = entry.get("tp1",          0)
            signal.tp2          = entry.get("tp2",          0)
            signal.tp3          = entry.get("tp3",          0)
            signal.risk_reward  = entry.get("rr",           0)
            signal.entry_type   = entry.get("type",         "")
            signal.invalidation = entry.get("invalidation", 0)

        signal.reasoning = self._build_reasoning(
            htf_bias, htf_poi, at_poi, ltf_confirm,
            score, htf_tf, ltf_tf,
        )
        signal.narrative = self._build_narrative(
            htf_bias, htf_poi, ltf_confirm, htf_tf, ltf_tf,
            current_price, signal,
        )
        return signal

    # ── Bias ─────────────────────────────────────────────────────────────
    def _determine_bias(self, a: dict) -> str:
        mss = a.get("structure", {}).get("mss_events", [])
        if mss:
            last = mss[-1]
            if isinstance(last, dict):
                return last.get("type", "neutral")

        choch = a.get("structure", {}).get("choch_events", [])
        if choch:
            last = choch[-1]
            if isinstance(last, dict):
                return last.get("type", "neutral")

        bias  = a.get("bias", "neutral")
        conf  = a.get("confidence", 0)
        trend = a.get("trend", "ranging")

        if trend in ("bullish", "bearish") and conf >= 55:
            return trend
        return bias if bias != "neutral" else "neutral"

    # ── Point of Interest ────────────────────────────────────────────────
    def _find_poi(
        self, analysis: dict, bias: str, current_price: float
    ) -> dict:
        poi = {}
        if bias == "bullish":
            zones    = analysis.get("demand_zones", [])
            best     = None
            best_dst = float("inf")
            for z in zones:
                if not isinstance(z, dict):
                    continue
                if z.get("type") == "mitigated":
                    continue
                zh = z.get("high", 0)
                if zh and zh <= current_price:
                    d = current_price - zh
                    if d < best_dst:
                        best_dst = d
                        best     = z
            if best:
                poi = {
                    "type":   "demand",
                    "high":   best.get("high", 0),
                    "low":    best.get("low",  0),
                    "strength": best.get("strength", 5),
                    "is_ob":  best.get("is_order_block", False),
                }
        elif bias == "bearish":
            zones    = analysis.get("supply_zones", [])
            best     = None
            best_dst = float("inf")
            for z in zones:
                if not isinstance(z, dict):
                    continue
                if z.get("type") == "mitigated":
                    continue
                zl = z.get("low", 0)
                if zl and zl >= current_price:
                    d = zl - current_price
                    if d < best_dst:
                        best_dst = d
                        best     = z
            if best:
                poi = {
                    "type":   "supply",
                    "high":   best.get("high", 0),
                    "low":    best.get("low",  0),
                    "strength": best.get("strength", 5),
                    "is_ob":  best.get("is_order_block", False),
                }
        return poi

    def _is_at_poi(self, price: float, poi: dict) -> bool:
        if not poi or not poi.get("high"):
            return False
        size      = poi["high"] - poi["low"]
        tolerance = size * 2.0
        if poi["type"] == "demand":
            return price <= poi["high"] + tolerance
        return price >= poi["low"] - tolerance

    # ── LTF Confirmation ─────────────────────────────────────────────────
    def _check_ltf_confirmation(
        self, ltf: dict, bias: str, price: float
    ) -> dict:
        result = {"confirmed": False, "type": "", "strength": 0, "details": ""}
        st = ltf.get("structure", {})

        for ev in reversed(st.get("mss_events", [])):
            if isinstance(ev, dict) and ev.get("type") == bias:
                return {"confirmed": True, "type": "mss", "strength": 9,
                        "details": f"LTF MSS {bias} confirmed"}

        for ev in reversed(st.get("choch_events", [])):
            if isinstance(ev, dict) and ev.get("type") == bias:
                return {"confirmed": True, "type": "choch", "strength": 7,
                        "details": f"LTF CHoCH {bias}"}

        bos_list = [
            b for b in st.get("bos_events", [])
            if isinstance(b, dict) and b.get("type") == bias
        ]
        if len(bos_list) >= 2:
            return {"confirmed": True, "type": "bos", "strength": 5,
                    "details": f"Multiple BOS {bias}"}

        return result

    # ── Score ────────────────────────────────────────────────────────────
    def _score(
        self, bias, poi, at_poi, ltf_confirm,
        htf, ltf, price,
    ) -> int:
        score = 0
        conf  = htf.get("confidence", 50)
        score += min(20, int(conf * 0.2))

        if poi:
            score += 10
            if poi.get("is_ob"):     score += 5
            if poi.get("strength", 0) >= 7: score += 5

        if at_poi: score += 15

        if ltf_confirm.get("confirmed"):
            score += 15
            score += min(10, ltf_confirm.get("strength", 0))

        liq = ltf.get("liquidity", {})
        swept_count = sum(
            1 for side in ("buy_side", "sell_side")
            for lv in liq.get(side, [])
            if isinstance(lv, dict) and lv.get("swept")
        )
        if swept_count:
            score += min(10, swept_count * 3)

        unfilled_fvg = [
            f for f in ltf.get("fvg", [])
            if isinstance(f, dict) and not f.get("filled")
        ]
        if unfilled_fvg: score += 5

        pd = htf.get("premium_discount", {})
        pos = pd.get("current_position", "")
        if bias == "bullish" and pos == "discount":  score += 5
        if bias == "bearish" and pos == "premium":   score += 5

        return min(100, score)

    # ── Entry Calculation ────────────────────────────────────────────────
    def _calc_entry(
        self, bias, poi, ltf_confirm, htf, ltf, price
    ) -> dict:
        e = {"entry": 0, "sl": 0, "tp1": 0, "tp2": 0, "tp3": 0,
             "rr": 0, "type": "", "invalidation": 0}

        if bias == "bullish" and poi.get("type") == "demand":
            e["entry"] = poi["high"]
            zone_sz    = poi["high"] - poi["low"]
            e["sl"]    = poi["low"] - zone_sz * 0.15
            e["type"]  = "demand_retest"

            # Check for FVG entry inside zone
            for fvg in ltf.get("fvg", []):
                if (isinstance(fvg, dict) and
                        fvg.get("type") == "bullish" and
                        not fvg.get("filled")):
                    mid = (fvg["high"] + fvg["low"]) / 2
                    if poi["low"] <= mid <= poi["high"] * 1.001:
                        e["entry"] = mid
                        e["type"]  = "fvg_in_demand"
                        break

            # TPs from supply zones + liquidity
            tps = sorted(
                [
                    z.get("low", 0) for z in htf.get("supply_zones", [])
                    if isinstance(z, dict) and z.get("low", 0) > price
                ] + [
                    lv.get("level", 0) for lv in htf.get("liquidity", {}).get("buy_side", [])
                    if isinstance(lv, dict) and not lv.get("swept") and lv.get("level", 0) > price
                ]
            )
            if tps: e["tp1"] = tps[0]
            if len(tps) > 1: e["tp2"] = tps[1]
            if len(tps) > 2: e["tp3"] = tps[2]

        elif bias == "bearish" and poi.get("type") == "supply":
            e["entry"] = poi["low"]
            zone_sz    = poi["high"] - poi["low"]
            e["sl"]    = poi["high"] + zone_sz * 0.15
            e["type"]  = "supply_retest"

            for fvg in ltf.get("fvg", []):
                if (isinstance(fvg, dict) and
                        fvg.get("type") == "bearish" and
                        not fvg.get("filled")):
                    mid = (fvg["high"] + fvg["low"]) / 2
                    if poi["low"] * 0.999 <= mid <= poi["high"]:
                        e["entry"] = mid
                        e["type"]  = "fvg_in_supply"
                        break

            tps = sorted(
                [
                    z.get("high", 0) for z in htf.get("demand_zones", [])
                    if isinstance(z, dict) and z.get("high", 0) < price
                ] + [
                    lv.get("level", 0) for lv in htf.get("liquidity", {}).get("sell_side", [])
                    if isinstance(lv, dict) and not lv.get("swept") and lv.get("level", 0) < price
                ],
                reverse=True,
            )
            if tps: e["tp1"] = tps[0]
            if len(tps) > 1: e["tp2"] = tps[1]
            if len(tps) > 2: e["tp3"] = tps[2]

        e["invalidation"] = e["sl"]

        if e["entry"] and e["sl"] and e["tp1"]:
            risk   = abs(e["entry"] - e["sl"])
            reward = abs(e["tp1"]   - e["entry"])
            e["rr"] = round(reward / risk, 2) if risk > 0 else 0

        return e

    # ── Narrative ────────────────────────────────────────────────────────
    def _build_reasoning(
        self, bias, poi, at_poi, ltf_confirm,
        score, htf_tf, ltf_tf,
    ) -> str:
        parts = [f"HTF ({htf_tf}): {bias}"]
        if poi:
            parts.append(
                f"POI: {poi.get('type')} "
                f"[{poi.get('low', 0):.5f}-{poi.get('high', 0):.5f}]"
                f"{' OB' if poi.get('is_ob') else ''}"
            )
        parts.append(f"At POI: {'YES' if at_poi else 'NO'}")
        if ltf_confirm.get("confirmed"):
            parts.append(f"LTF ({ltf_tf}): {ltf_confirm['type'].upper()} confirmed")
        else:
            parts.append(f"LTF ({ltf_tf}): waiting for confirmation")
        parts.append(f"Score: {score}/100")
        return " | ".join(parts)

    def _build_narrative(
        self, bias, poi, ltf_confirm, htf_tf, ltf_tf,
        price, signal,
    ) -> str:
        side   = "buys" if bias == "bullish" else "sells"
        pt     = poi.get("type", "zone") if poi else "zone"
        narr   = (
            f"Smart money accumulating {side} at the {htf_tf} {pt} zone. "
        )
        if ltf_confirm.get("confirmed"):
            narr += (
                f"{ltf_tf} {ltf_confirm['type'].upper()} confirms directional bias. "
            )
        else:
            narr += f"Waiting for {ltf_tf} MSS/CHoCH confirmation. "
        if signal.entry_price:
            narr += (
                f"Entry: {signal.entry_price:.5f} | "
                f"SL: {signal.stop_loss:.5f} | "
                f"TP1: {signal.tp1:.5f} | "
                f"R:R {signal.risk_reward}:1"
            )
        return narr

    @staticmethod
    def get_ltf_for_htf(htf: str) -> list:
        return TF_PAIRS.get(htf, ["15m", "5m"])