# actions/trading/mt5_executor.py
"""
MT5 Executor
─────────────
Handles:
  - MT5 connection (Windows native + Linux Wine)
  - Live and demo account support
  - Any broker support
  - Place market orders with SL/TP
  - Partial close at TP1 (50%)
  - Move SL to breakeven after TP1
  - Trailing stop
  - Max trades enforcer (max 2)
  - Trade monitoring loop
  - Position manager
  - Account info
  - Cross-platform (Windows/Linux/Mac)
"""

import os
import sys
import time
import platform
import threading
from datetime import datetime
from pathlib  import Path
from typing   import Optional


# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────

MAX_OPEN_TRADES     = 2
DEFAULT_MAGIC       = 20250101       # Magic number to identify JARVIS trades
SLIPPAGE            = 20             # Max slippage in points
RETRY_ATTEMPTS      = 3             # Order retry attempts
RETRY_DELAY         = 1.0           # Seconds between retries
MONITOR_INTERVAL    = 5.0           # Seconds between trade checks
TRAIL_ATR_MULT      = 1.0           # Trailing stop ATR multiple
BE_BUFFER_POINTS    = 5             # Points above entry for BE SL


# ─────────────────────────────────────────────────────────────
# PLATFORM DETECTOR
# ─────────────────────────────────────────────────────────────

class PlatformDetector:
    """Detects OS and MT5 availability."""

    _OS      = platform.system()
    _is_win  = _OS == "Windows"
    _is_lin  = _OS == "Linux"
    _is_mac  = _OS == "Darwin"

    @classmethod
    def get_os(cls) -> str:
        return cls._OS

    @classmethod
    def is_windows(cls) -> bool:
        return cls._is_win

    @classmethod
    def is_linux(cls) -> bool:
        return cls._is_lin

    @classmethod
    def is_mac(cls) -> bool:
        return cls._is_mac

    @classmethod
    def mt5_available(cls) -> bool:
        """Check if MT5 Python module is importable."""
        try:
            import MetaTrader5
            return True
        except ImportError:
            return False

    @classmethod
    def get_wine_mt5_path(cls) -> Optional[str]:
        """
        Find MT5 terminal on Linux via Wine.
        Checks common Wine prefix locations.
        """
        if not cls._is_lin:
            return None

        candidates = [
            Path.home() / ".wine_mt5" / "drive_c" /
            "Program Files" / "MetaTrader 5" / "terminal64.exe",

            Path.home() / ".wine" / "drive_c" /
            "Program Files" / "MetaTrader 5" / "terminal64.exe",

            Path.home() / ".wine" / "drive_c" /
            "Program Files (x86)" / "MetaTrader 5" / "terminal64.exe",
        ]

        # Check broker-specific paths
        wine_c = Path.home() / ".wine_mt5" / "drive_c" / "Program Files"
        if wine_c.exists():
            for broker_dir in wine_c.iterdir():
                t = broker_dir / "terminal64.exe"
                if t.exists():
                    candidates.append(t)

        for c in candidates:
            if Path(c).exists():
                return str(c)

        return None

    @classmethod
    def get_mt5_path_windows(cls) -> Optional[str]:
        """Find MT5 terminal on Windows."""
        if not cls._is_win:
            return None

        candidates = [
            Path("C:/Program Files/MetaTrader 5/terminal64.exe"),
            Path("C:/Program Files (x86)/MetaTrader 5/terminal64.exe"),
            Path.home() / "AppData/Roaming/MetaQuotes/Terminal",
        ]

        # Also check Program Files for broker-specific installs
        for pf in [
            Path("C:/Program Files"),
            Path("C:/Program Files (x86)"),
        ]:
            if pf.exists():
                for broker_dir in pf.iterdir():
                    t = broker_dir / "terminal64.exe"
                    if t.exists():
                        candidates.append(t)

        for c in candidates:
            p = Path(c)
            if p.exists() and p.is_file():
                return str(p)

        return None


# ─────────────────────────────────────────────────────────────
# MT5 CONNECTOR
# ─────────────────────────────────────────────────────────────

