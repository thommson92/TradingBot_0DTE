"""Walk-Forward-Validierung mit unberuehrtem Holdout (Entscheidung #17).

Ablauf:
- Der Zeitraum >= holdout_start bleibt KOMPLETT aussen vor (kein Training, keine
  Schwellen-Wahl) -- er dient spaeter nur dem finalen Realitaets-Check.
- Auf dem Rest werden quartalsweise Test-Bloecke gebildet. Fuer jeden Block wird
  ein Modell auf ALLEN frueheren Tagen trainiert (expandierendes Fenster) und der
  Block out-of-sample vorhergesagt. So entsteht eine OOS-Vorhersage ueber fast die
  ganze Historie, ohne je in die Zukunft zu schauen.

Purging: 0-DTE-Trades enden am selben Tag, daher genuegt 'Trainingstag < Testtag'
als strikte Trennung -- es gibt keine ueber Tage laufenden Trade-Lebensdauern, die
sonst zwischen Train und Test ueberlappen koennten.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import pandas as pd

from .features import FEATURE_COLUMNS
from .model import EVModel, train_model, tradable_rows


@dataclass
class FoldResult:
    test_start: int
    test_end: int
    n_train: int
    n_test: int


def quarter_blocks(dates: List[int]) -> List[List[int]]:
    """Gruppiert sortierte YYYYMMDD-Daten nach Kalenderquartal (chronologisch)."""
    blocks: dict = {}
    for d in sorted(dates):
        year = d // 10000
        month = (d // 100) % 100
        quarter = (month - 1) // 3
        blocks.setdefault((year, quarter), []).append(d)
    return [blocks[k] for k in sorted(blocks)]


def run_walk_forward(
    df: pd.DataFrame,
    holdout_start: int,
    initial_train_blocks: int = 2,
    feature_columns: List[str] = FEATURE_COLUMNS,
    **model_params,
) -> Tuple[pd.DataFrame, List[FoldResult]]:
    """Liefert (oos_predictions, fold_results).

    oos_predictions enthaelt alle handelbaren Testzeilen der Nicht-Holdout-Bloecke
    mit zusaetzlichen Spalten pnl_hat/win_proba. Die ersten initial_train_blocks
    Quartale dienen nur als Anfangs-Trainingsfenster (keine OOS-Vorhersage).
    """
    work = df[df["date"] < holdout_start]
    blocks = quarter_blocks(work["date"].unique().tolist())

    preds: List[pd.DataFrame] = []
    folds: List[FoldResult] = []
    for i in range(initial_train_blocks, len(blocks)):
        test_dates = set(blocks[i])
        train_max = min(test_dates)
        train = work[work["date"] < train_max]
        test = tradable_rows(work[work["date"].isin(test_dates)])
        if tradable_rows(train).empty or test.empty:
            continue

        model = train_model(train, feature_columns, **model_params)
        scored = model.predict(test)
        out = test.copy()
        out["pnl_hat"] = scored["pnl_hat"].to_numpy()
        out["win_proba"] = scored["win_proba"].to_numpy()
        preds.append(out)
        folds.append(FoldResult(
            test_start=min(test_dates), test_end=max(test_dates),
            n_train=len(tradable_rows(train)), n_test=len(test),
        ))

    oos = pd.concat(preds, ignore_index=True) if preds else df.iloc[0:0].copy()
    return oos, folds


def train_final(
    df: pd.DataFrame,
    holdout_start: int,
    feature_columns: List[str] = FEATURE_COLUMNS,
    **model_params,
) -> EVModel:
    """Finales Modell auf ALLEN Nicht-Holdout-Tagen (fuer die Holdout-Bewertung)."""
    work = df[df["date"] < holdout_start]
    return train_model(work, feature_columns, **model_params)
