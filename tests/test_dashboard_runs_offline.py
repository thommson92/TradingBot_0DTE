#!/usr/bin/env python3
"""Offline-Test der Dashboard-Lauf-Persistenz (dashboard/runs.py) ohne Streamlit.

Validiert: save_backtest_run/save_gridsearch_run schreiben die erwarteten
Dateien und haengen eine vollstaendige Zeile an runs_index.csv an; load_index
liefert ein leeres DataFrame mit den erwarteten Spalten, wenn der Index noch
nicht existiert.
Aufruf: python tests/test_dashboard_runs_offline.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))

import pandas as pd

import runs
from tradingbot_0dte.backtest.params import StrategyParams


def _base_params(**overrides) -> StrategyParams:
    p = StrategyParams(target_delta=0.16, delta_low=0.01, delta_high=0.50)
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def test_load_index_empty():
    tmp = Path(tempfile.mkdtemp())
    try:
        df = runs.load_index(tmp)
        assert df.empty and list(df.columns) == runs.INDEX_COLUMNS
        print("[ok] load_index ohne vorhandene Datei (leeres DataFrame, erwartete Spalten)")
    finally:
        shutil.rmtree(tmp)


def test_save_backtest_run():
    tmp = Path(tempfile.mkdtemp())
    try:
        params = _base_params(spread_type="put_spread", spread_width=10.0)
        metrics = {"n_trades": 3, "win_rate": 0.667, "total_pnl": 150.0,
                   "avg_pnl_per_trade": 50.0, "profit_factor": 2.0,
                   "max_drawdown": 30.0, "sharpe": 1.2, "sortino": 1.5}
        trades_df = pd.DataFrame([{"date": 20240105, "pnl": 50.0}])

        row = runs.save_backtest_run(tmp, "mein-lauf", params, "2024-01-02", "2024-01-31",
                                      metrics, trades_df)

        assert Path(row["csv_path"]).exists() and Path(row["json_path"]).exists()
        assert pd.read_csv(row["csv_path"]).iloc[0]["pnl"] == 50.0

        idx = runs.load_index(tmp)
        assert len(idx) == 1
        r = idx.iloc[0]
        assert r["label"] == "mein-lauf" and r["kind"] == "backtest"
        assert r["spread_type"] == "put_spread" and r["spread_width"] == 10.0
        assert r["total_pnl"] == 150.0 and r["n_trades"] == 3
        print("[ok] save_backtest_run (CSV+JSON geschrieben, Index-Zeile vollstaendig)")
    finally:
        shutil.rmtree(tmp)


def test_save_gridsearch_run():
    tmp = Path(tempfile.mkdtemp())
    try:
        leaderboard = pd.DataFrame([
            {"target_delta": 0.16, "spread_type": "naked", "spread_width": None,
             "n_trades": 21, "win_rate": 0.71, "total_pnl": 538.0,
             "avg_pnl_per_trade": 25.6, "profit_factor": 1.34,
             "max_drawdown": 100.0, "sharpe": 2.1, "sortino": 6.0},
            {"target_delta": 0.10, "spread_type": "naked", "spread_width": None,
             "n_trades": 21, "win_rate": 0.60, "total_pnl": 200.0,
             "avg_pnl_per_trade": 9.5, "profit_factor": 1.1,
             "max_drawdown": 150.0, "sharpe": 0.8, "sortino": 1.0},
        ])
        csv_path = tmp / "grid_leaderboard.csv"
        leaderboard.to_csv(csv_path, index=False)

        row = runs.save_gridsearch_run(tmp, "sweep-1", {"target_delta": [0.10, 0.16]},
                                        "2024-01-02", "2024-01-31", leaderboard, csv_path)

        assert row["total_pnl"] == 538.0, "Index uebernimmt Metrics der besten (ersten) Zeile"
        idx = runs.load_index(tmp)
        assert len(idx) == 1 and idx.iloc[0]["kind"] == "gridsearch"
        assert idx.iloc[0]["csv_path"] == str(csv_path)
        print("[ok] save_gridsearch_run (beste Zeile als Repraesentant, Drilldown-Pfad gesetzt)")
    finally:
        shutil.rmtree(tmp)


def test_multiple_runs_append():
    tmp = Path(tempfile.mkdtemp())
    try:
        params = _base_params()
        metrics = {"n_trades": 1, "win_rate": 1.0, "total_pnl": 10.0,
                   "avg_pnl_per_trade": 10.0, "profit_factor": float("inf"),
                   "max_drawdown": 0.0, "sharpe": float("nan"), "sortino": float("nan")}
        trades_df = pd.DataFrame([{"date": 20240105, "pnl": 10.0}])
        runs.save_backtest_run(tmp, "lauf-a", params, None, None, metrics, trades_df)
        runs.save_backtest_run(tmp, "lauf-b", params, None, None, metrics, trades_df)

        idx = runs.load_index(tmp)
        assert len(idx) == 2 and list(idx["label"]) == ["lauf-a", "lauf-b"]
        print("[ok] mehrere Laeufe haengen sich korrekt an den Index an")
    finally:
        shutil.rmtree(tmp)


def main():
    test_load_index_empty()
    test_save_backtest_run()
    test_save_gridsearch_run()
    test_multiple_runs_append()
    print("\nAlle Dashboard-Runs-Offline-Tests bestanden.")


if __name__ == "__main__":
    main()