class MT5Connector:
    """
    Handles MT5 connection for any broker,
    any OS (Windows native, Linux via Wine).
    """

    def __init__(
        self,
        login:    int    = None,
        password: str    = None,
        server:   str    = None,
        path:     str    = None,
        timeout:  int    = 60000,
        player   = None,
    ):
        self.login    = login
        self.password = password
        self.server   = server
        self.path     = path
        self.timeout  = timeout
        self.player   = player
        self._mt5     = None
        self.connected = False
        self._info     = None

    def _log(self, msg: str):
        print(f"[MT5] {msg}")
        if self.player:
            self.player.write_log(f"[MT5] {msg}")

    def _import_mt5(self):
        """Import MetaTrader5 module with Wine support on Linux."""
        try:
            import MetaTrader5 as mt5
            self._mt5 = mt5
            return True
        except ImportError:
            self._log("MetaTrader5 not installed.")
            self._log("Install: pip install MetaTrader5")
            return False

    def _find_terminal_path(self) -> Optional[str]:
        """Auto-find MT5 terminal path."""
        if self.path and Path(self.path).exists():
            return self.path

        detector = PlatformDetector()

        if detector.is_windows():
            p = detector.get_mt5_path_windows()
            if p:
                self._log(f"Found MT5: {p}")
                return p

        elif detector.is_linux():
            p = detector.get_wine_mt5_path()
            if p:
                self._log(f"Found MT5 via Wine: {p}")
                # Set Wine env vars
                wine_prefix = str(Path(p).parent.parent.parent.parent)
                os.environ["WINEPREFIX"] = wine_prefix
                os.environ["WINEARCH"]   = "win64"
                return p

        return None

    def connect(
        self,
        login:    int = None,
        password: str = None,
        server:   str = None,
    ) -> dict:
        """
        Connect to MT5.
        Supports: any broker, live or demo.

        Args:
            login:    MT5 account number
            password: MT5 account password
            server:   Broker server name

        Returns:
            {"success": bool, "message": str, "info": dict}
        """
        # Override with passed args
        if login:    self.login    = login
        if password: self.password = password
        if server:   self.server   = server

        # Import MT5
        if not self._import_mt5():
            return {
                "success": False,
                "message": "MetaTrader5 module not found. "
                           "Install: pip install MetaTrader5",
            }

        mt5 = self._mt5

        # Find terminal path
        term_path = self._find_terminal_path()

        # Initialize MT5
        init_kwargs = {"timeout": self.timeout}
        if term_path:
            init_kwargs["path"] = term_path
        if self.login:
            init_kwargs["login"]    = int(self.login)
        if self.password:
            init_kwargs["password"] = str(self.password)
        if self.server:
            init_kwargs["server"]   = str(self.server)

        self._log(
            f"Connecting to MT5"
            f"{' via Wine' if PlatformDetector.is_linux() else ''}..."
        )

        if not mt5.initialize(**init_kwargs):
            err = mt5.last_error()
            mt5.shutdown()
            return {
                "success": False,
                "message": f"MT5 init failed: {err}",
            }

        # Login if credentials provided
        if self.login and self.password and self.server:
            authorized = mt5.login(
                login    = int(self.login),
                password = str(self.password),
                server   = str(self.server),
            )
            if not authorized:
                err = mt5.last_error()
                mt5.shutdown()
                return {
                    "success": False,
                    "message": f"MT5 login failed: {err}",
                }

        # Get account info
        info = mt5.account_info()
        if info is None:
            mt5.shutdown()
            return {
                "success": False,
                "message": "Could not get account info",
            }

        self._info     = info
        self.connected = True

        account_type = "DEMO" if info.trade_mode == 0 else "LIVE"
        self._log(
            f"✅ Connected — {account_type} | "
            f"Account: {info.login} | "
            f"Broker: {info.company} | "
            f"Balance: {info.balance:.2f} {info.currency}"
        )

        return {
            "success":  True,
            "message":  f"Connected to {info.company}",
            "info": {
                "login":    info.login,
                "name":     info.name,
                "server":   info.server,
                "company":  info.company,
                "balance":  info.balance,
                "equity":   info.equity,
                "margin":   info.margin,
                "currency": info.currency,
                "leverage": info.leverage,
                "type":     account_type,
            },
        }

    def disconnect(self):
        """Shutdown MT5 connection."""
        if self._mt5:
            self._mt5.shutdown()
            self.connected = False
            self._log("Disconnected from MT5")

    def get_account_info(self) -> dict:
        """Get current account information."""
        if not self.connected or not self._mt5:
            return {"error": "Not connected"}

        info = self._mt5.account_info()
        if not info:
            return {"error": "Could not get account info"}

        return {
            "login":        info.login,
            "name":         info.name,
            "server":       info.server,
            "company":      info.company,
            "balance":      info.balance,
            "equity":       info.equity,
            "margin":       info.margin,
            "free_margin":  info.margin_free,
            "margin_level": info.margin_level,
            "profit":       info.profit,
            "currency":     info.currency,
            "leverage":     info.leverage,
            "type":         "DEMO" if info.trade_mode == 0 else "LIVE",
        }


# ─────────────────────────────────────────────────────────────
# SYMBOL INFO
# ─────────────────────────────────────────────────────────────

