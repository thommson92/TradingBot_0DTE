"""Grid-Search ueber Strategie-Parameter, parallelisiert ueber Worker-Prozesse.

Jeder Worker laedt die Tages-Daten im gewuenschten Zeitraum einmal beim Start
(Pool-initializer) in ein prozesslokales Dict und fuehrt dann alle ihm
zugewiesenen Parameter-Kombinationen gegen dieses bereits geladene Dict aus.
So wird Disk-I/O nur n_jobs-mal bezahlt, nicht einmal pro Kombination.
"""
from __future__ import annotations

import copy
import itertools
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from typing import Dict, List, Optional

import pandas as pd
from tqdm import tqdm

from ..config import Config
from ..storage import MarketData
from .engine import _yyyymmdd, run_day, trades_to_df
from .metrics import compute_metrics
from .params import StrategyParams

# Prozesslokaler Cache, von _init_worker befuellt. Liegt nach einem fork/spawn
# isoliert in jedem Worker-Prozess -- keine geteilte Mutation zwischen Workern.
_WORKER_DAYS: Dict[int, pd.DataFrame] = {}


def _init_worker(cfg: Config, start: Optional[str], end: Optional[str]) -> None:
    global _WORKER_DAYS
    md = MarketData(cfg)
    try:
        dates = sorted(md.available_dates())
        if start:
            s = _yyyymmdd(start)
            dates = [d for d in dates if d >= s]
        if end:
            e = _yyyymmdd(end)
            dates = [d for d in dates if d <= e]
        _WORKER_DAYS = {d: md.load_day(d) for d in dates}
    finally:
        md.close()


def _run_one(params: StrategyParams) -> dict:
    all_trades = []
    for date, day_df in _WORKER_DAYS.items():
        all_trades.extend(run_day(day_df, date, params))
    trades_df = trades_to_df(all_trades)
    metrics = compute_metrics(trades_df)

    row = asdict(params)
    row["entry_times"] = ",".join(params.entry_times)
    row.update(metrics)
    return row


def build_param_grid(base: StrategyParams, axes: Dict[str, List]) -> List[StrategyParams]:
    """Kartesisches Produkt ueber die angegebenen Achsen; alle anderen Felder
    bleiben bei `base`. Nicht angegebene Felder sind keine Achse, sondern fix."""
    if not axes:
        return [copy.deepcopy(base)]

    keys = list(axes.keys())
    grid = []
    for values in itertools.product(*(axes[k] for k in keys)):
        p = copy.deepcopy(base)
        for k, v in zip(keys, values):
            setattr(p, k, v)
        grid.append(p)
    return grid


def run_grid(
    cfg: Config, param_grid: List[StrategyParams],
    start: Optional[str] = None, end: Optional[str] = None,
    n_jobs: Optional[int] = None, sort_by: str = "total_pnl",
) -> pd.DataFrame:
    """Fuehrt jede Parameter-Kombination aus param_grid gegen die historisierten
    Daten aus, parallelisiert ueber Worker-Prozesse. Gibt ein Leaderboard
    zurueck: eine Zeile pro Kombination (Parameter-Felder + Metrics)."""
    with ProcessPoolExecutor(max_workers=n_jobs, initializer=_init_worker, initargs=(cfg, start, end)) as ex:
        rows = list(tqdm(
            ex.map(_run_one, param_grid), total=len(param_grid),
            desc="Grid-Search", unit="Kombi",
        ))

    df = pd.DataFrame(rows)
    if sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=False).reset_index(drop=True)
    return df
