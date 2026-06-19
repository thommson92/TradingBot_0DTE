"""Baut die ML-Trainingstabelle: pro Handelstag x Kandidat eine Zeile mit
Features (Marktzustand zum Entry) + Label (realer Trade-Ausgang via Engine).

Parallelisiert ueber TAGE: jeder Worker-Prozess oeffnet eine eigene
MarketData-Verbindung und verarbeitet die ihm zugewiesenen Tage gegen das
gemeinsame Kandidatenraster -- jeder Tag wird also genau einmal von der Platte
gelesen (nicht n_jobs-mal). Ergebnis wird als Parquet gecacht.

`prev_close` (fuer das gap_open-Feature) ist eine tagesuebergreifende Information
und wird daher im Hauptprozess per DuckDB-Vorabscan einmal bestimmt und den
Workern mitgegeben.
"""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm

from ..backtest.engine import _snapshot, _yyyymmdd
from ..backtest.strategy import pick_strike
from ..config import Config
from ..storage import MarketData
from .features import FEATURE_COLUMNS, candidate_features, market_features
from .labels import Candidate, ExitRule, simulate_candidate

META_COLUMNS = ["date", "entry_time", "target_delta", "spread_type", "spread_width"]
LABEL_COLUMNS = [
    "tradable", "pnl", "is_win", "exit_reason",
    "strike", "long_strike", "entry_price", "exit_price",
]
DATASET_COLUMNS = META_COLUMNS + FEATURE_COLUMNS + LABEL_COLUMNS

# Spread-Spezifikation: ("naked", None) oder ("put_spread", Breite).
SpreadSpec = Tuple[str, Optional[float]]


@dataclass
class CandidateGrid:
    """Das Kandidatenraster, ueber das pro Tag eine Trainingszeile je Kombination
    erzeugt wird (kartesisches Produkt der drei Achsen)."""
    entry_times: List[str]
    target_deltas: List[float]
    spreads: List[SpreadSpec]
    delta_low: float = 0.01
    delta_high: float = 0.50

    def expand(self) -> List[Candidate]:
        out: List[Candidate] = []
        for et in self.entry_times:
            for td in self.target_deltas:
                for stype, width in self.spreads:
                    out.append(Candidate(
                        entry_time=et, target_delta=td, spread_type=stype,
                        spread_width=width, delta_low=self.delta_low, delta_high=self.delta_high,
                    ))
        return out


def default_entry_times(start: str = "09:35:00", end: str = "15:55:00", step_min: int = 15) -> List[str]:
    """Entry-Zeit-Raster in step_min-Schritten zwischen start und end (inkl.)."""
    t = dt.time.fromisoformat(start)
    end_t = dt.time.fromisoformat(end)
    cur = dt.datetime.combine(dt.date(2000, 1, 1), t)
    end_dt = dt.datetime.combine(dt.date(2000, 1, 1), end_t)
    times: List[str] = []
    while cur <= end_dt:
        times.append(cur.time().strftime("%H:%M:%S"))
        cur += dt.timedelta(minutes=step_min)
    return times


def _empty_label() -> dict:
    return {
        "tradable": 0, "pnl": np.nan, "is_win": np.nan, "exit_reason": None,
        "strike": np.nan, "long_strike": np.nan, "entry_price": np.nan, "exit_price": np.nan,
    }


def _label_from_trade(trade) -> dict:
    return {
        "tradable": 1,
        "pnl": float(trade.pnl),
        "is_win": 1.0 if trade.pnl > 0 else 0.0,
        "exit_reason": trade.exit_reason,
        "strike": float(trade.strike),
        "long_strike": float(trade.long_strike) if trade.long_strike is not None else np.nan,
        "entry_price": float(trade.entry_price),
        "exit_price": float(trade.exit_price),
    }


