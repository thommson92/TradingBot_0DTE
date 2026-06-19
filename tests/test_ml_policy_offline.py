#!/usr/bin/env python3
"""Offline-Test fuer ML-Policy + Bewertung (Phase 5, Schritt 4) -- ohne Netzwerk.

Validiert:
- select_trades(): Schwellen-, Win-Filter- und Tageslimit-Selektion.
- to_trade_log()/policy_metrics(): compute_metrics-taugliches Trade-Log.
- composite_score(): Calmar-Logik + Win-Rate-Mindestschwelle.
- tune_threshold(): waehlt eine engere, profitable Schwelle auf gescorten Daten.
- save_ml_run(): dashboard-kompatible Persistenz (Index-Zeile, kind='ml_backtest').
Aufruf: python tests/test_ml_policy_offline.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))

import numpy as np
import pandas as pd

from tradingbot_0dte.ml.evaluate import composite_score, policy_metrics, to_trade_log, tune_threshold, tune_top_n
from tradingbot_0dte.ml.policy import collapse_exits, select_trades
import runs as dashboard_runs


def _scored(seed: int = 0) -> pd.DataFrame:
    """Gescorte Kandidaten: pnl_hat korreliert mit realem pnl (hoher Score ->
    positiver P&L), niedriger Score -> Verlust. Mehrere Kandidaten pro Tag."""
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(20230102, 20230122):  # 20 "Tage"
        for k in range(10):
            score = rng.normal(0, 10)
            pnl = score * 3 + rng.normal(0, 5)  # hoher Score -> hoher P&L
            rows.append({
                "date": d, "entry_time": "10:%02d:00" % k,
                "pnl": float(pnl), "is_win": 1.0 if pnl > 0 else 0.0,
                "pnl_hat": float(score), "win_proba": float(1 / (1 + np.exp(-score / 5))),
            })
    return pd.DataFrame(rows)


def test_select_trades():
    df = _scored()
    thr = df["pnl_hat"].quantile(0.8)
    sel = select_trades(df, thr)
    assert (sel["pnl_hat"] >= thr).all()
    assert len(sel) < len(df)
    # Win-Filter
    sel_wp = select_trades(df, thr, win_proba_floor=0.6)
    assert (sel_wp["win_proba"] >= 0.6).all()
    # Tageslimit: max 1 Trade/Tag -> hoechstes pnl_hat je Tag
    sel_cap = select_trades(df, df["pnl_hat"].min(), max_trades_per_day=1)
    assert (sel_cap.groupby("date").size() <= 1).all()
    assert len(sel_cap) == df["date"].nunique()
    print("[ok] select_trades (Schwelle, Win-Filter, Tageslimit)")


def test_to_trade_log_and_metrics():
    df = _scored()
    sel = select_trades(df, df["pnl_hat"].quantile(0.7))
    log = to_trade_log(sel)
    assert "exit_ts" in log.columns and log["exit_ts"].notna().all()
    m = policy_metrics(sel)
    assert m["n_trades"] == len(sel)
    assert abs(m["total_pnl"] - sel["pnl"].sum()) < 1e-6
    # leere Selektion -> leere Metrics ohne Crash
    empty = policy_metrics(select_trades(df, 1e9))
    assert empty["n_trades"] == 0
    print("[ok] to_trade_log/policy_metrics (inkl. leere Selektion)")


def test_composite_score():
    good = {"n_trades": 100, "total_pnl": 1000.0, "win_rate": 0.70, "max_drawdown": 200.0}
    weak_win = {"n_trades": 100, "total_pnl": 1000.0, "win_rate": 0.40, "max_drawdown": 200.0}
    losing = {"n_trades": 100, "total_pnl": -500.0, "win_rate": 0.70, "max_drawdown": 800.0}
    empty = {"n_trades": 0, "total_pnl": 0.0, "win_rate": float("nan"), "max_drawdown": 0.0}

    assert composite_score(good, min_win_rate=0.60) > 0
    assert composite_score(good) > composite_score(weak_win), "Win-Rate unter Schwelle -> abgestraft"
    assert composite_score(good) > composite_score(losing)
    assert composite_score(empty) == float("-inf")
    print("[ok] composite_score (Calmar + Win-Rate-Schwelle)")


def test_tune_threshold_picks_profitable():
    df = _scored()
    best, table = tune_threshold(df, min_win_rate=0.55)
    assert best["total_pnl"] > 0, "getunte Schwelle sollte profitabel sein"
    assert best["top_pct"] < 0.5, "engere Selektion als die Haelfte"
    assert "composite" in table.columns and len(table) > 3
    # Beste Zeile hat den maximalen Komposit-Score
    assert best["composite"] == table["composite"].max()
    print("[ok] tune_threshold (waehlt enge, profitable Schwelle)")


def test_tune_top_n():
    """Per-Tag-Top-N: kausal (taeglich die besten N), profitabel, N <= Kandidaten/Tag."""
    df = _scored()
    best, table = tune_top_n(df, n_values=(1, 2, 3, 5), pnl_hat_floor=0.0, min_win_rate=0.55)
    assert best["total_pnl"] > 0
    assert 1 <= best["n_per_day"] <= 5
    assert best["composite"] == table["composite"].max()
    # Jeder N-Lauf haelt das Tageslimit ein
    sel = select_trades(df, 0.0, max_trades_per_day=int(best["n_per_day"]))
    assert (sel.groupby("date").size() <= best["n_per_day"]).all()
    print("[ok] tune_top_n (kausale Per-Tag-Top-N-Policy)")


def _scored_with_exits() -> pd.DataFrame:
    """Zwei Entry-Gelegenheiten je Tag, jede mit drei Exit-Varianten (gleicher
    Entry-Key, unterschiedliche Exit-Meta + pnl_hat)."""
    rows = []
    for d in (20230102, 20230103):
        for et, td in [("10:00:00", 0.16), ("11:00:00", 0.10)]:
            for i, (pt, score, pnl) in enumerate([(0.30, 5.0, 20.0), (0.50, 9.0, 30.0), (None, 3.0, -10.0)]):
                rows.append({
                    "date": d, "entry_time": et, "target_delta": td,
                    "spread_type": "naked", "spread_width": float("nan"),
                    "profit_target_pct": pt, "pnl": pnl, "is_win": 1.0 if pnl > 0 else 0.0,
                    "pnl_hat": score, "win_proba": 0.7,
                })
    return pd.DataFrame(rows)


def test_collapse_exits():
    """collapse_exits behaelt je Entry-Gelegenheit nur die hoechstbewertete Exit-Variante."""
    df = _scored_with_exits()
    collapsed = collapse_exits(df)
    # 2 Tage x 2 Gelegenheiten = 4 Zeilen (statt 12)
    assert len(collapsed) == 4
    assert (collapsed.groupby(["date", "entry_time"]).size() == 1).all()
    # jeweils die Variante mit hoechstem pnl_hat (=9.0, profit_target 0.50)
    assert (collapsed["pnl_hat"] == 9.0).all()
    assert (collapsed["profit_target_pct"] == 0.50).all()
    # ohne Entry-Key-Spalten unveraendert (Rueckwaerts-Kompatibilitaet)
    bare = pd.DataFrame({"pnl_hat": [1.0, 2.0], "pnl": [1.0, 2.0]})
    assert len(collapse_exits(bare)) == 2
    print("[ok] collapse_exits (beste Exit-Variante je Entry-Gelegenheit)")


def test_select_trades_collapse_then_top_n():
    """Mit collapse_exits_first waehlt Top-N je Tag aus den kollabierten Gelegenheiten
    (nicht aus near-identischen Exit-Varianten derselben Gelegenheit)."""
    df = _scored_with_exits()
    sel = select_trades(df, 0.0, max_trades_per_day=1, collapse_exits_first=True)
    assert (sel.groupby("date").size() == 1).all()
    # gewaehlt: die beste Gelegenheit des Tages, mit ihrer besten Exit-Variante
    assert (sel["pnl_hat"] == 9.0).all() and (sel["profit_target_pct"] == 0.50).all()
    print("[ok] select_trades (collapse_exits_first + Top-N)")


def test_save_ml_run():
    df = _scored()
    sel = select_trades(df, df["pnl_hat"].quantile(0.8))
    m = policy_metrics(sel)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        row = dashboard_runs.save_ml_run(out, "Test-ML", "20230102", "20230121", m, sel,
                                         info={"pnl_hat_threshold": 5.0, "top_pct": 0.2})
        assert row["kind"] == "ml_backtest"
        idx = dashboard_runs.load_index(out)
        assert len(idx) == 1 and idx.iloc[0]["kind"] == "ml_backtest"
        assert Path(row["csv_path"]).exists() and Path(row["json_path"]).exists()
    print("[ok] save_ml_run (dashboard-kompatible Persistenz)")


def main():
    test_select_trades()
    test_to_trade_log_and_metrics()
    test_composite_score()
    test_tune_threshold_picks_profitable()
    test_tune_top_n()
    test_collapse_exits()
    test_select_trades_collapse_then_top_n()
    test_save_ml_run()
    print("\nAlle ML-Policy-Offline-Tests bestanden.")


if __name__ == "__main__":
    main()