class SymbolManager:
    """Manages MT5 symbol information."""

    def __init__(self, mt5, player=None):
        self._mt5    = mt5
        self.player  = player

    def _log(self, msg: str):
        print(f"[MT5-Symbol] {msg}")
        if self.player:
            self.player.write_log(f"[MT5] {msg}")

    def get_info(self, symbol: str) -> Optional[dict]:
        """Get symbol info from MT5."""
        info = self._mt5.symbol_info(symbol)
        if info is None:
            # Try to select symbol first
            self._mt5.symbol_select(symbol, True)
            time.sleep(0.5)
            info = self._mt5.symbol_info(symbol)

        if info is None:
            self._log(f"Symbol not found: {symbol}")
            return None

        return {
            "symbol":      info.name,
            "bid":         info.bid,
            "ask":         info.ask,
            "spread":      info.spread,
            "digits":      info.digits,
            "point":       info.point,
            "tick_size":   info.trade_tick_size,
            "tick_value":  info.trade_tick_value,
            "lot_min":     info.volume_min,
            "lot_max":     info.volume_max,
            "lot_step":    info.volume_step,
            "contract":    info.trade_contract_size,
            "currency":    info.currency_profit,
            "trade_mode":  info.trade_mode,
        }

    def normalize_price(self, symbol: str, price: float) -> float:
        """Round price to symbol's decimal places."""
        info = self._mt5.symbol_info(symbol)
        if info:
            digits = info.digits
            return round(price, digits)
        return round(price, 5)

    def normalize_volume(self, symbol: str, volume: float) -> float:
        """Round volume to symbol's lot step."""
        info = self._mt5.symbol_info(symbol)
        if info:
            step  = info.volume_step
            vol   = round(volume / step) * step
            vol   = max(vol, info.volume_min)
            vol   = min(vol, info.volume_max)
            return round(vol, 2)
        return round(max(volume, 0.01), 2)

    def get_current_price(
        self,
        symbol:    str,
        direction: str,
    ) -> float:
        """
        Get current price for entry.
        LONG  → use ask price
        SHORT → use bid price
        """
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            info = self.get_info(symbol)
            if info:
                return info["ask"] if direction == "BULLISH" else info["bid"]
            return 0.0

        return tick.ask if direction == "BULLISH" else tick.bid


# ─────────────────────────────────────────────────────────────
# RISK CALCULATOR
# ─────────────────────────────────────────────────────────────

class RiskCalculator:
    """Calculates position size for 1% risk."""

    def __init__(self, mt5, player=None):
        self._mt5   = mt5
        self.player = player

    def _log(self, msg: str):
        print(f"[MT5-Risk] {msg}")
        if self.player:
            self.player.write_log(f"[MT5] {msg}")

    def calculate_lot_size(
        self,
        symbol:       str,
        entry:        float,
        stop_loss:    float,
        risk_percent: float = 1.0,
        account_size: float = None,
    ) -> dict:
        """
        Calculate lot size for given risk %.

        Formula:
          risk_amount   = balance * risk_percent / 100
          sl_pips       = |entry - stop_loss| / point
          pip_value     = tick_value * (point / tick_size)
          lot_size      = risk_amount / (sl_pips * pip_value)

        Returns:
          {
            "lot_size":     float,
            "risk_amount":  float,
            "sl_pips":      float,
            "pip_value":    float,
          }
        """
        # Get account balance
        if account_size is None:
            info = self._mt5.account_info()
            if info is None:
                return {"error": "Cannot get account info"}
            account_size = info.balance

        risk_amount = account_size * (risk_percent / 100)

        # Get symbol info
        sym_info = self._mt5.symbol_info(symbol)
        if sym_info is None:
            return {"error": f"Symbol {symbol} not found"}

        point      = sym_info.point
        tick_size  = sym_info.trade_tick_size
        tick_value = sym_info.trade_tick_value
        lot_min    = sym_info.volume_min
        lot_step   = sym_info.volume_step

        # SL distance in points
        sl_distance = abs(entry - stop_loss)
        sl_pips     = sl_distance / point

        if sl_pips == 0:
            return {"error": "Stop loss too close to entry"}

        # Pip value per lot
        pip_value = tick_value * (point / tick_size) if tick_size > 0 else tick_value

        # Lot size
        if pip_value > 0 and sl_pips > 0:
            lot_size = risk_amount / (sl_pips * pip_value)
        else:
            lot_size = lot_min

        # Normalize to symbol constraints
        lot_size = round(lot_size / lot_step) * lot_step
        lot_size = max(lot_size, lot_min)
        lot_size = min(lot_size, sym_info.volume_max)
        lot_size = round(lot_size, 2)

        self._log(
            f"Risk calc: {risk_percent}% of ${account_size:.2f} = "
            f"${risk_amount:.2f} | SL: {sl_pips:.1f} pips | "
            f"Lots: {lot_size}"
        )

        return {
            "lot_size":    lot_size,
            "risk_amount": round(risk_amount, 2),
            "sl_pips":     round(sl_pips,     1),
            "pip_value":   round(pip_value,    4),
            "balance":     round(account_size, 2),
        }


