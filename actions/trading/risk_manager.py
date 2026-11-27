# actions/trading/risk_manager.py
"""
Risk Manager
─────────────
Handles:
  - Daily loss limit tracker    (stop trading if -X% hit)
  - Max drawdown protection     (account level)
  - Trade journal               (every trade logged to JSON + CSV)
  - Session filter              (London / New York / Asian / Sydney)
  - Kill switch                 (auto-stop if limits breached)
  - Performance statistics      (win rate, avg RR, profit factor)
  - Weekly / Monthly reports
  - Consecutive loss tracker    (pause after N losses)
"""

import json
import csv
import os
import time
import threading
from datetime  import datetime, timedelta
from pathlib   import Path
from typing    import Optional
import pytz


# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────

# Default risk limits
DEFAULT_DAILY_LOSS_PCT    = 3.0     # Stop trading after -3% daily
DEFAULT_MAX_DRAWDOWN_PCT  = 6.0     # Kill switch at -6% drawdown
DEFAULT_MAX_CONSEC_LOSSES = 3       # Pause after 3 consecutive losses
DEFAULT_RISK_PER_TRADE    = 1.0     # 1% per trade

# Session times (UTC)
SESSIONS = {
    "SYDNEY": {
        "start": (21, 0),   # 21:00 UTC (Sun)
        "end":   (6,  0),   # 06:00 UTC
        "tz":    "Australia/Sydney",
        "pairs": ["AUDUSD", "NZDUSD", "AUDNZD", "AUDJPY"],
    },
    "TOKYO": {
        "start": (0,  0),   # 00:00 UTC
        "end":   (9,  0),   # 09:00 UTC
        "tz":    "Asia/Tokyo",
        "pairs": ["USDJPY", "EURJPY", "GBPJPY", "AUDJPY"],
    },
    "LONDON": {
        "start": (7,  0),   # 07:00 UTC
        "end":   (16, 0),   # 16:00 UTC
        "tz":    "Europe/London",
        "pairs": [
            "EURUSD", "GBPUSD", "EURGBP",
            "USDCHF", "EURJPY", "GBPJPY",
        ],
    },
    "NEW_YORK": {
        "start": (12, 0),   # 12:00 UTC
        "end":   (21, 0),   # 21:00 UTC
        "tz":    "America/New_York",
        "pairs": [
            "EURUSD", "GBPUSD", "USDJPY",
            "USDCAD", "USDCHF", "XAUUSD",
        ],
    },
    "KILLZONE_LONDON_OPEN": {
        "start": (7,  0),
        "end":   (9,  0),
        "tz":    "UTC",
        "pairs": ["EURUSD", "GBPUSD", "EURGBP"],
    },
    "KILLZONE_NY_OPEN": {
        "start": (12, 0),
        "end":   (14, 0),
        "tz":    "UTC",
        "pairs": ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"],
    },
    "KILLZONE_NY_CLOSE": {
        "start": (19, 0),
        "end":   (21, 0),
        "tz":    "UTC",
        "pairs": ["EURUSD", "GBPUSD"],
    },
}

# Journal file paths
JOURNAL_DIR = Path.home() / "JARVIS_Trading"


# ─────────────────────────────────────────────────────────────
# SESSION MANAGER
# ─────────────────────────────────────────────────────────────

