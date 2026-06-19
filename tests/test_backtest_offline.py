#!/usr/bin/env python3
"""Offline-Test der Backtest-Engine (nackter Short Put + Put-Spread) ohne
Netzwerkzugriff.

Validiert: Strike-Wahl per Ziel-Delta, Exit-Prioritaet (Stop-Loss > Profit-Target
> Zeit-Exit), Expiration-Fallback, das Mehrfach-Entry/Tag-Limit (Kernpunkt: "1
Trade/Tag" ist kein festes Kriterium mehr), Put-Spread (Long-Leg-Wahl + Netto-
P&L) und compute_metrics().
Aufruf: python tests/test_backtest_offline.py
"""
from __future__ import annotations

import datetime as dt
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from tradingbot_0dte.backtest.engine import run_day, trades_to_df
from tradingbot_0dte.backtest.metrics import compute_metrics
from tradingbot_0dte.backtest.params import StrategyParams
from tradingbot_0dte.backtest.strategy import pick_long_leg
from tradingbot_0dte.backtest.trade import Trade

DATE = 20240105


def _bar(time_str: str, strike: float, bid: float, ask: float, delta: float) -> dict:
    return {
        "timestamp": pd.Timestamp("2024-01-05 %s" % time_str),
        "strike": strike, "right": "PUT", "bid": bid, "ask": ask, "delta": delta,
        "date": DATE,
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


def test_profit_target():
    rows = [
        _bar("09:35:00", 4650.0, 2.0, 2.2, -0.16),
        _bar("09:35:00", 4500.0, 9.0, 9.4, -0.80),  # ausserhalb Band -> darf nicht gewaehlt werden
        _bar("09:36:00", 4650.0, 0.4, 0.6, -0.05),  # mid 0.5 -> Profit-Target
        _bar("09:37:00", 4650.0, 0.1, 0.2, -0.01),
    ]
    df = pd.DataFrame(rows)
    trades = run_day(df, DATE, _base_params())
    assert len(trades) == 1
    tr = trades[0]
    assert tr.strike == 4650.0
    assert tr.exit_reason == "profit_target"
    assert tr.exit_ts == pd.Timestamp("2024-01-05 09:36:00")
    # entry_price = mid(2.1) - 0.25*spread(0.2) = 2.05
    assert math.isclose(tr.entry_price, 2.05, rel_tol=1e-9)
    # exit_price = mid(0.5) + 0.25*spread(0.2) = 0.55  (< 2.05*0.30=0.615 -> Target)
    assert math.isclose(tr.exit_price, 0.55, rel_tol=1e-9)
    print("[ok] profit_target Exit")


def test_stop_loss():
    rows = [
        _bar("09:35:00", 4650.0, 2.0, 2.2, -0.16),
        _bar("09:36:00", 4650.0, 5.0, 5.4, -0.45),  # mid 5.2 -> weit ueber 2x Praemie
    ]
    df = pd.DataFrame(rows)
    trades = run_day(df, DATE, _base_params())
    assert len(trades) == 1
    tr = trades[0]
    assert tr.exit_reason == "stop_loss"
    # exit_price = mid(5.2) + 0.25*spread(0.4) = 5.3 >= 2.0 * entry_price(2.05)=4.10
    assert math.isclose(tr.exit_price, 5.3, rel_tol=1e-9)
    assert tr.pnl < 0
    print("[ok] stop_loss Exit")


def test_expiration_fallback():
    rows = [
        _bar("09:35:00", 4650.0, 2.0, 2.2, -0.16),
        _bar("09:36:00", 4650.0, 1.9, 2.1, -0.15),
        _bar("16:00:00", 4650.0, 1.8, 2.0, -0.14),  # letzter Bar, kein Exit-Trigger
    ]
    df = pd.DataFrame(rows)
    trades = run_day(df, DATE, _base_params())
    assert len(trades) == 1
    tr = trades[0]
    assert tr.exit_reason == "expiration"
    assert tr.exit_ts == pd.Timestamp("2024-01-05 16:00:00")
    print("[ok] expiration-Fallback (kein Exit-Trigger ausgeloest)")


def test_multi_entry_cap():
    """Kernpunkt: 'max. 1 Trade/Tag' ist kein festes Kriterium -> mehrere
    Entry-Zeiten moeglich, begrenzt durch ein konfigurierbares Tages-Limit."""
    rows = [
        _bar("09:35:00", 4650.0, 2.0, 2.2, -0.16),
        _bar("09:36:00", 4650.0, 0.4, 0.6, -0.05),   # Trade 1: Profit-Target
        _bar("09:40:00", 4650.0, 2.0, 2.2, -0.16),
        _bar("09:41:00", 4650.0, 0.4, 0.6, -0.05),   # Trade 2: Profit-Target
        _bar("09:45:00", 4650.0, 2.0, 2.2, -0.16),   # waere Trade 3, aber Limit=2
        _bar("09:46:00", 4650.0, 0.4, 0.6, -0.05),
    ]
    df = pd.DataFrame(rows)
    params = _base_params(
        entry_times=["09:35:00", "09:40:00", "09:45:00"],
        max_trades_per_day=2,
    )
    trades = run_day(df, DATE, params)
    assert len(trades) == 2, "Drittes Entry darf wegen max_trades_per_day=2 nicht oeffnen"
    assert [t.entry_ts.time() for t in trades] == [dt.time(9, 35), dt.time(9, 40)]

    # Unbegrenzt (None) -> alle drei Entry-Zeiten oeffnen Trades
    params_unlimited = _base_params(
        entry_times=["09:35:00", "09:40:00", "09:45:00"],
        max_trades_per_day=None,
    )
    trades_unlimited = run_day(df, DATE, params_unlimited)
    assert len(trades_unlimited) == 3
    print("[ok] mehrere Entry-Zeiten/Tag + konfigurierbares Limit (kein festes '1 Trade/Tag')")


def test_pick_long_leg():
    """Long-Leg-Wahl: nearest-match, kein exakter Strikeabstand noetig."""
    snapshot = pd.DataFrame([
        _bar("09:35:00", 4700.0, 9.0, 9.4, -0.80),
        _bar("09:35:00", 4650.0, 2.0, 2.2, -0.16),
        _bar("09:35:00", 4630.0, 1.0, 1.2, -0.10),
        _bar("09:35:00", 4600.0, 0.3, 0.5, -0.04),
    ])
    row = pick_long_leg(snapshot, short_strike=4650.0, width=10.0)
    assert row is not None and row["strike"] == 4630.0, "4630 liegt naeher an 4650-10=4640 als 4600"
    print("[ok] pick_long_leg (nearest-match)")


def test_put_spread_pnl():
    """Put-Spread: Netto-Kredit bei Eroeffnung, Exit auf Spread-Netto-Wert,
    Kommission fuer 2 Legs."""
    rows = [
        _bar("09:35:00", 4650.0, 2.0, 2.2, -0.16),
        _bar("09:35:00", 4640.0, 0.5, 0.7, -0.08),
        _bar("09:36:00", 4650.0, 0.3, 0.5, -0.05),
        _bar("09:36:00", 4640.0, 0.05, 0.15, -0.02),
    ]
    df = pd.DataFrame(rows)
    params = _base_params(spread_type="put_spread", spread_width=10.0)
    trades = run_day(df, DATE, params)
    assert len(trades) == 1
    tr = trades[0]
    assert tr.strike == 4650.0 and tr.long_strike == 4640.0
    assert tr.exit_reason == "profit_target"
    # entry_credit = sell_fill(2.0,2.2)=2.05 - buy_fill(0.5,0.7)=0.65 -> 1.40
    assert math.isclose(tr.entry_price, 1.40, rel_tol=1e-9)
    # exit_cost = buy_fill(0.3,0.5)=0.45 - sell_fill(0.05,0.15)=0.075 -> 0.375 (<= 1.40*0.30=0.42)
    assert math.isclose(tr.exit_price, 0.375, rel_tol=1e-9)
    # pnl = (1.40-0.375)*100 - commission(legs=2: 1.10*2*2=4.4) = 98.1
    assert math.isclose(tr.pnl, 98.1, rel_tol=1e-9)
    print("[ok] Put-Spread: Long-Leg-Wahl, Netto-Kredit/-Exit, 2-Leg-Kommission")


def test_put_spread_nan_bar_no_crash():
    """Regression: ein Spread-Bar ohne Quote (NaN bid/ask) darf nicht crashen.

    Frueher baute _simulate_spread_entry die Bars als pd.Series({Timestamp, bid,
    ask}); pandas zwang die Series bei NaN bid/ask auf datetime64 und machte aus
    den NaN-Floats NaT -> die Preis-Arithmetik ergab NaT und der Schwellenwert-
    Vergleich (NaT >= float) warf einen TypeError. Jetzt werden Dicts genutzt.
    """
    rows = [
        _bar("09:35:00", 4650.0, 2.0, 2.2, -0.16),
        _bar("09:35:00", 4640.0, 0.5, 0.7, -0.08),
        # Mittlerer Bar ohne Quote (illiquide Long-Leg): NaN bid/ask
        _bar("09:36:00", 4650.0, float("nan"), float("nan"), -0.05),
        _bar("09:36:00", 4640.0, float("nan"), float("nan"), -0.02),
        # Spaeterer gueltiger Bar -> Profit-Target greift hier
        _bar("09:37:00", 4650.0, 0.3, 0.5, -0.04),
        _bar("09:37:00", 4640.0, 0.05, 0.15, -0.01),
    ]
    df = pd.DataFrame(rows)
    params = _base_params(spread_type="put_spread", spread_width=10.0)
    trades = run_day(df, DATE, params)  # darf nicht werfen
    assert len(trades) == 1
    tr = trades[0]
    assert tr.exit_reason == "profit_target"
    assert tr.exit_ts == pd.Timestamp("2024-01-05 09:37:00"), "NaN-Bar uebersprungen, Exit am gueltigen Bar"
    assert math.isfinite(tr.pnl)
    print("[ok] Put-Spread: NaN-Bar (kein Quote) wird ohne Crash uebersprungen")


def test_compute_metrics():
    base_ts = pd.Timestamp("2024-01-02 10:00:00")
    trades = [
        Trade(date=20240102, entry_ts=base_ts, exit_ts=base_ts, strike=4650.0,
              entry_delta=-0.16, entry_price=2.0, exit_price=1.0, exit_reason="profit_target", pnl=100.0),
        Trade(date=20240103, entry_ts=base_ts, exit_ts=base_ts + dt.timedelta(minutes=1), strike=4650.0,
              entry_delta=-0.16, entry_price=2.0, exit_price=3.0, exit_reason="stop_loss", pnl=-50.0),
        Trade(date=20240104, entry_ts=base_ts, exit_ts=base_ts + dt.timedelta(minutes=2), strike=4650.0,
              entry_delta=-0.16, entry_price=2.0, exit_price=0.5, exit_reason="profit_target", pnl=200.0),
        Trade(date=20240105, entry_ts=base_ts, exit_ts=base_ts + dt.timedelta(minutes=3), strike=4650.0,
              entry_delta=-0.16, entry_price=2.0, exit_price=2.5, exit_reason="expiration", pnl=-30.0),
    ]
    df = trades_to_df(trades)
    m = compute_metrics(df)

    assert m["n_trades"] == 4
    assert math.isclose(m["win_rate"], 0.5)
    assert math.isclose(m["total_pnl"], 220.0)
    assert math.isclose(m["avg_pnl_per_trade"], 55.0)
    assert math.isclose(m["profit_factor"], 300.0 / 80.0)
    # Equity (chronologisch): 100, 50, 250, 220 -> running_max 100,100,250,250 -> Drawdown max 50
    assert math.isclose(m["max_drawdown"], 50.0)
    assert m["sharpe"] is not None and not math.isnan(m["sharpe"])
    assert m["sortino"] is not None and not math.isnan(m["sortino"])
    print("[ok] compute_metrics (win_rate, profit_factor, expectancy, drawdown)")


def main():
    test_profit_target()
    test_stop_loss()
    test_expiration_fallback()
    test_multi_entry_cap()
    test_pick_long_leg()
    test_put_spread_pnl()
    test_put_spread_nan_bar_no_crash()
    test_compute_metrics()
    print("\nAlle Backtest-Offline-Tests bestanden.")


if __name__ == "__main__":
    main()