# ─────────────────────────────────────────────────────────────
# ORDER EXECUTOR
# ─────────────────────────────────────────────────────────────

class OrderExecutor:
    """Places and manages MT5 orders."""

    def __init__(self, mt5, player=None, speak=None):
        self._mt5    = mt5
        self.player  = player
        self.speak   = speak
        self._sym    = SymbolManager(mt5, player)
        self._risk   = RiskCalculator(mt5, player)

    def _log(self, msg: str):
        print(f"[MT5-Order] {msg}")
        if self.player:
            self.player.write_log(f"[MT5] {msg}")

    def _say(self, msg: str):
        if self.speak:
            self.speak(msg)

    def _check_max_trades(self) -> dict:
        """
        Enforce max open trades limit.
        Returns {"allowed": bool, "current": int}
        """
        positions = self._mt5.positions_get(
            group="*"
        )
        jarvis_trades = []
        if positions:
            jarvis_trades = [
                p for p in positions
                if p.magic == DEFAULT_MAGIC
            ]

        count = len(jarvis_trades)
        return {
            "allowed": count < MAX_OPEN_TRADES,
            "current": count,
            "max":     MAX_OPEN_TRADES,
        }

    def place_market_order(
        self,
        symbol:       str,
        direction:    str,       # BULLISH | BEARISH
        stop_loss:    float,
        tp1:          float,
        tp2:          float,
        risk_percent: float = 1.0,
        comment:      str   = "JARVIS-ICT",
        magic:        int   = DEFAULT_MAGIC,
    ) -> dict:
        """
        Place market order with full risk management.

        Args:
            symbol:       Trading symbol
            direction:    BULLISH (long) or BEARISH (short)
            stop_loss:    SL price
            tp1:          First target (1:1 R:R)
            tp2:          Final target (next liquidity)
            risk_percent: Risk per trade (default 1%)
            comment:      Order comment
            magic:        Magic number

        Returns:
            Order result dict
        """
        # ── Max trades check ──────────────────────
        trade_check = self._check_max_trades()
        if not trade_check["allowed"]:
            msg = (
                f"Max trades reached "
                f"({trade_check['current']}/{MAX_OPEN_TRADES}). "
                f"Cannot place new trade."
            )
            self._log(msg)
            self._say(
                f"Sir, I cannot place this trade. "
                f"We already have {trade_check['current']} open trades. "
                f"Maximum is {MAX_OPEN_TRADES}."
            )
            return {"success": False, "message": msg}

        # ── Symbol info ───────────────────────────
        sym_info = self._sym.get_info(symbol)
        if not sym_info:
            return {
                "success": False,
                "message": f"Symbol {symbol} not found on broker",
            }

        # ── Order type ────────────────────────────
        mt5      = self._mt5
        buy_type = mt5.ORDER_TYPE_BUY
        sel_type = mt5.ORDER_TYPE_SELL
        order_type = buy_type if direction == "BULLISH" else sel_type

        # ── Current price ─────────────────────────
        entry_price = self._sym.get_current_price(symbol, direction)
        if entry_price == 0:
            return {
                "success": False,
                "message": "Cannot get current price",
            }

        # ── Normalize prices ──────────────────────
        sl_price = self._sym.normalize_price(symbol, stop_loss)
        tp_price = self._sym.normalize_price(symbol, tp2)  # Use TP2 as main TP
        entry    = self._sym.normalize_price(symbol, entry_price)

        # ── Calculate lot size ────────────────────
        risk_result = self._risk.calculate_lot_size(
            symbol, entry, sl_price, risk_percent
        )
        if "error" in risk_result:
            return {
                "success": False,
                "message": f"Risk calc failed: {risk_result['error']}",
            }

        lot_size = risk_result["lot_size"]

        # ── Build order request ───────────────────
        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       lot_size,
            "type":         order_type,
            "price":        entry,
            "sl":           sl_price,
            "tp":           tp_price,
            "deviation":    SLIPPAGE,
            "magic":        magic,
            "comment":      comment,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        self._log(
            f"Placing {direction} order: "
            f"{symbol} {lot_size} lots | "
            f"Entry: {entry} | SL: {sl_price} | TP: {tp_price}"
        )

        # ── Send with retries ─────────────────────
        result = None
        for attempt in range(RETRY_ATTEMPTS):
            result = mt5.order_send(request)

            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                break

            if result:
                self._log(
                    f"Attempt {attempt+1} failed: "
                    f"retcode={result.retcode} "
                    f"comment={result.comment}"
                )
                # Update price on requote
                if result.retcode == mt5.TRADE_RETCODE_REQUOTE:
                    entry = self._sym.get_current_price(symbol, direction)
                    request["price"] = self._sym.normalize_price(symbol, entry)

            time.sleep(RETRY_DELAY)

        if not result or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else "Unknown error"
            msg = f"Order failed after {RETRY_ATTEMPTS} attempts: {err}"
            self._log(msg)
            self._say(
                f"Sir, the order failed. {err}"
            )
            return {"success": False, "message": msg}

        # ── Success ───────────────────────────────
        ticket = result.order
        dir_word = "long" if direction == "BULLISH" else "short"

        self._log(
            f"✅ Order placed! Ticket: {ticket} | "
            f"{direction} {symbol} {lot_size} lots"
        )
        self._say(
            f"Trade placed, sir. "
            f"{dir_word.capitalize()} {symbol} "
            f"with {lot_size} lots. "
            f"Stop loss at {sl_price:.5f}. "
            f"First target at {tp1:.5f}. "
            f"Final target at {tp_price:.5f}. "
            f"Risking {risk_result['risk_amount']:.2f} "
            f"which is {risk_percent}% of your account."
        )

        return {
            "success":     True,
            "ticket":      ticket,
            "symbol":      symbol,
            "direction":   direction,
            "lot_size":    lot_size,
            "entry":       entry,
            "stop_loss":   sl_price,
            "tp1":         tp1,
            "tp2":         tp_price,
            "risk_amount": risk_result["risk_amount"],
            "sl_pips":     risk_result["sl_pips"],
            "placed_at":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }


