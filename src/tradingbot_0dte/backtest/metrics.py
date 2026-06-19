"""Kennzahlen aus dem Trade-Log: Win-Rate, P/L, Drawdown, Sharpe/Sortino, Profit-Faktor, Expectancy.

Annahme: Sharpe/Sortino werden auf der Tages-P&L-Reihe (Summe Trade-P&L je
Kalendertag, annualisiert mit sqrt(252)) berechnet, nicht auf prozentualen
Returns -- bei fixer Kontraktzahl=1 gibt es keine definierte Kapitalbasis.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def _empty_metrics() -> dict:
    return {
        "n_trades": 0, "win_rate": np.nan, "total_pnl": 0.0,
        "avg_pnl_per_trade": np.nan, "profit_factor": np.nan,
        "max_drawdown": 0.0, "sharpe": np.nan, "sortino": np.nan,
    }


def compute_metrics(trades_df: pd.DataFrame) -> dict:
    if trades_df.empty:
        return _empty_metrics()

    pnl = trades_df["pnl"]
    n_trades = len(trades_df)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]

    win_rate = len(wins) / n_trades
    total_pnl = float(pnl.sum())
    avg_pnl_per_trade = float(pnl.mean())
    profit_factor = float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else np.inf

    equity = trades_df.sort_values("exit_ts")["pnl"].cumsum()
    running_max = equity.cummax()
    max_drawdown = float((running_max - equity).max())

    daily_pnl = trades_df.groupby("date")["pnl"].sum()
    mean_daily = daily_pnl.mean()
    std_daily = daily_pnl.std(ddof=1)
    sharpe = float(mean_daily / std_daily * np.sqrt(TRADING_DAYS_PER_YEAR)) if std_daily and std_daily > 0 else np.nan

    downside = daily_pnl[daily_pnl < 0]
    downside_std = downside.std(ddof=1)
    sortino = (
        float(mean_daily / downside_std * np.sqrt(TRADING_DAYS_PER_YEAR))
        if downside_std and downside_std > 0 else np.nan
    )

    return {
        "n_trades": n_trades,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_pnl_per_trade": avg_pnl_per_trade,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "sortino": sortino,
    }
