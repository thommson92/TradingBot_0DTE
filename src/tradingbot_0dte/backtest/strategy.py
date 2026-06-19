"""Strike-Wahl und Exit-Logik fuer nackten Short Put und Put-Spread."""
from __future__ import annotations

import datetime as dt
from typing import Optional, Tuple

import pandas as pd

from .fills import buy_fill, exit_fill, sell_fill
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


def pick_long_leg(snapshot: pd.DataFrame, short_strike: float, width: float) -> Optional[pd.Series]:
    """Waehlt die Long-Put-Leg eines Spreads: den Strike (ausser short_strike), der
    short_strike - width am naechsten liegt. Kein exakter Match noetig, da SPX-
    Strikeabstaende nicht ueberall gleich breit sind."""
    candidates = snapshot[(snapshot["right"] == "PUT") & (snapshot["strike"] != short_strike)]
    if candidates.empty:
        return None
    target = short_strike - width
    idx = (candidates["strike"] - target).abs().idxmin()
    return candidates.loc[idx]


def _check_thresholds(
    entry_price: float,
    current_price: float,
    now: dt.time,
    params: StrategyParams,
    cutoff_time: Optional[dt.time],
) -> Optional[Tuple[str, float]]:
    """Reine Schwellenwert-Logik, Prioritaet Stop-Loss -> Profit-Target -> Zeit-Exit.

    Gibt (reason, current_price) zurueck, sonst None (Position bleibt offen).
    """
    if params.stop_loss_multiplier is not None and current_price >= entry_price * params.stop_loss_multiplier:
        return "stop_loss", current_price
    if params.profit_target_pct is not None and current_price <= entry_price * params.profit_target_pct:
        return "profit_target", current_price
    if cutoff_time is not None and now >= cutoff_time:
        return "time_exit", current_price
    return None


def check_exit(
    entry_price: float,
    bar: pd.Series,
    params: StrategyParams,
    cutoff_time: Optional[dt.time],
) -> Optional[Tuple[str, float]]:
    """Exit-Check fuer den nackten Short Put: current_price = Rueckkaufkosten."""
    price = exit_fill(bar["bid"], bar["ask"], params.slippage_pct_of_spread)
    return _check_thresholds(entry_price, price, bar["timestamp"].time(), params, cutoff_time)


def check_exit_spread(
    entry_credit: float,
    short_bar: pd.Series,
    long_bar: pd.Series,
    params: StrategyParams,
    cutoff_time: Optional[dt.time],
) -> Optional[Tuple[str, float]]:
    """Exit-Check fuer den Put-Spread: current_price = Kosten, um den Spread zu
    schliessen (Short-Leg zurueckkaufen, Long-Leg verkaufen)."""
    cost = buy_fill(short_bar["bid"], short_bar["ask"], params.slippage_pct_of_spread) - \
        sell_fill(long_bar["bid"], long_bar["ask"], params.slippage_pct_of_spread)
    return _check_thresholds(entry_credit, cost, short_bar["timestamp"].time(), params, cutoff_time)