# ─────────────────────────────────────────────────────────────
# TRADE MANAGER
# ─────────────────────────────────────────────────────────────

class TradeManager:
    """
    Manages open trades:
      - Monitors price vs TP1/TP2
      - Partial close at TP1 (50%)
      - Move SL to BE after TP1
      - Trailing stop
    """

    def __init__(self, mt5, player=None, speak=None):
        self._mt5     = mt5
        self.player   = player
        self.speak    = speak
        self._sym     = SymbolManager(mt5, player)
        self._managed = {}   # ticket → management state
        self._running = False
        self._thread  = None

    def _log(self, msg: str):
        print(f"[MT5-Mgr] {msg}")
        if self.player:
            self.player.write_log(f"[MT5] {msg}")

    def _say(self, msg: str):
        if self.speak:
            self.speak(msg)

    def register_trade(
        self,
        ticket:    int,
        tp1:       float,
        tp2:       float,
        entry:     float,
        direction: str,
        symbol:    str,
        atr:       float = None,
    ):
        """Register a trade for management."""
        self._managed[ticket] = {
            "ticket":       ticket,
            "symbol":       symbol,
            "direction":    direction,
            "entry":        entry,
            "tp1":          tp1,
            "tp2":          tp2,
            "atr":          atr or 0,
            "tp1_hit":      False,
            "sl_at_be":     False,
            "trailing":     False,
            "partial_done": False,
        }
        self._log(f"Registered trade #{ticket} for management")

    def _get_position(self, ticket: int):
        """Get position by ticket."""
        positions = self._mt5.positions_get(ticket=ticket)
        if positions and len(positions) > 0:
            return positions[0]
        return None

    def _partial_close(
        self,
        position,
        percent: float = 50.0,
    ) -> bool:
        """
        Close a percentage of a position.
        Default: close 50% at TP1.
        """
        mt5      = self._mt5
        symbol   = position.symbol
        ticket   = position.ticket
        volume   = position.volume
        close_vol = round(volume * (percent / 100), 2)

        # Get symbol min lot
        sym_info = mt5.symbol_info(symbol)
        if sym_info:
            close_vol = max(close_vol, sym_info.volume_min)
            close_vol = min(close_vol, volume)
            step      = sym_info.volume_step
            close_vol = round(round(close_vol / step) * step, 2)

        if close_vol <= 0 or close_vol > volume:
            return False

        # Determine close price
        if position.type == mt5.POSITION_TYPE_BUY:
            price    = mt5.symbol_info_tick(symbol).bid
            order_type = mt5.ORDER_TYPE_SELL
        else:
            price    = mt5.symbol_info_tick(symbol).ask
            order_type = mt5.ORDER_TYPE_BUY

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       close_vol,
            "type":         order_type,
            "position":     ticket,
            "price":        price,
            "deviation":    SLIPPAGE,
            "magic":        DEFAULT_MAGIC,
            "comment":      "JARVIS-TP1-partial",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            self._log(f"✅ Partial close #{ticket}: {close_vol} lots at {price}")
            return True

        self._log(
            f"Partial close failed #{ticket}: "
            f"{result.comment if result else 'unknown'}"
        )
        return False

    def _move_sl_to_be(
        self,
        position,
        entry:     float,
        direction: str,
    ) -> bool:
        """Move stop loss to breakeven + small buffer."""
        mt5    = self._mt5
        symbol = position.symbol
        ticket = position.ticket
        point  = mt5.symbol_info(symbol).point if mt5.symbol_info(symbol) else 0.00001

        if direction == "BULLISH":
            new_sl = entry + (BE_BUFFER_POINTS * point)
        else:
            new_sl = entry - (BE_BUFFER_POINTS * point)

        new_sl = self._sym.normalize_price(symbol, new_sl)

        # Check SL is better than current
        if direction == "BULLISH" and new_sl <= position.sl:
            return False
        if direction == "BEARISH" and new_sl >= position.sl:
            return False

        request = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "symbol":   symbol,
            "sl":       new_sl,
            "tp":       position.tp,
            "position": ticket,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            self._log(f"✅ SL moved to BE #{ticket}: {new_sl:.5f}")
            return True

        return False

    def _update_trailing_stop(
        self,
        position,
        direction: str,
        atr:       float,
    ) -> bool:
        """
        Update trailing stop based on ATR.
        Trail = current price - ATR * multiplier (for longs)
        Trail = current price + ATR * multiplier (for shorts)
        """
        mt5    = self._mt5
        symbol = position.symbol
        ticket = position.ticket
        tick   = mt5.symbol_info_tick(symbol)

        if not tick:
            return False

        if direction == "BULLISH":
            trail_sl = tick.bid - (atr * TRAIL_ATR_MULT)
            if trail_sl <= position.sl:
                return False   # No improvement
        else:
            trail_sl = tick.ask + (atr * TRAIL_ATR_MULT)
            if trail_sl >= position.sl:
                return False

        trail_sl = self._sym.normalize_price(symbol, trail_sl)

        request = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "symbol":   symbol,
            "sl":       trail_sl,
            "tp":       position.tp,
            "position": ticket,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            self._log(f"Trailing SL updated #{ticket}: {trail_sl:.5f}")
            return True

        return False

    def _manage_position(self, ticket: int):
        """
        Run management logic for one trade.
        Called every MONITOR_INTERVAL seconds.
        """
        state    = self._managed.get(ticket)
        if not state:
            return

        position = self._get_position(ticket)
        if not position:
            # Trade closed
            self._log(f"Trade #{ticket} closed — removing from manager")
            del self._managed[ticket]
            return

        mt5       = self._mt5
        symbol    = state["symbol"]
        direction = state["direction"]
        entry     = state["entry"]
        tp1       = state["tp1"]
        atr       = state["atr"]

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return

        current = tick.bid if direction == "BULLISH" else tick.ask

        # ── TP1 Hit Check ─────────────────────────
        if not state["tp1_hit"]:
            tp1_hit = (
                (direction == "BULLISH" and current >= tp1) or
                (direction == "BEARISH" and current <= tp1)
            )

            if tp1_hit:
                state["tp1_hit"] = True
                self._log(f"TP1 hit #{ticket} @ {current:.5f}")
                self._say(
                    f"Sir, first target hit on ticket {ticket}. "
                    f"Closing 50% and moving stop to breakeven."
                )

                # Partial close 50%
                if not state["partial_done"]:
                    done = self._partial_close(position, 50.0)
                    state["partial_done"] = done

                # Move SL to BE
                if not state["sl_at_be"]:
                    done = self._move_sl_to_be(position, entry, direction)
                    state["sl_at_be"] = done

                # Enable trailing
                state["trailing"] = True

        # ── Trailing Stop ─────────────────────────
        if state["tp1_hit"] and state["trailing"] and atr > 0:
            # Refresh position after partial close
            position = self._get_position(ticket)
            if position:
                self._update_trailing_stop(position, direction, atr)

    def start_monitoring(self):
        """Start background trade monitoring thread."""
        if self._running:
            return

        self._running = True
        self._thread  = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
        )
        self._thread.start()
        self._log("Trade monitor started")

    def stop_monitoring(self):
        """Stop background monitoring."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        self._log("Trade monitor stopped")

    def _monitor_loop(self):
        """Background loop — runs every MONITOR_INTERVAL seconds."""
        while self._running:
            tickets = list(self._managed.keys())
            for ticket in tickets:
                try:
                    self._manage_position(ticket)
                except Exception as e:
                    self._log(f"Monitor error #{ticket}: {e}")

            time.sleep(MONITOR_INTERVAL)


# ─────────────────────────────────────────────────────────────
# POSITIONS READER
# ─────────────────────────────────────────────────────────────

class PositionsReader:
    """Read and format open positions."""

    def __init__(self, mt5, player=None):
        self._mt5   = mt5
        self.player = player

    def get_all_positions(self) -> list[dict]:
        """Get all open positions."""
        positions = self._mt5.positions_get()
        if not positions:
            return []

        result = []
        for p in positions:
            result.append({
                "ticket":     p.ticket,
                "symbol":     p.symbol,
                "type":       "BUY" if p.type == 0 else "SELL",
                "volume":     p.volume,
                "entry":      p.price_open,
                "current":    p.price_current,
                "sl":         p.sl,
                "tp":         p.tp,
                "profit":     round(p.profit, 2),
                "swap":       round(p.swap, 2),
                "magic":      p.magic,
                "comment":    p.comment,
                "time":       datetime.fromtimestamp(p.time).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "is_jarvis":  p.magic == DEFAULT_MAGIC,
            })

        return result

    def get_jarvis_positions(self) -> list[dict]:
        """Get only JARVIS-placed positions."""
        return [
            p for p in self.get_all_positions()
            if p["is_jarvis"]
        ]

    def format_positions(self) -> str:
        """Format positions for display."""
        positions = self.get_all_positions()
        if not positions:
            return "No open positions."

        lines = [
            "📊 OPEN POSITIONS",
            "─" * 50,
        ]

        total_profit = 0
        for p in positions:
            tag  = " 🤖" if p["is_jarvis"] else ""
            pnl  = p["profit"]
            sign = "+" if pnl >= 0 else ""
            total_profit += pnl

            lines += [
                f"#{p['ticket']} {p['symbol']} {p['type']}{tag}",
                f"  Lots:   {p['volume']}",
                f"  Entry:  {p['entry']:.5f}",
                f"  Price:  {p['current']:.5f}",
                f"  SL:     {p['sl']:.5f}",
                f"  TP:     {p['tp']:.5f}",
                f"  P&L:    {sign}{pnl:.2f}",
                f"  Time:   {p['time']}",
                "",
            ]

        sign = "+" if total_profit >= 0 else ""
        lines += [
            "─" * 50,
            f"Total P&L: {sign}{total_profit:.2f}",
        ]

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# MAIN MT5 EXECUTOR
# ─────────────────────────────────────────────────────────────

class MT5Executor:
    """
    Main MT5 interface — combines all components.
    Used by the ICT engine and trading_agent.
    """

    def __init__(self, player=None, speak=None):
        self.player    = player
        self.speak     = speak
        self._conn     = MT5Connector(player=player)
        self._mt5      = None
        self._order    = None
        self._manager  = None
        self._reader   = None
        self.connected = False

    def _log(self, msg: str):
        print(f"[MT5-Exec] {msg}")
        if self.player:
            self.player.write_log(f"[MT5] {msg}")

    def connect(
        self,
        login:    int = None,
        password: str = None,
        server:   str = None,
        path:     str = None,
    ) -> dict:
        """Connect to MT5 broker."""
        self._conn.path = path
        result = self._conn.connect(login, password, server)

        if result["success"]:
            self._mt5     = self._conn._mt5
            self._order   = OrderExecutor(self._mt5, self.player, self.speak)
            self._manager = TradeManager(self._mt5,  self.player, self.speak)
            self._reader  = PositionsReader(self._mt5, self.player)
            self.connected = True
            self._manager.start_monitoring()

        return result

    def disconnect(self):
        """Disconnect from MT5."""
        if self._manager:
            self._manager.stop_monitoring()
        self._conn.disconnect()
        self.connected = False

    def place_trade(
        self,
        setup:        dict,
        risk_percent: float = 1.0,
    ) -> dict:
        """
        Place a trade from an ICT setup dict.
        Automatically registers for trade management.

        Args:
            setup:        ICT engine setup dict
            risk_percent: Risk per trade (default 1%)

        Returns:
            Order result dict
        """
        if not self.connected:
            return {
                "success": False,
                "message": "Not connected to MT5",
            }

        symbol    = setup.get("symbol", "")
        direction = setup.get("direction", "")
        sl        = setup.get("stop_loss", 0)
        tp1       = setup.get("tp1",       0)
        tp2       = setup.get("tp2",       0)
        atr       = setup.get("atr",       0)

        if not symbol or not direction or not sl or not tp2:
            return {
                "success": False,
                "message": "Invalid setup — missing symbol/direction/SL/TP",
            }

        # Place the order
        result = self._order.place_market_order(
            symbol       = symbol,
            direction    = direction,
            stop_loss    = sl,
            tp1          = tp1,
            tp2          = tp2,
            risk_percent = risk_percent,
        )

        # Register for management
        if result.get("success"):
            ticket = result["ticket"]
            entry  = result["entry"]
            self._manager.register_trade(
                ticket    = ticket,
                tp1       = tp1,
                tp2       = tp2,
                entry     = entry,
                direction = direction,
                symbol    = symbol,
                atr       = atr,
            )
            self._log(
                f"Trade #{ticket} registered for auto-management"
            )

        return result

    def close_trade(
        self,
        ticket: int,
        percent: float = 100.0,
    ) -> dict:
        """Close a trade fully or partially."""
        if not self.connected:
            return {"success": False, "message": "Not connected"}

        position = self._manager._get_position(ticket)
        if not position:
            return {
                "success": False,
                "message": f"Position #{ticket} not found",
            }

        if percent >= 100:
            # Full close
            mt5    = self._mt5
            symbol = position.symbol
            tick   = mt5.symbol_info_tick(symbol)

            if position.type == mt5.POSITION_TYPE_BUY:
                price    = tick.bid
                order_tp = mt5.ORDER_TYPE_SELL
            else:
                price    = tick.ask
                order_tp = mt5.ORDER_TYPE_BUY

            request = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       symbol,
                "volume":       position.volume,
                "type":         order_tp,
                "position":     ticket,
                "price":        price,
                "deviation":    SLIPPAGE,
                "magic":        DEFAULT_MAGIC,
                "comment":      "JARVIS-close",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                if ticket in self._manager._managed:
                    del self._manager._managed[ticket]
                self._log(f"✅ Trade #{ticket} fully closed")
                return {
                    "success": True,
                    "message": f"Trade #{ticket} closed",
                }
            return {
                "success": False,
                "message": result.comment if result else "Close failed",
            }

        else:
            # Partial close
            success = self._manager._partial_close(position, percent)
            return {
                "success": success,
                "message": (
                    f"Partial close {percent}% done"
                    if success else "Partial close failed"
                ),
            }

    def get_account_info(self) -> dict:
        """Get account information."""
        if not self.connected:
            return {"error": "Not connected"}
        return self._conn.get_account_info()

    def get_positions(self) -> str:
        """Get formatted positions."""
        if not self.connected:
            return "Not connected to MT5"
        return self._reader.format_positions()

    def get_positions_raw(self) -> list[dict]:
        """Get raw positions list."""
        if not self.connected:
            return []
        return self._reader.get_all_positions()

    def modify_sl_tp(
        self,
        ticket:    int,
        new_sl:    float = None,
        new_tp:    float = None,
    ) -> dict:
        """Manually modify SL or TP on a position."""
        if not self.connected:
            return {"success": False, "message": "Not connected"}

        position = self._manager._get_position(ticket)
        if not position:
            return {
                "success": False,
                "message": f"Position #{ticket} not found",
            }

        mt5    = self._mt5
        sym    = SymbolManager(mt5, self.player)

        sl = sym.normalize_price(
            position.symbol,
            new_sl if new_sl is not None else position.sl,
        )
        tp = sym.normalize_price(
            position.symbol,
            new_tp if new_tp is not None else position.tp,
        )

        request = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "symbol":   position.symbol,
            "sl":       sl,
            "tp":       tp,
            "position": ticket,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            self._log(f"SL/TP modified #{ticket}: SL={sl} TP={tp}")
            return {
                "success": True,
                "message": f"Modified #{ticket}: SL={sl:.5f} TP={tp:.5f}",
            }

        return {
            "success": False,
            "message": result.comment if result else "Modify failed",
        }


# ─────────────────────────────────────────────────────────────
# CREDENTIAL STORE
# ─────────────────────────────────────────────────────────────

def save_mt5_credentials(
    login:    int,
    password: str,
    server:   str,
    broker:   str = "default",
) -> bool:
    """
    Save MT5 credentials securely using JARVIS
    credential manager.
    """
    try:
        from core.credential_manager import save_credential
        save_credential(f"mt5_{broker}", "login",    str(login))
        save_credential(f"mt5_{broker}", "password", password)
        save_credential(f"mt5_{broker}", "server",   server)
        print(f"[MT5] Credentials saved for broker: {broker}")
        return True
    except Exception as e:
        print(f"[MT5] Failed to save credentials: {e}")
        return False


def load_mt5_credentials(broker: str = "default") -> dict:
    """
    Load MT5 credentials from JARVIS credential manager.
    """
    try:
        from core.credential_manager import get_credential
        login    = get_credential(f"mt5_{broker}", "login")
        password = get_credential(f"mt5_{broker}", "password")
        server   = get_credential(f"mt5_{broker}", "server")

        if login and password and server:
            return {
                "login":    int(login),
                "password": password,
                "server":   server,
            }
    except Exception as e:
        print(f"[MT5] Failed to load credentials: {e}")

    return {}


# ─────────────────────────────────────────────────────────────
# QUICK CONNECT HELPER
# ─────────────────────────────────────────────────────────────

def get_executor(
    player = None,
    speak  = None,
    broker: str = "default",
    login:    int = None,
    password: str = None,
    server:   str = None,
) -> tuple[MT5Executor, dict]:
    """
    Quick connect helper.
    Loads saved credentials or uses provided ones.

    Returns:
        (executor, connect_result)
    """
    executor = MT5Executor(player=player, speak=speak)

    # Load saved credentials
    creds = load_mt5_credentials(broker)

    # Override with provided
    if login:    creds["login"]    = login
    if password: creds["password"] = password
    if server:   creds["server"]   = server

    if not creds:
        return executor, {
            "success": False,
            "message": (
                "No MT5 credentials found. "
                "Please provide login, password, and server."
            ),
        }

    result = executor.connect(**creds)
    return executor, result