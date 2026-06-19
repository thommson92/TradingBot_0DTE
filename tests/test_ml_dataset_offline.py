#!/usr/bin/env python3
"""Offline-Test fuer den ML-Dataset-Aufbau (Phase 5, Schritt 2) -- ohne
Netzwerk-/Marktzugriff und ohne Multiprocessing (build_day_rows direkt).

Validiert:
- CandidateGrid.expand(): kartesisches Produkt der drei Achsen.
- default_entry_times(): korrektes Zeit-Raster.
- build_day_rows(): eine Zeile je Kandidat, korrekte Meta-/Feature-/Label-Spalten,
  Trennung tradable=1 (Trade) vs. tradable=0 (kein Strike im Band), is_win-Flag.
Aufruf: python tests/test_ml_dataset_offline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from tradingbot_0dte.ml.dataset import (
    CandidateGrid, DATASET_COLUMNS, ExitRule, build_day_rows, default_entry_times,
)

DATE = 20240105


def _bar(time_str, strike, bid, ask, delta, *, iv=0.20, underlying=4660.0) -> dict:
    return {
        "timestamp": pd.Timestamp("2024-01-05 %s" % time_str),
        "strike": strike, "right": "PUT", "bid": bid, "ask": ask, "delta": delta,
        "theta": -0.5, "vega": 0.1, "rho": 0.0, "implied_vol": iv,
        "underlying_price": underlying, "mid": (bid + ask) / 2.0, "date": DATE,
    }


def test_default_entry_times():
    times = default_entry_times("09:35:00", "10:35:00", 30)
    assert times == ["09:35:00", "10:05:00", "10:35:00"]
    print("[ok] default_entry_times (Raster inkl. Endzeit)")


def test_candidate_grid_expand():
    grid = CandidateGrid(
        entry_times=["09:35:00", "10:05:00"],
        target_deltas=[0.10, 0.16],
        spreads=[("naked", None), ("put_spread", 5.0)],
    )
    cands = grid.expand()
    assert len(cands) == 2 * 2 * 2, "2 Zeiten x 2 Deltas x 2 Spread-Typen"
    # Stichprobe: alle Kombinationen vorhanden
    keys = {(c.entry_time, c.target_delta, c.spread_type, c.spread_width) for c in cands}
    assert ("09:35:00", 0.10, "naked", None) in keys
    assert ("10:05:00", 0.16, "put_spread", 5.0) in keys
    print("[ok] CandidateGrid.expand (kartesisches Produkt)")


def test_build_day_rows_tradable_and_label():
    rows_data = [
        # Entry 09:35: Strike 4650 (delta -0.16) -> handelbar, Profit-Target
        _bar("09:35:00", 4650.0, 2.0, 2.2, -0.16),
        _bar("09:35:00", 4600.0, 1.0, 1.2, -0.10),
        _bar("09:36:00", 4650.0, 0.4, 0.6, -0.05),  # -> Profit-Target fuer den 0.16er
        _bar("09:36:00", 4600.0, 0.3, 0.5, -0.04),
    ]
    day = pd.DataFrame(rows_data)
    exit_rule = ExitRule(profit_target_pct=0.30, stop_loss_multiplier=2.0, time_exit_before_close_min=None)

    # Handelbarer Kandidat: Band [0.05,0.20] enthaelt Strike 4650 (delta 0.16)
    grid_ok = CandidateGrid(
        entry_times=["09:35:00"], target_deltas=[0.16], spreads=[("naked", None)],
        delta_low=0.05, delta_high=0.20,
    )
    rows = build_day_rows(day, DATE, grid_ok.expand(), exit_rule, prev_close=4640.0)
    assert len(rows) == 1, "eine Zeile je Kandidat"
    assert set(pd.DataFrame(rows).columns) == set(DATASET_COLUMNS)
    hit = rows[0]
    assert hit["tradable"] == 1 and hit["strike"] == 4650.0
    assert hit["is_win"] == 1.0 and hit["pnl"] > 0 and hit["exit_reason"] == "profit_target"
    assert hit["date"] == DATE and hit["entry_time"] == "09:35:00"

    # Nicht handelbarer Kandidat: Band [0.60,0.90] enthaelt keinen der Strikes
    # (max |delta| am Tag ist 0.16) -> pick_strike findet nichts.
    grid_miss = CandidateGrid(
        entry_times=["09:35:00"], target_deltas=[0.16], spreads=[("naked", None)],
        delta_low=0.60, delta_high=0.90,
    )
    miss_rows = build_day_rows(day, DATE, grid_miss.expand(), exit_rule, prev_close=4640.0)
    assert len(miss_rows) == 1
    miss = miss_rows[0]
    assert miss["tradable"] == 0 and pd.isna(miss["pnl"]) and pd.isna(miss["is_win"])
    print("[ok] build_day_rows (tradable/Label, eine Zeile je Kandidat)")


def test_build_day_rows_shared_market_features():
    """market_features pro Entry-Zeit identisch fuer alle Kandidaten desselben Bars."""
    day = pd.DataFrame([
        _bar("09:35:00", 4650.0, 2.0, 2.2, -0.16),
        _bar("09:35:00", 4600.0, 1.0, 1.2, -0.10),
        _bar("09:36:00", 4650.0, 1.9, 2.1, -0.15),
        _bar("09:36:00", 4600.0, 0.9, 1.1, -0.09),
    ])
    grid = CandidateGrid(
        entry_times=["09:35:00"], target_deltas=[0.10, 0.16], spreads=[("naked", None)],
        delta_low=0.05, delta_high=0.20,
    )
    rows = build_day_rows(day, DATE, grid.expand(), ExitRule(time_exit_before_close_min=None), prev_close=4640.0)
    assert rows[0]["atm_iv"] == rows[1]["atm_iv"]
    assert rows[0]["underlying"] == rows[1]["underlying"]
    # aber kandidatenspezifische Features unterscheiden sich (Strike-Delta)
    assert rows[0]["strike_delta"] != rows[1]["strike_delta"]
    print("[ok] build_day_rows teilt market_features je Entry-Zeit")


def main():
    test_default_entry_times()
    test_candidate_grid_expand()
    test_build_day_rows_tradable_and_label()
    test_build_day_rows_shared_market_features()
    print("\nAlle ML-Dataset-Offline-Tests bestanden.")


if __name__ == "__main__":
    main()
