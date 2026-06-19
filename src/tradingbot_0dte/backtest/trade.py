"""Trade-Record fuer den Backtest."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional


@dataclass
class Trade:
    date: int  # YYYYMMDD
    entry_ts: dt.datetime
    exit_ts: dt.datetime
    strike: float  # Short-Strike (bei Spreads) bzw. der einzige Strike (naked)
    entry_delta: float
    entry_price: float
    exit_price: float
    exit_reason: str  # profit_target | stop_loss | time_exit | expiration
    pnl: float
    long_strike: Optional[float] = None  # nur bei put_spread gesetzt
