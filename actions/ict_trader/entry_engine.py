"""
Entry Engine — Position sizing, risk management, trade setup validation.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class TradeSetup:
    symbol:          str   = ""
    direction:       str   = ""
    entry_price:     float = 0.0
    stop_loss:       float = 0.0
    tp1:             float = 0.0
    tp2:             float = 0.0
    tp3:             float = 0.0
    risk_reward:     float = 0.0
    position_size:   float = 0.0
    risk_amount:     float = 0.0
    risk_percent:    float = 1.0
    confidence:      int   = 0
    entry_type:      str   = ""
    htf:             str   = ""
    ltf:             str   = ""
    narrative:       str   = ""
    invalidation:    float = 0.0
    status:          str   = "pending"

class EntryEngine:

    def __init__(
        self,
        default_risk_percent: float = 1.0,
        max_risk_percent:     float = 2.0,
        min_rr:               float = 1.8,
        account_balance:      float = 10000.0,
    ):
        self.default_risk = default_risk_percent
        self.max_risk     = max_risk_percent
        self.min_rr       = min_rr
        self.balance      = account_balance

    def create_setup(
        self,
        symbol:     str,
        direction:  str,
        entry:      float,
        sl:         float,
        tp1:        float,
        tp2:        float = 0,
        tp3:        float = 0,
        confidence: int   = 50,
        entry_type: str   = "",
        htf:        str   = "",
        ltf:        str   = "",
        narrative:  str   = "",
    ) -> Optional[TradeSetup]:
        if not entry or not sl or not tp1:
            return None

        risk_pips   = abs(entry - sl)
        reward_pips = abs(tp1 - entry)

        if risk_pips <= 0:
            return None

        rr = reward_pips / risk_pips
        if rr < self.min_rr:
            return None

        # Adaptive risk based on confidence
        risk_pct = self.default_risk
        if confidence >= 80:
            risk_pct = min(self.max_risk, risk_pct * 1.5)
        elif confidence < 50:
            risk_pct = risk_pct * 0.5

        risk_amount = self.balance * (risk_pct / 100)

        pip_val  = self._pip_value(symbol)
        pip_size = self._pip_size(symbol)
        if pip_val > 0 and pip_size > 0 and risk_pips > 0:
            pips_at_risk = risk_pips / pip_size
            lots = risk_amount / (pips_at_risk * pip_val)
            lots = max(0.01, round(lots, 2))
        else:
            lots = 0.01

        # Auto-calculate TP2 / TP3 if not given
        if not tp2:
            tp2 = entry + (tp1 - entry) * 1.618 if direction == "long" \
                else entry - (entry - tp1) * 1.618
        if not tp3:
            tp3 = entry + (tp1 - entry) * 2.618 if direction == "long" \
                else entry - (entry - tp1) * 2.618

        return TradeSetup(
            symbol=symbol,
            direction=direction,
            entry_price=round(entry, 5),
            stop_loss=round(sl, 5),
            tp1=round(tp1, 5),
            tp2=round(tp2, 5),
            tp3=round(tp3, 5),
            risk_reward=round(rr, 2),
            position_size=lots,
            risk_amount=round(risk_amount, 2),
            risk_percent=risk_pct,
            confidence=confidence,
            entry_type=entry_type,
            htf=htf,
            ltf=ltf,
            narrative=narrative[:300],
            invalidation=round(sl, 5),
        )

    def validate_setup(self, setup: TradeSetup) -> dict:
        issues = []
        if setup.risk_reward < self.min_rr:
            issues.append(f"R:R {setup.risk_reward} < min {self.min_rr}")
        if setup.confidence < 40:
            issues.append(f"Low confidence: {setup.confidence}%")
        if setup.direction == "long":
            if setup.stop_loss >= setup.entry_price:
                issues.append("SL above entry (long)")
            if setup.tp1 <= setup.entry_price:
                issues.append("TP1 below entry (long)")
        elif setup.direction == "short":
            if setup.stop_loss <= setup.entry_price:
                issues.append("SL below entry (short)")
            if setup.tp1 >= setup.entry_price:
                issues.append("TP1 above entry (short)")
        return {"valid": len(issues) == 0, "issues": issues}

    def format_setup(self, setup: TradeSetup) -> str:
        e  = "🟢" if setup.direction == "long" else "🔴"
        lines = [
            f"{e} {setup.symbol} {setup.direction.upper()}",
            f"├─ Entry:    {setup.entry_price:.5f}  [{setup.entry_type}]",
            f"├─ Stop:     {setup.stop_loss:.5f}",
            f"├─ TP1:      {setup.tp1:.5f}",
            f"├─ TP2:      {setup.tp2:.5f}",
            f"├─ TP3:      {setup.tp3:.5f}",
            f"├─ R:R:      1:{setup.risk_reward}",
            f"├─ Lots:     {setup.position_size}",
            f"├─ Risk:     ${setup.risk_amount} ({setup.risk_percent:.1f}%)",
            f"├─ Conf:     {setup.confidence}%",
            f"├─ HTF/LTF:  {setup.htf} → {setup.ltf}",
            f"└─ {setup.narrative[:120]}",
        ]
        return "\n".join(lines)

    # ── Market Pip Info ──────────────────────────────────────────────────
    @staticmethod
    def _pip_value(symbol: str) -> float:
        s = symbol.upper().replace("/", "")
        if "JPY" in s:              return 6.5
        if any(x in s for x in ["XAU", "GOLD"]):  return 1.0
        if any(x in s for x in ["US30", "NAS", "SPX", "DJ"]): return 1.0
        if any(x in s for x in ["BTC", "ETH"]):   return 1.0
        return 10.0

    @staticmethod
    def _pip_size(symbol: str) -> float:
        s = symbol.upper().replace("/", "")
        if "JPY" in s:              return 0.01
        if any(x in s for x in ["XAU", "GOLD"]):  return 0.1
        if any(x in s for x in ["US30", "NAS", "SPX", "BTC", "ETH"]): return 1.0
        return 0.0001