class SessionManager:
    """
    Manages trading sessions and killzones.
    Only trades during high-probability ICT sessions.
    """

    def __init__(self):
        self._utc = pytz.UTC

    def get_utc_now(self) -> datetime:
        """Get current UTC time."""
        return datetime.now(pytz.UTC)

    def get_active_sessions(self) -> list[dict]:
        """
        Get all currently active sessions.
        Returns list of active session dicts.
        """
        now     = self.get_utc_now()
        h, m    = now.hour, now.minute
        active  = []

        for name, sess in SESSIONS.items():
            s_h, s_m = sess["start"]
            e_h, e_m = sess["end"]

            start_mins = s_h * 60 + s_m
            end_mins   = e_h * 60 + e_m
            now_mins   = h   * 60 + m

            # Handle overnight sessions (e.g. Sydney crosses midnight)
            if start_mins > end_mins:
                in_session = (
                    now_mins >= start_mins or
                    now_mins <  end_mins
                )
            else:
                in_session = start_mins <= now_mins < end_mins

            if in_session:
                active.append({
                    "name":  name,
                    "pairs": sess["pairs"],
                    "tz":    sess["tz"],
                    "start": f"{s_h:02d}:{s_m:02d} UTC",
                    "end":   f"{e_h:02d}:{e_m:02d} UTC",
                })

        return active

    def is_killzone(self) -> bool:
        """Check if we are in an ICT killzone."""
        active = self.get_active_sessions()
        return any("KILLZONE" in s["name"] for s in active)

    def is_valid_session(
        self,
        symbol:           str,
        require_killzone: bool = False,
    ) -> dict:
        """
        Check if symbol can be traded in current session.

        Args:
            symbol:           Trading symbol
            require_killzone: Only allow trades in killzones

        Returns:
            {
              "allowed":  bool,
              "sessions": list of active sessions,
              "reason":   str,
            }
        """
        active   = self.get_active_sessions()
        sym_up   = symbol.upper().replace("/", "").replace("-", "")

        # Check if market is closed (weekend)
        now = self.get_utc_now()
        if now.weekday() == 5:  # Saturday
            return {
                "allowed":  False,
                "sessions": [],
                "reason":   "Markets closed — Saturday",
            }
        if now.weekday() == 6 and now.hour < 21:  # Sunday before Sydney
            return {
                "allowed":  False,
                "sessions": [],
                "reason":   "Markets closed — Sunday (before Sydney open)",
            }

        if not active:
            return {
                "allowed":  False,
                "sessions": [],
                "reason":   "No active trading session",
            }

        # Killzone filter
        if require_killzone and not self.is_killzone():
            return {
                "allowed":  False,
                "sessions": active,
                "reason":   "Not in ICT killzone (London/NY open)",
            }

        # Check symbol is in at least one active session
        valid_sessions = []
        for sess in active:
            for pair in sess["pairs"]:
                if pair.upper() in sym_up or sym_up in pair.upper():
                    valid_sessions.append(sess["name"])
                    break

        # Gold / indices can trade in any major session
        if any(x in sym_up for x in ["XAU", "GOLD", "US30", "NAS"]):
            valid_sessions = [s["name"] for s in active]

        if valid_sessions:
            return {
                "allowed":  True,
                "sessions": active,
                "reason":   f"Active: {', '.join(valid_sessions)}",
            }

        return {
            "allowed":  False,
            "sessions": active,
            "reason":   (
                f"{symbol} not ideal in current sessions: "
                f"{[s['name'] for s in active]}"
            ),
        }

    def get_next_killzone(self) -> dict:
        """Get the next ICT killzone time."""
        now      = self.get_utc_now()
        h, m     = now.hour, now.minute
        now_mins = h * 60 + m

        killzones = {
            name: sess
            for name, sess in SESSIONS.items()
            if "KILLZONE" in name
        }

        nearest      = None
        nearest_mins = float("inf")

        for name, sess in killzones.items():
            s_h, s_m  = sess["start"]
            start_mins = s_h * 60 + s_m

            # Minutes until this killzone
            if start_mins > now_mins:
                diff = start_mins - now_mins
            else:
                diff = (24 * 60 - now_mins) + start_mins

            if diff < nearest_mins:
                nearest_mins = diff
                nearest      = {
                    "name":         name,
                    "start":        f"{s_h:02d}:{s_m:02d} UTC",
                    "minutes_away": diff,
                    "hours_away":   round(diff / 60, 1),
                }

        return nearest or {}

    def format_sessions(self) -> str:
        """Human readable session status."""
        active = self.get_active_sessions()
        now    = self.get_utc_now()
        lines  = [
            "🕐 TRADING SESSIONS",
            "─" * 42,
            f"UTC Time: {now.strftime('%H:%M:%S')}",
            f"In Killzone: {'✅ YES' if self.is_killzone() else '❌ NO'}",
            "",
        ]

        if active:
            lines.append("Active Sessions:")
            for s in active:
                kz = " 🎯 KILLZONE" if "KILLZONE" in s["name"] else ""
                lines.append(f"  • {s['name']}{kz}")
                lines.append(f"    {s['start']} — {s['end']}")
        else:
            lines.append("No active sessions.")

        next_kz = self.get_next_killzone()
        if next_kz:
            lines += [
                "",
                f"Next Killzone: {next_kz['name']}",
                f"  At: {next_kz['start']}",
                f"  In: {next_kz['hours_away']}h",
            ]

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# TRADE JOURNAL
# ─────────────────────────────────────────────────────────────

