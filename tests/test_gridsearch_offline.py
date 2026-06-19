#!/usr/bin/env python3
"""Offline-Test der Grid-Search-Bausteine ohne Netzwerk/Prozess-Pool.

Validiert: build_param_grid() (kartesisches Produkt ueber Achsen, nicht
angegebene Felder bleiben fix) und _run_one() direkt gegen ein synthetisches
Tages-Dict (ohne MarketData/Disk, ohne echten ProcessPoolExecutor).
Aufruf: python tests/test_gridsearch_offline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from tradingbot_0dte.backtest import gridsearch
from tradingbot_0dte.backtest.gridsearch import build_param_grid
from tradingbot_0dte.backtest.params import StrategyParams

DATE = 20240105


def _bar(time_str: str, strike: float, bid: float, ask: float, delta: float) -> dict:
    return {
        "timestamp": pd.Timestamp("2024-01-05 %s" % time_str),
        "strike": strike, "right": "PUT", "bid": bid, "ask": ask, "delta": delta,
    }


def _base_params(**overrides) -> StrategyParams:
    p = StrategyParams(
        target_delta=0.16, delta_low=0.01, delta_high=0.50,
        entry_times=["09:35:00"], max_trades_per_day=1, max_concurrent_positions=1,
        profit_target_pct=0.30, stop_loss_multiplier=2.0, time_exit_before_close_min=None,
        slippage_pct_of_spread=0.25, commission_per_contract_leg=1.10,
    )
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def test_build_param_grid():
    base = _base_params()
    axes = {
        "target_delta": [0.10, 0.16],
        "profit_target_pct": [0.20, 0.30, 0.40],
    }
    grid = build_param_grid(base, axes)
    assert len(grid) == 2 * 3, "kartesisches Produkt 2x3=6"
    combos = {(p.target_delta, p.profit_target_pct) for p in grid}
    assert combos == {(0.10, 0.20), (0.10, 0.30), (0.10, 0.40),
                       (0.16, 0.20), (0.16, 0.30), (0.16, 0.40)}
    # nicht angegebene Felder bleiben fix auf dem Basis-Wert
    assert all(p.stop_loss_multiplier == 2.0 for p in grid)
    assert all(p.entry_times == ["09:35:00"] for p in grid)
    print("[ok] build_param_grid (kartesisches Produkt, fixe Restfelder)")


def test_build_param_grid_no_axes():
    base = _base_params()
    grid = build_param_grid(base, {})
    assert len(grid) == 1 and grid[0].target_delta == base.target_delta
    print("[ok] build_param_grid ohne Achsen (1 Kombination = Basis)")


def test_run_one_offline():
    """_run_one() direkt gegen ein synthetisches _WORKER_DAYS-Dict, wie es
    sonst _init_worker() aus den historisierten Daten befuellen wuerde."""
    rows = [
        _bar("09:35:00", 4650.0, 2.0, 2.2, -0.16),
        _bar("09:36:00", 4650.0, 0.4, 0.6, -0.05),  # Profit-Target
    ]
    day_df = pd.DataFrame(rows)
    gridsearch._WORKER_DAYS = {DATE: day_df}
    try:
        params = _base_params()
        row = gridsearch._run_one(params)
    finally:
        gridsearch._WORKER_DAYS = {}

    assert row["target_delta"] == 0.16
    assert row["entry_times"] == "09:35:00"  # Liste -> komma-getrennter String
    assert row["n_trades"] == 1
    assert row["total_pnl"] > 0
    print("[ok] _run_one (Parameter-Felder + Metrics in einer Zeile)")


def main():
    test_build_param_grid()
    test_build_param_grid_no_axes()
    test_run_one_offline()
    print("\nAlle Grid-Search-Offline-Tests bestanden.")


if __name__ == "__main__":
    main()
