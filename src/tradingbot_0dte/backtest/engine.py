"""Event-getriebene Backtest-Engine: nackter Short Put auf SPXW-0DTE-Daten."""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict
from typing import List, Optional

import pandas as pd
from tqdm import tqdm

from ..config import Config
from ..storage import MarketData
from .fills import entry_fill, exit_fill, trade_pnl
from .params import StrategyParams
from .strategy import check_exit, pick_strike
from .trade import Trade

TRADE_COLUMNS = [
    "date", "entry_ts", "exit_ts", "strike", "entry_delta",
    "entry_price", "exit_price", "exit_reason", "pnl",
]


def _yyyymmdd(d) -> int:
    return int(str(d).replace("-", ""))


def _snapshot(day_df: pd.DataFrame, time_str: str) -> pd.DataFrame:
    """Optionskette zum naechsten Bar <= time_str (analog zu MarketData.chain_at,
    aber auf dem bereits geladenen Tages-DataFrame -> kein erneuter Parquet-Read)."""
    t = dt.time.fromisoformat(time_str)
    mask = day_df["timestamp"].dt.time <= t
    if not mask.any():
        return day_df.iloc[0:0]
    snap_ts = day_df.loc[mask, "timestamp"].max()
    return day_df[day_df["timestamp"] == snap_ts]


def _cutoff_time(day_df: pd.DataFrame, minutes_before_close: Optional[int]) -> Optional[dt.time]:
    if minutes_before_close is None:
        return None
    close_ts = day_df["timestamp"].max()
    return (close_ts - dt.timedelta(minutes=minutes_before_close)).time()


def run_day(day_df: pd.DataFrame, date: int, params: StrategyParams) -> List[Trade]:
    """Simuliert einen Handelstag: jede Entry-Zeit wird unabhaengig bis zum Exit
    durchsimuliert, bevor die naechste Entry-Zeit geprueft wird (sequentiell,
    daher reicht ein einfacher exit_ts-Vergleich fuer den Concurrency-Check)."""
    if day_df.empty:
        return []

    trades: List[Trade] = []
    cutoff_time = _cutoff_time(day_df, params.time_exit_before_close_min)

    for entry_time_str in sorted(params.entry_times):
        if params.max_trades_per_day is not None and len(trades) >= params.max_trades_per_day:
            break

        entry_t = dt.time.fromisoformat(entry_time_str)
        open_count = sum(1 for tr in trades if tr.exit_ts.time() > entry_t)
        if open_count >= params.max_concurrent_positions:
            continue

        snapshot = _snapshot(day_df, entry_time_str)
        if snapshot.empty:
            continue
        row = pick_strike(snapshot, params.target_delta, params.delta_low, params.delta_high)
        if row is None:
            continue

        entry_ts = row["timestamp"]
        strike = row["strike"]
        entry_delta = row["delta"]
        entry_price = entry_fill(row["bid"], row["ask"], params.slippage_pct_of_spread)

        series = day_df[(day_df["strike"] == strike) & (day_df["timestamp"] >= entry_ts)].sort_values("timestamp")

        exit_reason: Optional[str] = None
        exit_price: Optional[float] = None
        exit_ts: Optional[dt.datetime] = None
        for _, bar in series.iterrows():
            if bar["timestamp"] == entry_ts:
                continue
            result = check_exit(entry_price, bar, params, cutoff_time)
            if result is not None:
                exit_reason, exit_price = result
                exit_ts = bar["timestamp"]
                break

        if exit_reason is None:
            last_bar = series.iloc[-1]
            exit_ts = last_bar["timestamp"]
            exit_price = exit_fill(last_bar["bid"], last_bar["ask"], params.slippage_pct_of_spread)
            exit_reason = "expiration"

        pnl = trade_pnl(entry_price, exit_price, params.commission_per_contract_leg)
        trades.append(Trade(
            date=date, entry_ts=entry_ts, exit_ts=exit_ts, strike=strike,
            entry_delta=entry_delta, entry_price=entry_price, exit_price=exit_price,
            exit_reason=exit_reason, pnl=pnl,
        ))

    return trades


def trades_to_df(trades: List[Trade]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(columns=TRADE_COLUMNS)
    return pd.DataFrame([asdict(t) for t in trades])[TRADE_COLUMNS]


def run(cfg: Config, params: StrategyParams, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
    md = MarketData(cfg)
    try:
        dates = sorted(md.available_dates())
        if start:
            s = _yyyymmdd(start)
            dates = [d for d in dates if d >= s]
        if end:
            e = _yyyymmdd(end)
            dates = [d for d in dates if d <= e]

        all_trades: List[Trade] = []
        for date in tqdm(dates, desc="Backtest", unit="Tag"):
            day_df = md.load_day(date)
            all_trades.extend(run_day(day_df, date, params))
    finally:
        md.close()

    return trades_to_df(all_trades)
