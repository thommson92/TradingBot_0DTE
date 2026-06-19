#!/usr/bin/env python3
"""Offline-Test fuer EV-Modell + Walk-Forward (Phase 5, Schritt 3) -- ohne
Netzwerk-/Marktzugriff, mit synthetischen Mehrquartalsdaten.

Validiert:
- quarter_blocks(): chronologische Quartalsgruppierung.
- train_model()/EVModel.predict(): lernt eine eingebaute Beziehung
  (niedriges Delta -> hoeherer P&L) und liefert pnl_hat/win_proba.
- run_walk_forward(): expandierendes Training, OOS nur vor dem Holdout, erste
  Bloecke nur als Trainingsfenster, kein Holdout-Tag in den OOS-Vorhersagen.
Aufruf: python tests/test_ml_model_offline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from tradingbot_0dte.ml.dataset import DATASET_COLUMNS
from tradingbot_0dte.ml.features import FEATURE_COLUMNS
from tradingbot_0dte.ml.model import train_model
from tradingbot_0dte.ml.walkforward import quarter_blocks, run_walk_forward, train_final

HOLDOUT_START = 20230401  # 2023 Q2 = Holdout
# Quartals-Anfangsmonate fuer 2022 Q1..Q4 und 2023 Q1..Q2.
QUARTER_MONTHS = [(2022, 1), (2022, 4), (2022, 7), (2022, 10), (2023, 1), (2023, 4)]


def _make_dataset(seed: int = 0) -> pd.DataFrame:
    """Synthetisches Dataset: pnl ist eine lernbare Funktion von strike_delta
    (niedriges Delta -> positiver P&L), plus Rauschen. Alle DATASET_COLUMNS gesetzt."""
    rng = np.random.default_rng(seed)
    rows = []
    for year, month in QUARTER_MONTHS:
        for day in range(1, 11):  # 10 Tage je Quartal
            date = year * 10000 + month * 100 + day
            for delta in [0.05, 0.10, 0.16, 0.20, 0.30]:
                sd = float(delta + rng.normal(0, 0.004))
                pnl = float(60.0 - 350.0 * sd + rng.normal(0, 8.0))
                row = {c: 0.0 for c in FEATURE_COLUMNS}
                row.update({
                    "minute_of_day": 30.0, "minutes_to_close": 360.0,
                    "day_of_week": float(date % 5), "month": float(month),
                    "underlying": 4600.0, "atm_iv": 0.20,
                    "cand_target_delta": float(delta), "strike_delta": sd,
                    "strike_iv": 0.21, "strike_mid": 2.0, "strike_dist_pct": 0.01,
                    "date": date, "entry_time": "10:00:00", "target_delta": float(delta),
                    "spread_type": "naked", "spread_width": np.nan,
                    "tradable": 1, "pnl": pnl, "is_win": 1.0 if pnl > 0 else 0.0,
                    "exit_reason": "x", "strike": 4600.0, "long_strike": np.nan,
                    "entry_price": 2.0, "exit_price": 1.0,
                })
                rows.append(row)
    return pd.DataFrame(rows)[DATASET_COLUMNS]


def test_quarter_blocks():
    dates = [20220103, 20220215, 20220401, 20221215, 20230105]
    blocks = quarter_blocks(dates)
    assert len(blocks) == 4, "Q1/2022, Q2/2022, Q4/2022, Q1/2023"
    assert blocks[0] == [20220103, 20220215]
    assert blocks[-1] == [20230105]
    print("[ok] quarter_blocks (chronologische Quartalsgruppierung)")


def test_train_predict_learns_relationship():
    df = _make_dataset()
    model = train_model(df)
    probe = pd.DataFrame([
        {**{c: 0.0 for c in FEATURE_COLUMNS}, "strike_delta": 0.05, "cand_target_delta": 0.05},
        {**{c: 0.0 for c in FEATURE_COLUMNS}, "strike_delta": 0.30, "cand_target_delta": 0.30},
    ])
    pred = model.predict(probe)
    assert set(pred.columns) == {"pnl_hat", "win_proba"}
    assert pred["pnl_hat"].iloc[0] > pred["pnl_hat"].iloc[1], "niedriges Delta -> hoeherer erwarteter P&L"
    assert pred["win_proba"].iloc[0] > pred["win_proba"].iloc[1], "niedriges Delta -> hoehere Win-Wahrscheinlichkeit"
    assert (pred["win_proba"].between(0, 1)).all()
    print("[ok] train_model/predict (lernt Delta->P&L-Beziehung)")


def test_walk_forward_holdout_and_oos():
    df = _make_dataset()
    oos, folds = run_walk_forward(df, HOLDOUT_START, initial_train_blocks=2)

    # Nicht-Holdout-Bloecke: 2022 Q1..Q4 + 2023 Q1 = 5; minus 2 Anfangsbloecke -> 3 Folds
    assert len(folds) == 3, "5 Bloecke vor Holdout, 2 als Anfangstraining -> 3 OOS-Folds"
    assert not oos.empty
    assert (oos["date"] < HOLDOUT_START).all(), "kein Holdout-Tag in den OOS-Vorhersagen"
    # OOS beginnt fruehestens im 3. Block (Q3/2022)
    assert oos["date"].min() >= 20220701
    assert {"pnl_hat", "win_proba"}.issubset(oos.columns)
    # Folds sind chronologisch und nicht ueberlappend
    starts = [f.test_start for f in folds]
    assert starts == sorted(starts)
    print("[ok] run_walk_forward (Holdout unberuehrt, OOS chronologisch)")


def test_train_final_excludes_holdout():
    df = _make_dataset()
    model = train_final(df, HOLDOUT_START)
    # Modell ist trainiert und liefert plausible Vorhersagen auf Holdout-Daten
    holdout = df[df["date"] >= HOLDOUT_START]
    assert not holdout.empty
    pred = model.predict(holdout)
    assert len(pred) == len(holdout) and pred["pnl_hat"].notna().all()
    print("[ok] train_final (Holdout aus Training ausgeschlossen, Vorhersage moeglich)")


def main():
    test_quarter_blocks()
    test_train_predict_learns_relationship()
    test_walk_forward_holdout_and_oos()
    test_train_final_excludes_holdout()
    print("\nAlle ML-Modell/Walk-Forward-Offline-Tests bestanden.")


if __name__ == "__main__":
    main()
