"""Bewertung einer ML-Policy: Trade-Log, Kennzahlen, Komposit-Score, Schwellen-Tuning.

Komposit-Ziel (Entscheidung #18, Profil "ausgewogen"): Calmar-aehnlich
(Gesamt-P&L / Max-Drawdown) mit Win-Rate-Mindestschwelle. Die Selektions-Schwelle
wird auf den OOS-Vorhersagen so gewaehlt, dass dieser Score maximal wird -- der
Drawdown fliesst also ueber die Selektion ein, nicht pro Trade.

Hinweis zum Drawdown: Das ML-Dataset speichert keinen exit_ts (nur date +
entry_time). Fuer die Equity-/Drawdown-Reihenfolge wird daher der Entry-Zeitpunkt
als chronologischer Proxy genutzt (bei 0-DTE ist die Entry-Reihenfolge eine gute
Naeherung der Exit-Reihenfolge). compute_metrics gruppiert die Tages-P&L exakt.
"""
from __future__ import annotations

from typing import Iterable, Tuple

import numpy as np
import pandas as pd

from ..backtest.metrics import compute_metrics
from .policy import select_trades

DEFAULT_PERCENTILES = (0.50, 0.40, 0.30, 0.20, 0.15, 0.10, 0.07, 0.05, 0.03, 0.02, 0.01)


def to_trade_log(selected: pd.DataFrame) -> pd.DataFrame:
    """Macht aus den selektierten Kandidaten ein compute_metrics-taugliches
    Trade-Log (synthetischer exit_ts aus date+entry_time als Chrono-Proxy)."""
    if selected.empty:
        return pd.DataFrame(columns=["date", "exit_ts", "pnl"])
    df = selected.copy()
    df["exit_ts"] = pd.to_datetime(
        df["date"].astype(int).astype(str) + " " + df["entry_time"].astype(str),
        format="%Y%m%d %H:%M:%S",
    )
    return df


def policy_metrics(selected: pd.DataFrame) -> dict:
    return compute_metrics(to_trade_log(selected))


def composite_score(metrics: dict, min_win_rate: float = 0.60, eps: float = 1.0) -> float:
    """Calmar-aehnlicher Score; ungueltige Loesungen (P&L<=0 oder Win-Rate unter
    Schwelle) werden weit unter alle gueltigen gerueckt, bleiben aber untereinander
    nach Calmar geordnet."""
    if metrics["n_trades"] == 0:
        return float("-inf")
    calmar = metrics["total_pnl"] / (metrics["max_drawdown"] + eps)
    valid = metrics["total_pnl"] > 0 and metrics["win_rate"] >= min_win_rate
    return calmar if valid else calmar - 1e6


DEFAULT_N_GRID = (1, 2, 3, 4, 5, 7, 10)


def tune_top_n(
    oos_scored: pd.DataFrame,
    n_values: Iterable[int] = DEFAULT_N_GRID,
    pnl_hat_floor: float = 0.0,
    min_win_rate: float = 0.60,
    collapse_exits: bool = False,
) -> Tuple[dict, pd.DataFrame]:
    """Tunt die *kausale* Per-Tag-Top-N-Policy: je Tag die N Kandidaten mit dem
    hoechsten pnl_hat (>= pnl_hat_floor) eroeffnen. N wird auf den OOS-Scores nach
    Komposit-Score gewaehlt und unveraendert aufs Holdout angewandt.

    Dies ist die robuste, realistische Policy-Formulierung (ein Live-Bot rankt
    taeglich seine Kandidaten und nimmt die besten N): relativ statt absolut, daher
    immun gegen Score-Drift zwischen Zeitraeumen und ohne Zukunftsblick -- im
    Gegensatz zu einer absoluten pnl_hat-Schwelle, die nicht generalisierte.

    collapse_exits (Schritt 6): bei gelernten Exits zuerst je Entry-Gelegenheit die
    beste Exit-Variante waehlen, bevor Top-N greift."""
    rows = []
    for n in n_values:
        sel = select_trades(oos_scored, pnl_hat_floor, max_trades_per_day=int(n),
                            collapse_exits_first=collapse_exits)
        m = policy_metrics(sel)
        rows.append({
            "n_per_day": int(n), "pnl_hat_floor": pnl_hat_floor,
            "composite": composite_score(m, min_win_rate), **m,
        })
    table = pd.DataFrame(rows)
    best = table.loc[table["composite"].idxmax()].to_dict()
    return best, table


def tune_threshold(
    oos_scored: pd.DataFrame,
    percentiles: Iterable[float] = DEFAULT_PERCENTILES,
    win_proba_floor: float | None = None,
    max_trades_per_day: int | None = None,
    min_win_rate: float = 0.60,
) -> Tuple[dict, pd.DataFrame]:
    """Variante mit absoluter Top-Perzentil-pnl_hat-Schwelle (zum Vergleich).

    ACHTUNG: Eine absolute Schwelle generalisiert auf 0-DTE-Daten schlecht (die
    Score-Kalibrierung driftet zwischen Zeitraeumen) -- tune_top_n() ist die
    bevorzugte, robuste Policy. Diese Funktion bleibt fuer Diagnose/Vergleich."""
    rows = []
    for q in percentiles:
        thr = float(oos_scored["pnl_hat"].quantile(1.0 - q))
        sel = select_trades(oos_scored, thr, win_proba_floor, max_trades_per_day)
        m = policy_metrics(sel)
        rows.append({
            "top_pct": q, "pnl_hat_threshold": thr,
            "composite": composite_score(m, min_win_rate), **m,
        })
    table = pd.DataFrame(rows)
    best = table.loc[table["composite"].idxmax()].to_dict()
    return best, table
