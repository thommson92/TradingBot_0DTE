"""Event-getriebene Backtest-Engine: nackter Short Put oder Put-Spread auf SPXW-0DTE-Daten."""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass
from typing import List, Optional, Tuple

import pandas as pd
from tqdm import tqdm

from ..config import Config
from ..storage import MarketData
from .fills import LEGS_NAKED_PUT, LEGS_PUT_SPREAD, buy_fill, entry_fill, exit_fill, sell_fill, trade_pnl
from .params import StrategyParams
from .strategy import check_exit, check_exit_spread, pick_long_leg, pick_strike
from .trade import Trade

TRADE_COLUMNS = [
    "date", "entry_ts", "exit_ts", "strike", "long_strike", "entry_delta",
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


@dataclass
class NakedSetup:
    """Entry-Seite des nackten Short Put -- haengt NICHT von der Exit-Regel ab und
    wird daher fuer mehrere Exit-Varianten desselben Entrys einmal aufgebaut
    (Schritt 6: gelernte Exits ueber ein erweitertes Kandidatenraster)."""
    entry_ts: object
    strike: float
    entry_delta: float
    entry_price: float
    series: pd.DataFrame


def _naked_setup(day_df: pd.DataFrame, snapshot: pd.DataFrame, params: StrategyParams) -> Optional[NakedSetup]:
    """Waehlt den Short-Strike, berechnet den Entry-Fill und schneidet die
    Strike-Zeitreihe ab Entry zu -- der teure Tagesfilter passiert hier nur einmal."""
    row = pick_strike(snapshot, params.target_delta, params.delta_low, params.delta_high)
    if row is None:
        return None
    entry_ts = row["timestamp"]
    strike = row["strike"]
    series = day_df[(day_df["strike"] == strike) & (day_df["timestamp"] >= entry_ts)].sort_values("timestamp")
    return NakedSetup(
        entry_ts=entry_ts, strike=strike, entry_delta=row["delta"],
        entry_price=entry_fill(row["bid"], row["ask"], params.slippage_pct_of_spread),
        series=series,
    )


def _naked_exit_walk(
    setup: NakedSetup, params: StrategyParams, cutoff_time: Optional[dt.time],
) -> Tuple[str, float, object]:
    """Laeuft die Strike-Zeitreihe ab und liefert (exit_reason, exit_price, exit_ts)
    fuer die gegebene Exit-Regel. Reines Wiederholen je Exit-Variante, ohne den
    Tagesfilter erneut zu zahlen."""
    for _, bar in setup.series.iterrows():
        if bar["timestamp"] == setup.entry_ts:
            continue
        result = check_exit(setup.entry_price, bar, params, cutoff_time)
        if result is not None:
            return result[0], result[1], bar["timestamp"]

    last_bar = setup.series.iloc[-1]
    exit_price = exit_fill(last_bar["bid"], last_bar["ask"], params.slippage_pct_of_spread)
    return "expiration", exit_price, last_bar["timestamp"]


def _naked_trade(setup: NakedSetup, date: int, params: StrategyParams,
                 exit_reason: str, exit_price: float, exit_ts) -> Trade:
    pnl = trade_pnl(setup.entry_price, exit_price, params.commission_per_contract_leg, legs=LEGS_NAKED_PUT)
    return Trade(
        date=date, entry_ts=setup.entry_ts, exit_ts=exit_ts, strike=setup.strike,
        entry_delta=setup.entry_delta, entry_price=setup.entry_price, exit_price=exit_price,
        exit_reason=exit_reason, pnl=pnl,
    )


def _simulate_naked_entry(
    day_df: pd.DataFrame, snapshot: pd.DataFrame, date: int,
    params: StrategyParams, cutoff_time: Optional[dt.time],
) -> Optional[Trade]:
    """Simuliert den nackten Short Put ab einem Entry-Snapshot bis zum Exit."""
    setup = _naked_setup(day_df, snapshot, params)
    if setup is None:
        return None
    exit_reason, exit_price, exit_ts = _naked_exit_walk(setup, params, cutoff_time)
    return _naked_trade(setup, date, params, exit_reason, exit_price, exit_ts)


@dataclass
class SpreadSetup:
    """Entry-Seite des Put-Spreads (exit-regel-unabhaengig, fuer mehrere Exit-Varianten)."""
    entry_ts: object
    short_strike: float
    long_strike: float
    entry_delta: float
    entry_credit: float
    bars: list  # itertuples-Liste (Timestamp + bid/ask je Leg), Dtypes erhalten


def _spread_setup(day_df: pd.DataFrame, snapshot: pd.DataFrame, params: StrategyParams) -> Optional[SpreadSetup]:
    """Waehlt Short-/Long-Leg, berechnet den Entry-Credit und merged die Leg-Reihen
    einmal -- teure Filter/Merge passieren hier nur einmal je Entry."""
    short_row = pick_strike(snapshot, params.target_delta, params.delta_low, params.delta_high)
    if short_row is None:
        return None
    long_row = pick_long_leg(snapshot, short_row["strike"], params.spread_width)
    if long_row is None:
        return None

    entry_ts = short_row["timestamp"]
    short_strike = short_row["strike"]
    long_strike = long_row["strike"]
    entry_credit = sell_fill(short_row["bid"], short_row["ask"], params.slippage_pct_of_spread) - \
        buy_fill(long_row["bid"], long_row["ask"], params.slippage_pct_of_spread)

    short_series = day_df[(day_df["strike"] == short_strike) & (day_df["timestamp"] >= entry_ts)]
    long_series = day_df[(day_df["strike"] == long_strike) & (day_df["timestamp"] >= entry_ts)]
    merged = pd.merge(
        short_series[["timestamp", "bid", "ask"]], long_series[["timestamp", "bid", "ask"]],
        on="timestamp", suffixes=("_short", "_long"),
    ).sort_values("timestamp")

    # itertuples statt iterrows: merged hat nur Timestamp- + Float-Spalten (keine
    # String-Spalte), daher zwingt iterrows/iloc die Zeile auf datetime64 und macht
    # aus NaN bid/ask (Bar ohne Quote) NaT -> die Preis-Arithmetik ergaebe NaT und
    # der Schwellenwert-Vergleich (NaT >= float) wuerfe einen TypeError. itertuples
    # erhaelt die Dtypes pro Feld (NaN bleibt float-NaN -> Vergleich liefert False).
    bars = list(merged.itertuples(index=False))
    return SpreadSetup(
        entry_ts=entry_ts, short_strike=short_strike, long_strike=long_strike,
        entry_delta=short_row["delta"], entry_credit=entry_credit, bars=bars,
    )


def _spread_exit_walk(
    setup: SpreadSetup, params: StrategyParams, cutoff_time: Optional[dt.time],
) -> Tuple[str, float, object]:
    """Laeuft die gemergte Spread-Zeitreihe ab und liefert (reason, exit_cost, ts)."""
    for r in setup.bars:
        if r.timestamp == setup.entry_ts:
            continue
        short_bar = {"timestamp": r.timestamp, "bid": r.bid_short, "ask": r.ask_short}
        long_bar = {"timestamp": r.timestamp, "bid": r.bid_long, "ask": r.ask_long}
        result = check_exit_spread(setup.entry_credit, short_bar, long_bar, params, cutoff_time)
        if result is not None:
            return result[0], result[1], r.timestamp

    last_row = setup.bars[-1]
    exit_cost = buy_fill(last_row.bid_short, last_row.ask_short, params.slippage_pct_of_spread) - \
        sell_fill(last_row.bid_long, last_row.ask_long, params.slippage_pct_of_spread)
    return "expiration", exit_cost, last_row.timestamp


def _spread_trade(setup: SpreadSetup, date: int, params: StrategyParams,
                  exit_reason: str, exit_cost: float, exit_ts) -> Trade:
    pnl = trade_pnl(setup.entry_credit, exit_cost, params.commission_per_contract_leg, legs=LEGS_PUT_SPREAD)
    return Trade(
        date=date, entry_ts=setup.entry_ts, exit_ts=exit_ts, strike=setup.short_strike,
        long_strike=setup.long_strike, entry_delta=setup.entry_delta,
        entry_price=setup.entry_credit, exit_price=exit_cost, exit_reason=exit_reason, pnl=pnl,
    )


def _simulate_spread_entry(
    day_df: pd.DataFrame, snapshot: pd.DataFrame, date: int,
    params: StrategyParams, cutoff_time: Optional[dt.time],
) -> Optional[Trade]:
    """Simuliert den Put-Spread (Short-Leg per Ziel-Delta, Long-Leg per Breite)
    ab einem Entry-Snapshot bis zum Exit der Spread-Position."""
    setup = _spread_setup(day_df, snapshot, params)
    if setup is None:
        return None
    exit_reason, exit_cost, exit_ts = _spread_exit_walk(setup, params, cutoff_time)
    return _spread_trade(setup, date, params, exit_reason, exit_cost, exit_ts)


def run_day(day_df: pd.DataFrame, date: int, params: StrategyParams) -> List[Trade]:
    """Simuliert einen Handelstag: jede Entry-Zeit wird unabhaengig bis zum Exit
    durchsimuliert, bevor die naechste Entry-Zeit geprueft wird (sequentiell,
    daher reicht ein einfacher exit_ts-Vergleich fuer den Concurrency-Check).
    spread_type steuert, ob nackter Put oder Put-Spread simuliert wird."""
    if day_df.empty:
        return []

    trades: List[Trade] = []
    cutoff_time = _cutoff_time(day_df, params.time_exit_before_close_min)
    simulate = _simulate_spread_entry if params.spread_type == "put_spread" else _simulate_naked_entry

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

        trade = simulate(day_df, snapshot, date, params, cutoff_time)
        if trade is None:
            continue
        trades.append(trade)

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