class TradeJournal:
    """
    Logs every trade to JSON and CSV.
    Tracks performance over time.
    """

    def __init__(self, journal_dir: Path = JOURNAL_DIR):
        self.dir      = Path(journal_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.json_path = self.dir / "trade_journal.json"
        self.csv_path  = self.dir / "trade_journal.csv"
        self._lock     = threading.Lock()
        self._trades   = self._load_journal()

    def _load_journal(self) -> list[dict]:
        """Load existing journal from disk."""
        if self.json_path.exists():
            try:
                with open(self.json_path, "r") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save_journal(self):
        """Save journal to disk."""
        with open(self.json_path, "w") as f:
            json.dump(self._trades, f, indent=2, default=str)

        # CSV export
        if self._trades:
            keys = self._trades[0].keys()
            with open(self.csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(self._trades)

    def log_entry(
        self,
        ticket:      int,
        symbol:      str,
        direction:   str,
        setup_type:  str,
        entry_price: float,
        stop_loss:   float,
        tp1:         float,
        tp2:         float,
        lot_size:    float,
        risk_amount: float,
        entry_type:  str    = "",
        score:       float  = 0.0,
        session:     str    = "",
        notes:       str    = "",
    ):
        """Log a new trade entry."""
        trade = {
            "ticket":      ticket,
            "symbol":      symbol,
            "direction":   direction,
            "setup_type":  setup_type,
            "entry_type":  entry_type,
            "entry_price": entry_price,
            "stop_loss":   stop_loss,
            "tp1":         tp1,
            "tp2":         tp2,
            "lot_size":    lot_size,
            "risk_amount": risk_amount,
            "score":       score,
            "session":     session,
            "notes":       notes,

            # To be filled on close
            "exit_price":  None,
            "exit_time":   None,
            "pnl":         None,
            "pips":        None,
            "outcome":     None,   # WIN | LOSS | BE
            "rr_achieved": None,
            "duration_h":  None,

            "entry_time":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "date":        datetime.now().strftime("%Y-%m-%d"),
        }

        with self._lock:
            self._trades.append(trade)
            self._save_journal()

        print(f"[Journal] Trade #{ticket} logged: {direction} {symbol}")

    def log_exit(
        self,
        ticket:     int,
        exit_price: float,
        pnl:        float,
        pips:       float = None,
    ):
        """Update journal with trade exit data."""
        with self._lock:
            for trade in self._trades:
                if trade["ticket"] == ticket and trade["exit_time"] is None:
                    entry_time = datetime.strptime(
                        trade["entry_time"], "%Y-%m-%d %H:%M:%S"
                    )
                    exit_time = datetime.now()
                    duration  = (exit_time - entry_time).total_seconds() / 3600

                    trade["exit_price"]  = exit_price
                    trade["exit_time"]   = exit_time.strftime("%Y-%m-%d %H:%M:%S")
                    trade["pnl"]         = round(pnl, 2)
                    trade["duration_h"]  = round(duration, 2)

                    if pips is not None:
                        trade["pips"] = round(pips, 1)

                    # Outcome
                    if pnl > 0:
                        trade["outcome"] = "WIN"
                    elif pnl < 0:
                        trade["outcome"] = "LOSS"
                    else:
                        trade["outcome"] = "BE"

                    # R:R achieved
                    risk = trade.get("risk_amount", 1)
                    if risk and risk != 0:
                        trade["rr_achieved"] = round(pnl / risk, 2)

                    self._save_journal()
                    print(f"[Journal] Trade #{ticket} closed: {trade['outcome']} {pnl:+.2f}")
                    return True

        return False

    def get_today_trades(self) -> list[dict]:
        """Get all trades from today."""
        today = datetime.now().strftime("%Y-%m-%d")
        return [t for t in self._trades if t.get("date") == today]

    def get_trades_by_date(
        self,
        start: str,  # YYYY-MM-DD
        end:   str,  # YYYY-MM-DD
    ) -> list[dict]:
        """Get trades between two dates."""
        return [
            t for t in self._trades
            if start <= t.get("date", "") <= end
        ]

    def get_open_trades(self) -> list[dict]:
        """Get trades not yet closed."""
        return [t for t in self._trades if t["exit_time"] is None]


# ─────────────────────────────────────────────────────────────
# PERFORMANCE STATS
# ─────────────────────────────────────────────────────────────

class PerformanceStats:
    """Calculates trading performance metrics."""

    def __init__(self, journal: TradeJournal):
        self._journal = journal

    def _closed_trades(
        self,
        trades: list[dict] = None,
    ) -> list[dict]:
        """Filter to closed trades only."""
        t = trades or self._journal._trades
        return [x for x in t if x.get("exit_time") is not None]

    def calculate(
        self,
        trades: list[dict] = None,
        period: str        = "all",    # all | today | week | month
    ) -> dict:
        """
        Calculate full performance statistics.

        Returns:
          {
            "total_trades":   int,
            "wins":           int,
            "losses":         int,
            "breakevens":     int,
            "win_rate":       float,
            "avg_rr":         float,
            "profit_factor":  float,
            "total_pnl":      float,
            "avg_win":        float,
            "avg_loss":       float,
            "best_trade":     float,
            "worst_trade":    float,
            "consec_wins":    int,
            "consec_losses":  int,
            "expectancy":     float,
          }
        """
        # Filter by period
        if period == "today":
            trades = self._journal.get_today_trades()
        elif period == "week":
            start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            end   = datetime.now().strftime("%Y-%m-%d")
            trades = self._journal.get_trades_by_date(start, end)
        elif period == "month":
            start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            end   = datetime.now().strftime("%Y-%m-%d")
            trades = self._journal.get_trades_by_date(start, end)
        else:
            trades = trades or self._journal._trades

        closed = self._closed_trades(trades)

        if not closed:
            return {
                "total_trades":  0,
                "wins":          0,
                "losses":        0,
                "breakevens":    0,
                "win_rate":      0.0,
                "avg_rr":        0.0,
                "profit_factor": 0.0,
                "total_pnl":     0.0,
                "avg_win":       0.0,
                "avg_loss":      0.0,
                "best_trade":    0.0,
                "worst_trade":   0.0,
                "consec_wins":   0,
                "consec_losses": 0,
                "expectancy":    0.0,
                "period":        period,
            }

        wins       = [t for t in closed if t["outcome"] == "WIN"]
        losses     = [t for t in closed if t["outcome"] == "LOSS"]
        breakevens = [t for t in closed if t["outcome"] == "BE"]

        total_pnl  = sum(t.get("pnl", 0) or 0 for t in closed)
        win_pnls   = [t.get("pnl", 0) or 0 for t in wins]
        loss_pnls  = [t.get("pnl", 0) or 0 for t in losses]

        win_rate   = len(wins) / len(closed) * 100 if closed else 0
        avg_win    = sum(win_pnls)  / len(wins)   if wins   else 0
        avg_loss   = sum(loss_pnls) / len(losses) if losses else 0

        # Profit factor
        gross_profit = sum(p for p in win_pnls  if p > 0)
        gross_loss   = abs(sum(p for p in loss_pnls if p < 0))
        profit_factor = (
            gross_profit / gross_loss
            if gross_loss > 0 else float("inf")
        )

        # Average R:R
        rr_vals = [
            t.get("rr_achieved", 0) or 0
            for t in closed
            if t.get("rr_achieved") is not None
        ]
        avg_rr = sum(rr_vals) / len(rr_vals) if rr_vals else 0

        # Consecutive wins/losses
        outcomes    = [t["outcome"] for t in closed]
        max_cw = cw = max_cl = cl = 0
        for o in outcomes:
            if o == "WIN":
                cw += 1; cl = 0
                max_cw = max(max_cw, cw)
            elif o == "LOSS":
                cl += 1; cw = 0
                max_cl = max(max_cl, cl)
            else:
                cw = cl = 0

        # Expectancy
        wr = win_rate / 100
        expectancy = (wr * avg_win) + ((1 - wr) * avg_loss)

        return {
            "total_trades":  len(closed),
            "wins":          len(wins),
            "losses":        len(losses),
            "breakevens":    len(breakevens),
            "win_rate":      round(win_rate,      1),
            "avg_rr":        round(avg_rr,        2),
            "profit_factor": round(profit_factor, 2),
            "total_pnl":     round(total_pnl,     2),
            "avg_win":       round(avg_win,        2),
            "avg_loss":      round(avg_loss,       2),
            "best_trade":    round(max(win_pnls  or [0]), 2),
            "worst_trade":   round(min(loss_pnls or [0]), 2),
            "consec_wins":   max_cw,
            "consec_losses": max_cl,
            "expectancy":    round(expectancy,    2),
            "gross_profit":  round(gross_profit,  2),
            "gross_loss":    round(gross_loss,    2),
            "period":        period,
        }

    def format_stats(self, period: str = "all") -> str:
        """Human readable performance report."""
        s     = self.calculate(period=period)
        pf    = s["profit_factor"]
        pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
        pnl_sign = "+" if s["total_pnl"] >= 0 else ""

        lines = [
            f"📈 PERFORMANCE — {s['period'].upper()}",
            "─" * 42,
            f"Total Trades:   {s['total_trades']}",
            f"Wins:           {s['wins']}",
            f"Losses:         {s['losses']}",
            f"Breakevens:     {s['breakevens']}",
            f"Win Rate:       {s['win_rate']:.1f}%",
            "",
            f"Avg R:R:        {s['avg_rr']:.2f}:1",
            f"Profit Factor:  {pf_str}",
            f"Expectancy:     {s['expectancy']:+.2f}",
            "",
            f"Total P&L:      {pnl_sign}{s['total_pnl']:.2f}",
            f"Gross Profit:   +{s['gross_profit']:.2f}",
            f"Gross Loss:     -{s['gross_loss']:.2f}",
            f"Avg Win:        +{s['avg_win']:.2f}",
            f"Avg Loss:       {s['avg_loss']:.2f}",
            f"Best Trade:     +{s['best_trade']:.2f}",
            f"Worst Trade:    {s['worst_trade']:.2f}",
            "",
            f"Max Consec W:   {s['consec_wins']}",
            f"Max Consec L:   {s['consec_losses']}",
        ]

        # Grade
        if s["total_trades"] >= 10:
            if s["win_rate"] >= 60 and s["avg_rr"] >= 2.0:
                grade = "A+ — Excellent"
            elif s["win_rate"] >= 50 and s["avg_rr"] >= 1.5:
                grade = "A  — Strong"
            elif s["win_rate"] >= 40 and s["profit_factor"] >= 1.5:
                grade = "B  — Good"
            elif s["profit_factor"] >= 1.0:
                grade = "C  — Acceptable"
            else:
                grade = "D  — Review strategy"

            lines += ["", f"Grade:          {grade}"]

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# RISK GUARD
# ─────────────────────────────────────────────────────────────

class RiskGuard:
    """
    Real-time risk enforcement.
    Prevents trading if limits are breached.
    """

    def __init__(
        self,
        daily_loss_pct:    float = DEFAULT_DAILY_LOSS_PCT,
        max_drawdown_pct:  float = DEFAULT_MAX_DRAWDOWN_PCT,
        max_consec_losses: int   = DEFAULT_MAX_CONSEC_LOSSES,
        journal:           TradeJournal = None,
        player             = None,
        speak              = None,
    ):
        self.daily_loss_pct    = daily_loss_pct
        self.max_drawdown_pct  = max_drawdown_pct
        self.max_consec_losses = max_consec_losses
        self._journal          = journal
        self.player            = player
        self.speak             = speak

        # State
        self._killed            = False
        self._kill_reason       = ""
        self._daily_loss        = 0.0
        self._starting_balance  = 0.0
        self._peak_balance      = 0.0
        self._consec_losses     = 0

    def _log(self, msg: str):
        print(f"[RiskGuard] {msg}")
        if self.player:
            self.player.write_log(f"[Risk] {msg}")

    def _say(self, msg: str):
        if self.speak:
            self.speak(msg)

    def set_starting_balance(self, balance: float):
        """Call this when trading session starts."""
        self._starting_balance = balance
        self._peak_balance     = balance
        self._daily_loss       = 0.0
        self._log(f"Starting balance set: ${balance:.2f}")

    def update_balance(self, current_balance: float):
        """Update current balance — recalculates drawdown."""
        self._peak_balance = max(self._peak_balance, current_balance)
        daily_pnl          = current_balance - self._starting_balance
        if daily_pnl < 0:
            self._daily_loss = abs(daily_pnl)

    def record_trade_result(self, outcome: str, pnl: float):
        """
        Record trade outcome for consecutive loss tracking.
        outcome: WIN | LOSS | BE
        """
        if outcome == "LOSS":
            self._consec_losses += 1
            self._daily_loss    += abs(pnl)
            self._log(
                f"Loss recorded. "
                f"Consecutive: {self._consec_losses} | "
                f"Daily loss: ${self._daily_loss:.2f}"
            )

            if self._consec_losses >= self.max_consec_losses:
                self._kill(
                    f"{self._consec_losses} consecutive losses — "
                    f"trading paused"
                )

        elif outcome == "WIN":
            self._consec_losses = 0

        elif outcome == "BE":
            pass   # Breakeven resets nothing

    def _kill(self, reason: str):
        """Activate kill switch."""
        if not self._killed:
            self._killed      = True
            self._kill_reason = reason
            self._log(f"🚨 KILL SWITCH ACTIVATED: {reason}")
            self._say(
                f"Sir, trading has been stopped. {reason}. "
                f"Please review your positions and restart manually."
            )

    def reset_kill(self):
        """Manually reset kill switch (user confirms)."""
        self._killed        = False
        self._kill_reason   = ""
        self._consec_losses = 0
        self._log("Kill switch reset by user")

    def reset_daily(self):
        """Reset daily counters — call at start of new day."""
        self._daily_loss    = 0.0
        self._consec_losses = 0
        self._killed        = False
        self._kill_reason   = ""
        self._log("Daily risk counters reset")

    def can_trade(
        self,
        symbol:          str   = "",
        account_balance: float = None,
    ) -> dict:
        """
        Master check — can we place a new trade?

        Returns:
          {
            "allowed":       bool,
            "reason":        str,
            "daily_loss":    float,
            "drawdown_pct":  float,
            "consec_losses": int,
          }
        """
        # Kill switch
        if self._killed:
            return {
                "allowed":       False,
                "reason":        f"Kill switch active: {self._kill_reason}",
                "daily_loss":    self._daily_loss,
                "drawdown_pct":  self._get_drawdown_pct(account_balance),
                "consec_losses": self._consec_losses,
            }

        # Daily loss check
        if self._starting_balance > 0:
            daily_loss_pct = (
                self._daily_loss / self._starting_balance * 100
            )
            if daily_loss_pct >= self.daily_loss_pct:
                self._kill(
                    f"Daily loss limit reached: "
                    f"{daily_loss_pct:.1f}% "
                    f"(limit: {self.daily_loss_pct}%)"
                )
                return {
                    "allowed":       False,
                    "reason":        self._kill_reason,
                    "daily_loss":    self._daily_loss,
                    "drawdown_pct":  daily_loss_pct,
                    "consec_losses": self._consec_losses,
                }

        # Max drawdown check
        dd_pct = self._get_drawdown_pct(account_balance)
        if dd_pct >= self.max_drawdown_pct:
            self._kill(
                f"Max drawdown hit: {dd_pct:.1f}% "
                f"(limit: {self.max_drawdown_pct}%)"
            )
            return {
                "allowed":       False,
                "reason":        self._kill_reason,
                "daily_loss":    self._daily_loss,
                "drawdown_pct":  dd_pct,
                "consec_losses": self._consec_losses,
            }

        # Consecutive losses
        if self._consec_losses >= self.max_consec_losses:
            return {
                "allowed":       False,
                "reason":        (
                    f"{self._consec_losses} consecutive losses — "
                    f"take a break and review"
                ),
                "daily_loss":    self._daily_loss,
                "drawdown_pct":  dd_pct,
                "consec_losses": self._consec_losses,
            }

        return {
            "allowed":       True,
            "reason":        "All risk checks passed",
            "daily_loss":    self._daily_loss,
            "drawdown_pct":  dd_pct,
            "consec_losses": self._consec_losses,
        }

    def _get_drawdown_pct(
        self,
        current_balance: float = None,
    ) -> float:
        """Calculate current drawdown percentage."""
        if not self._peak_balance or not current_balance:
            return 0.0
        dd = (self._peak_balance - current_balance) / self._peak_balance * 100
        return round(max(dd, 0.0), 2)

    def format_status(
        self,
        account_balance: float = None,
    ) -> str:
        """Human readable risk status."""
        dd = self._get_drawdown_pct(account_balance)
        lines = [
            "🛡️  RISK MANAGER STATUS",
            "─" * 42,
            f"Kill Switch:    {'🚨 ACTIVE' if self._killed else '✅ OFF'}",
            f"Daily Loss:     ${self._daily_loss:.2f} "
            f"({self.daily_loss_pct}% limit)",
            f"Drawdown:       {dd:.1f}% "
            f"({self.max_drawdown_pct}% limit)",
            f"Consec Losses:  {self._consec_losses} "
            f"({self.max_consec_losses} limit)",
        ]

        if self._killed:
            lines.append(f"Reason:         {self._kill_reason}")

        if account_balance and self._starting_balance:
            daily_pnl  = account_balance - self._starting_balance
            sign       = "+" if daily_pnl >= 0 else ""
            lines.append(f"Daily P&L:      {sign}{daily_pnl:.2f}")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# MAIN RISK MANAGER
# ─────────────────────────────────────────────────────────────

class RiskManager:
    """
    Main risk manager — combines all components.
    Used by trading_agent.py as the risk layer.
    """

    def __init__(
        self,
        daily_loss_pct:    float = DEFAULT_DAILY_LOSS_PCT,
        max_drawdown_pct:  float = DEFAULT_MAX_DRAWDOWN_PCT,
        max_consec_losses: int   = DEFAULT_MAX_CONSEC_LOSSES,
        risk_per_trade:    float = DEFAULT_RISK_PER_TRADE,
        player             = None,
        speak              = None,
    ):
        self.risk_per_trade = risk_per_trade
        self.player         = player
        self.speak          = speak

        self.journal  = TradeJournal()
        self.guard    = RiskGuard(
            daily_loss_pct    = daily_loss_pct,
            max_drawdown_pct  = max_drawdown_pct,
            max_consec_losses = max_consec_losses,
            journal           = self.journal,
            player            = player,
            speak             = speak,
        )
        self.session  = SessionManager()
        self.stats    = PerformanceStats(self.journal)

    def pre_trade_check(
        self,
        symbol:          str,
        setup_score:     float,
        account_balance: float  = None,
        require_killzone: bool  = False,
        min_score:       float  = 0.45,
    ) -> dict:
        """
        Full pre-trade validation.
        Call before placing any trade.

        Returns:
          {
            "allowed":  bool,
            "reason":   str,
            "checks":   dict of individual checks,
          }
        """
        checks  = {}
        reasons = []

        # ── Risk guard ────────────────────────────
        risk_ok = self.guard.can_trade(symbol, account_balance)
        checks["risk_guard"] = risk_ok
        if not risk_ok["allowed"]:
            reasons.append(risk_ok["reason"])

        # ── Session check ─────────────────────────
        sess_ok = self.session.is_valid_session(
            symbol, require_killzone
        )
        checks["session"] = sess_ok
        if not sess_ok["allowed"]:
            reasons.append(sess_ok["reason"])

        # ── Setup quality ─────────────────────────
        score_ok = setup_score >= min_score
        checks["score"] = {
            "allowed": score_ok,
            "score":   setup_score,
            "minimum": min_score,
        }
        if not score_ok:
            reasons.append(
                f"Setup score {setup_score*100:.0f}% below "
                f"minimum {min_score*100:.0f}%"
            )

        allowed = len(reasons) == 0

        return {
            "allowed": allowed,
            "reason":  "; ".join(reasons) if reasons else "All checks passed",
            "checks":  checks,
        }

    def log_trade_entry(self, trade_result: dict, setup: dict):
        """Log a new trade to the journal."""
        if not trade_result.get("success"):
            return

        active_sessions = self.session.get_active_sessions()
        session_names   = ", ".join(
            s["name"] for s in active_sessions
        )

        self.journal.log_entry(
            ticket      = trade_result.get("ticket", 0),
            symbol      = setup.get("symbol", ""),
            direction   = setup.get("direction", ""),
            setup_type  = setup.get("setup_type", ""),
            entry_price = trade_result.get("entry", 0),
            stop_loss   = trade_result.get("stop_loss", 0),
            tp1         = trade_result.get("tp1", 0),
            tp2         = trade_result.get("tp2", 0),
            lot_size    = trade_result.get("lot_size", 0),
            risk_amount = trade_result.get("risk_amount", 0),
            entry_type  = setup.get("entry_type", ""),
            score       = setup.get("score", 0),
            session     = session_names,
        )

    def log_trade_exit(
        self,
        ticket:     int,
        exit_price: float,
        pnl:        float,
    ):
        """Log trade exit and update risk guard."""
        self.journal.log_exit(ticket, exit_price, pnl)

        outcome = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "BE"
        self.guard.record_trade_result(outcome, pnl)

    def get_full_report(self) -> str:
        """Full risk + performance report."""
        lines = [
            self.guard.format_status(),
            "",
            self.session.format_sessions(),
            "",
            self.stats.format_stats(period="today"),
            "",
            "─" * 42,
            "ALL TIME:",
            self.stats.format_stats(period="all"),
        ]
        return "\n".join(lines)