"""Strike-Wahl und Exit-Logik fuer den nackten Short Put."""
from __future__ import annotations

import datetime as dt
from typing import Optional, Tuple

import pandas as pd

from .fills import exit_fill
from .params import StrategyParams


def pick_strike(snapshot: pd.DataFrame, target_delta: float, delta_low: float, delta_high: float) -> Optional[pd.Series]:
    """Waehlt unter den Puts im Band [delta_low, delta_high] den Strike mit |Delta| am naechsten zu target_delta."""
    band = snapshot[
        (snapshot["right"] == "PUT")
        & (snapshot["delta"].abs() >= delta_low)
        & (snapshot["delta"].abs() <= delta_high)
    ]
    if band.empty:
        return None
    idx = (band["delta"].abs() - target_delta).abs().idxmin()
    return band.loc[idx]


def check_exit(
    entry_price: float,
    bar: pd.Series,
    params: StrategyParams,
    cutoff_time: Optional[dt.time],
) -> Optional[Tuple[str, float]]:
    """Prueft Exit-Bedingungen in Prioritaet Stop-Loss -> Profit-Target -> Zeit-Exit.

    Gibt (reason, exit_price) zurueck, sonst None (Position bleibt offen).
    """
    price = exit_fill(bar["bid"], bar["ask"], params.slippage_pct_of_spread)

    if params.stop_loss_multiplier is not None and price >= entry_price * params.stop_loss_multiplier:
        return "stop_loss", price
    if params.profit_target_pct is not None and price <= entry_price * params.profit_target_pct:
        return "profit_target", price
    if cutoff_time is not None and bar["timestamp"].time() >= cutoff_time:
        return "time_exit", price
    return None
