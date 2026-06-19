"""EV-Modell: HistGradientBoosting-Regressor (P&L) + -Classifier (P(Win)).

HGB statt LightGBM/XGBoost gewaehlt, weil es Teil von scikit-learn ist (keine
fragile Native-Abhaengigkeit auf Python 3.14) und NaN-Features nativ verarbeitet
(z. B. gap_open am ersten Historientag). Trainiert wird ausschliesslich auf
handelbaren Zeilen (tradable == 1) -- nicht handelbare Kandidaten haben kein Label
und werden zur Inferenzzeit ohnehin nicht eroeffnet (kein passender Strike).

Beide Koepfe nutzen denselben Feature-Satz (features.FEATURE_COLUMNS) und werden
hinter einem Adapter gekapselt, damit ein spaeterer Wechsel auf LightGBM nur diese
Datei betrifft.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

from .features import FEATURE_COLUMNS

# Deterministische Defaults (kein internes early_stopping -> reproduzierbar).
DEFAULT_PARAMS = dict(
    learning_rate=0.05,
    max_iter=300,
    max_depth=None,
    l2_regularization=1.0,
    min_samples_leaf=50,
    early_stopping=False,
    random_state=42,
)


@dataclass
class EVModel:
    regressor: HistGradientBoostingRegressor
    classifier: HistGradientBoostingClassifier
    feature_columns: List[str]
    single_class: float | None = None  # gesetzt, wenn das Trainingsset nur eine Klasse hatte

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Gibt pnl_hat (erwarteter P&L) und win_proba (P(Win)) je Zeile zurueck."""
        X = df[self.feature_columns]
        pnl_hat = self.regressor.predict(X)
        if self.single_class is not None:
            win_proba = np.full(len(df), self.single_class, dtype=float)
        else:
            win_proba = self.classifier.predict_proba(X)[:, 1]
        return pd.DataFrame({"pnl_hat": pnl_hat, "win_proba": win_proba}, index=df.index)


def tradable_rows(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["tradable"] == 1]


def train_model(df_train: pd.DataFrame, feature_columns: List[str] = FEATURE_COLUMNS, **params) -> EVModel:
    """Trainiert beide Koepfe auf den handelbaren Zeilen von df_train."""
    p = {**DEFAULT_PARAMS, **params}
    t = tradable_rows(df_train)
    if t.empty:
        raise ValueError("Keine handelbaren Zeilen (tradable==1) im Trainingsset.")

    X = t[feature_columns]
    reg = HistGradientBoostingRegressor(**p).fit(X, t["pnl"].to_numpy())

    y_win = t["is_win"].astype(int).to_numpy()
    classes = np.unique(y_win)
    if len(classes) < 2:
        # Entartet (nur Gewinne ODER nur Verluste im Trainingsset): Classifier
        # kann nicht sinnvoll trainieren -> konstante Wahrscheinlichkeit merken.
        clf = HistGradientBoostingClassifier(**p)
        return EVModel(reg, clf, list(feature_columns), single_class=float(classes[0]))

    clf = HistGradientBoostingClassifier(**p).fit(X, y_win)
    return EVModel(reg, clf, list(feature_columns))


def save_model(model: EVModel, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)


def load_model(path: Path) -> EVModel:
    return joblib.load(path)