def build_day_rows(
    day_df: pd.DataFrame,
    date: int,
    candidates: List[Candidate],
    exit_rule: ExitRule,
    prev_close: Optional[float],
) -> List[dict]:
    """Erzeugt alle Trainingszeilen eines Tages.

    Die market_features sind kandidatenunabhaengig und werden je Entry-Zeit nur
    EINMAL berechnet (Kandidaten desselben Bars teilen sie). Strike-Wahl (Features)
    und Label-Simulation nutzen dieselbe pick_strike-Logik -> selber Strike.
    """
    if day_df.empty:
        return []

    by_time: Dict[str, List[Candidate]] = {}
    for c in candidates:
        by_time.setdefault(c.entry_time, []).append(c)

    rows: List[dict] = []
    for entry_time, cands in by_time.items():
        snapshot = _snapshot(day_df, entry_time)
        if snapshot.empty:
            continue
        entry_ts = snapshot["timestamp"].iloc[0]
        mf = market_features(day_df, snapshot, entry_ts, prev_close)

        for c in cands:
            entry_row = pick_strike(snapshot, c.target_delta, c.delta_low, c.delta_high)
            cf = candidate_features(entry_row, c, mf["underlying"])
            trade, _ = simulate_candidate(day_df, date, c, exit_rule)

            row = {
                "date": date,
                "entry_time": entry_time,
                "target_delta": c.target_delta,
                "spread_type": c.spread_type,
                "spread_width": c.spread_width if c.spread_width is not None else np.nan,
            }
            row.update(mf)
            row.update(cf)
            # NaN-P&L (z. B. Expiration-Fallback auf einem Bar ohne Quote) als nicht
            # handelbar werten -> kein fehletikettiertes Label im Training.
            if trade is not None and np.isfinite(trade.pnl):
                row.update(_label_from_trade(trade))
            else:
                row.update(_empty_label())
            rows.append(row)
    return rows


# --- Parallelisierung ueber Tage --------------------------------------------

_WORKER: dict = {}


def _init_worker(cfg: Config, candidates: List[Candidate], exit_rule: ExitRule,
                 prev_close_map: Dict[int, Optional[float]]) -> None:
    global _WORKER
    _WORKER = {
        "md": MarketData(cfg),
        "candidates": candidates,
        "exit_rule": exit_rule,
        "prev_close": prev_close_map,
    }


def _process_day(date: int) -> List[dict]:
    md: MarketData = _WORKER["md"]
    day_df = md.load_day(date)
    return build_day_rows(
        day_df, date, _WORKER["candidates"], _WORKER["exit_rule"],
        _WORKER["prev_close"].get(date),
    )


def _close_underlying_map(md: MarketData, dates: List[int]) -> Dict[int, float]:
    """Schlusskurs (letzter Nicht-NaN underlying_price) je Tag -- ein DuckDB-Scan
    nur ueber die underlying_price/timestamp-Spalten (Parquet ist spaltenweise)."""
    files = [str(md.root_dir / ("%d.parquet" % d)) for d in dates]
    listed = ", ".join("'%s'" % f for f in files)
    sql = (
        "SELECT date, arg_max(underlying_price, timestamp) AS close_u "
        "FROM read_parquet([%s]) WHERE underlying_price IS NOT NULL "
        "GROUP BY date" % listed
    )
    df = md.con.execute(sql).df()
    return {int(d): float(u) for d, u in zip(df["date"], df["close_u"])}


def _prev_close_map(close_map: Dict[int, float], dates: List[int]) -> Dict[int, Optional[float]]:
    """Ordnet jedem Tag den Schlusskurs des VORHERIGEN Handelstages zu (gap_open)."""
    out: Dict[int, Optional[float]] = {}
    for i, d in enumerate(dates):
        out[d] = close_map.get(dates[i - 1]) if i > 0 else None
    return out


def build_dataset(
    cfg: Config,
    grid: CandidateGrid,
    exit_rule: Optional[ExitRule] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    n_jobs: Optional[int] = None,
) -> pd.DataFrame:
    """Baut die komplette Trainingstabelle ueber den (gefilterten) Zeitraum."""
    exit_rule = exit_rule or ExitRule()
    candidates = grid.expand()

    md = MarketData(cfg)
    try:
        dates = sorted(md.available_dates())
        if start:
            s = _yyyymmdd(start)
            dates = [d for d in dates if d >= s]
        if end:
            e = _yyyymmdd(end)
            dates = [d for d in dates if d <= e]
        close_map = _close_underlying_map(md, dates)
    finally:
        md.close()

    prev_close_map = _prev_close_map(close_map, dates)

    with ProcessPoolExecutor(
        max_workers=n_jobs, initializer=_init_worker,
        initargs=(cfg, candidates, exit_rule, prev_close_map),
    ) as ex:
        results = list(tqdm(
            ex.map(_process_day, dates), total=len(dates),
            desc="ML-Dataset", unit="Tag",
        ))

    rows = [r for day_rows in results for r in day_rows]
    if not rows:
        return pd.DataFrame(columns=DATASET_COLUMNS)
    return pd.DataFrame(rows)[DATASET_COLUMNS]


def save_dataset(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def load_dataset(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)
