#!/usr/bin/env python3
"""Offline-Test fuer das ML-Feature-Engineering und die Label-Simulation
(Phase 5, Schritt 1) -- ohne Netzwerk-/Marktzugriff.

Validiert:
- market_features: Zeit-/Underlying-/IV-Features (ATM-IV, Skew, ret_since_open,
  gap_open, minute_of_day/minutes_to_close) und Leakage-Sicherheit (kein Blick
  auf Bars nach dem Entry).
- compute_features: gewaehlter Short-Strike + dessen Greeks (gleiche pick_strike-
  Logik wie der Backtest).
- simulate_candidate: realer Trade-Ausgang via Engine (Profit-Target) und der
  "nicht handelbar"-Fall (kein Strike im Delta-Band -> Trade None, Snapshot da).
Aufruf: python tests/test_ml_features_offline.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from tradingbot_0dte.ml.features import compute_features, market_features
from tradingbot_0dte.ml.labels import Candidate, ExitRule, simulate_candidate

DATE = 20240105  # 2024-01-05 ist ein Freitag (dayofweek == 4)

# Strike -> (Delta, IV) fuer eine kleine, aber realistische Optionskette.
STRIKES = [
    (4700.0, -0.80, 0.18),
    (4660.0, -0.50, 0.15),   # ATM (|delta| ~ 0.50)
    (4650.0, -0.30, 0.14),
    (4630.0, -0.16, 0.13),
    (4600.0, -0.10, 0.135),
    (4550.0, -0.05, 0.16),
]


def _bar(time_str, strike, bid, ask, delta, *, iv=0.15, underlying=4660.0,
         theta=-0.5, vega=0.1) -> dict:
    return {
        "timestamp": pd.Timestamp("2024-01-05 %s" % time_str),
        "strike": strike, "right": "PUT", "bid": bid, "ask": ask, "delta": delta,
        "theta": theta, "vega": vega, "rho": 0.0, "implied_vol": iv,
        "underlying_price": underlying, "mid": (bid + ask) / 2.0, "date": DATE,
    }


def _chain(time_str, underlying) -> list:
    return [
        _bar(time_str, strike, 2.0, 2.2, delta, iv=iv, underlying=underlying)
        for strike, delta, iv in STRIKES
    ]


def _day_with_history() -> pd.DataFrame:
    rows = (
        _chain("09:35:00", 4660.0)
        + _chain("09:36:00", 4665.0)
        + _chain("09:37:00", 4670.0)
        + _chain("16:00:00", 4680.0)  # spaeter Bar -> realistischer Close
    )
    return pd.DataFrame(rows)


def test_market_features():
    day = _day_with_history()
    snapshot = day[day["timestamp"] == pd.Timestamp("2024-01-05 09:37:00")]
    entry_ts = pd.Timestamp("2024-01-05 09:37:00")

    mf = market_features(day, snapshot, entry_ts, prev_close=4650.0)

    assert math.isclose(mf["minute_of_day"], 2.0)             # 09:37 - 09:35
    assert math.isclose(mf["minutes_to_close"], 383.0)         # 16:00 - 09:37
    assert mf["day_of_week"] == 4.0 and mf["month"] == 1.0
    assert math.isclose(mf["underlying"], 4670.0)
    assert math.isclose(mf["ret_since_open"], 4670.0 / 4660.0 - 1.0, rel_tol=1e-9)
    assert math.isclose(mf["gap_open"], 4660.0 / 4650.0 - 1.0, rel_tol=1e-9)
    assert math.isclose(mf["atm_iv"], 0.15)                    # nearest |delta| -> 0.50
    assert math.isclose(mf["iv_skew"], 0.135 - 0.14, rel_tol=1e-9)  # iv(0.10) - iv(0.30)
    assert not math.isnan(mf["realized_vol_intraday"]) and mf["realized_vol_intraday"] >= 0.0
    print("[ok] market_features (Zeit, Underlying, ATM-IV, Skew)")


def test_market_features_leakage_safe():
    """Entry um 09:36 darf den Underlying-Spike um 09:37 NICHT sehen."""
    rows = (
        _chain("09:35:00", 4660.0)
        + _chain("09:36:00", 4665.0)
        + _chain("09:37:00", 5000.0)  # grosser Spruch NACH dem Entry
    )
    day = pd.DataFrame(rows)
    snapshot = day[day["timestamp"] == pd.Timestamp("2024-01-05 09:36:00")]
    entry_ts = pd.Timestamp("2024-01-05 09:36:00")

    mf = market_features(day, snapshot, entry_ts, prev_close=4650.0)
    assert math.isclose(mf["underlying"], 4665.0), "Underlying darf nur bis Entry reichen"
    assert math.isclose(mf["ret_since_open"], 4665.0 / 4660.0 - 1.0, rel_tol=1e-9)
    print("[ok] market_features ist leakage-sicher (kein Blick nach dem Entry)")


def test_compute_features_picks_strike():
    day = _day_with_history()
    snapshot = day[day["timestamp"] == pd.Timestamp("2024-01-05 09:37:00")]
    entry_ts = pd.Timestamp("2024-01-05 09:37:00")
    cand = Candidate(entry_time="09:37:00", target_delta=0.16)

    feats = compute_features(day, snapshot, entry_ts, cand, prev_close=4650.0)

    assert math.isclose(feats["strike_delta"], 0.16, rel_tol=1e-9)   # Strike 4630
    assert math.isclose(feats["strike_iv"], 0.13, rel_tol=1e-9)
    assert math.isclose(feats["strike_dist_pct"], (4670.0 - 4630.0) / 4670.0, rel_tol=1e-9)
    assert feats["cand_is_spread"] == 0.0 and feats["cand_spread_width"] == 0.0
    assert math.isclose(feats["cand_target_delta"], 0.16)
    print("[ok] compute_features waehlt den Short-Strike + dessen Greeks")


def test_simulate_candidate_profit_target():
    rows = [
        _bar("09:35:00", 4650.0, 2.0, 2.2, -0.16),
        _bar("09:36:00", 4650.0, 0.4, 0.6, -0.05),   # mid 0.5 -> Profit-Target
    ]
    day = pd.DataFrame(rows)
    cand = Candidate(entry_time="09:35:00", target_delta=0.16)
    exit_rule = ExitRule(profit_target_pct=0.30, stop_loss_multiplier=2.0,
                         time_exit_before_close_min=None)

    trade, snapshot = simulate_candidate(day, DATE, cand, exit_rule)
    assert not snapshot.empty
    assert trade is not None
    assert trade.exit_reason == "profit_target"
    assert math.isclose(trade.entry_price, 2.05, rel_tol=1e-9)  # mid 2.1 - 0.25*0.2
    assert math.isclose(trade.exit_price, 0.55, rel_tol=1e-9)
    assert trade.pnl > 0
    print("[ok] simulate_candidate (naked, Profit-Target) konsistent zur Engine")


def test_simulate_candidate_no_strike_in_band():
    """Kein Strike im Delta-Band -> kein Trade, aber Snapshot vorhanden."""
    rows = [_bar("09:35:00", 4650.0, 2.0, 2.2, -0.16)]
    day = pd.DataFrame(rows)
    cand = Candidate(entry_time="09:35:00", target_delta=0.16, delta_low=0.60, delta_high=0.90)

    trade, snapshot = simulate_candidate(day, DATE, cand, ExitRule())
    assert trade is None, "Delta-Band 0.60-0.90 enthaelt keinen Strike"
    assert not snapshot.empty, "Snapshot wird auch ohne Trade zurueckgegeben"
    print("[ok] simulate_candidate trennt 'nicht handelbar' von 'Verlust-Trade'")


def main():
    test_market_features()
    test_market_features_leakage_safe()
    test_compute_features_picks_strike()
    test_simulate_candidate_profit_target()
    test_simulate_candidate_no_strike_in_band()
    print("\nAlle ML-Feature/Label-Offline-Tests bestanden.")


if __name__ == "__main__":
    main()
