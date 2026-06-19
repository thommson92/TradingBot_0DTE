#!/usr/bin/env python3
"""CLI: EV-Modell trainieren + Walk-Forward auswerten (Phase 5, Schritt 3).

Liest die ML-Trainingstabelle (aus build_ml_dataset.py), fuehrt eine
Walk-Forward-Validierung mit unberuehrtem Holdout durch (Entscheidung #17),
trainiert ein finales Modell auf allen Nicht-Holdout-Tagen und bewertet es auf
dem Holdout. Speichert Modell + OOS-/Holdout-Vorhersagen.

Die eigentliche Strategie-/Portfolio-Bewertung (Komposit-Score, Equity-Kurve)
folgt in Schritt 4 (policy.py/evaluate.py) -- hier geht es um die Rang-/
Vorhersagequalitaet des Modells.

Beispiel:
  python scripts/train_ml.py --dataset out/ml/dataset.parquet \\
      --holdout-start 2025-07-01 --model-out out/ml/ev_model.joblib
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import accuracy_score, mean_absolute_error, r2_score, roc_auc_score  # noqa: E402

from tradingbot_0dte.ml.dataset import load_dataset  # noqa: E402
from tradingbot_0dte.ml.model import save_model  # noqa: E402
from tradingbot_0dte.ml.walkforward import run_walk_forward, train_final  # noqa: E402


def _yyyymmdd(s: str) -> int:
    return int(s.replace("-", ""))


def _ranking_report(name: str, df: pd.DataFrame) -> None:
    """Vorhersagequalitaet auf einer gescorten Menge (pnl_hat/win_proba vs. real)."""
    if df.empty:
        print("  [%s] leer" % name)
        return
    y_pnl = df["pnl"].to_numpy()
    y_win = df["is_win"].astype(int).to_numpy()
    mae = mean_absolute_error(y_pnl, df["pnl_hat"])
    r2 = r2_score(y_pnl, df["pnl_hat"])
    acc = accuracy_score(y_win, (df["win_proba"] >= 0.5).astype(int))
    auc = roc_auc_score(y_win, df["win_proba"]) if len(np.unique(y_win)) == 2 else float("nan")

    # Foreshadowing Schritt 4: trennt das Modell gute von schlechten Trades?
    pos = df[df["pnl_hat"] > 0]["pnl"]
    neg = df[df["pnl_hat"] <= 0]["pnl"]
    print("  [%s] n=%d | MAE=%.2f R2=%.3f | win-acc=%.3f AUC=%.3f" % (name, len(df), mae, r2, acc, auc))
    print("       real-P&L wenn pnl_hat>0: %.2f (n=%d) | sonst: %.2f (n=%d)"
          % (pos.mean() if len(pos) else float("nan"), len(pos),
             neg.mean() if len(neg) else float("nan"), len(neg)))


def main() -> int:
    parser = argparse.ArgumentParser(description="EV-Modell trainieren + Walk-Forward")
    parser.add_argument("--dataset", default="out/ml/dataset.parquet", help="ML-Trainingstabelle (Parquet)")
    parser.add_argument("--holdout-start", required=True, help="Holdout-Beginn YYYY-MM-DD (nie im Training)")
    parser.add_argument("--initial-train-blocks", type=int, default=2,
                        help="Quartale als Anfangs-Trainingsfenster (keine OOS-Vorhersage)")
    parser.add_argument("--model-out", default="out/ml/ev_model.joblib", help="Pfad fuer das finale Modell")
    parser.add_argument("--oos-out", default="out/ml/oos_predictions.parquet", help="Pfad fuer OOS-Vorhersagen")
    parser.add_argument("--holdout-out", default="out/ml/holdout_predictions.parquet", help="Pfad fuer Holdout-Vorhersagen")
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--max-iter", type=int, default=300)
    parser.add_argument("--min-samples-leaf", type=int, default=50)
    args = parser.parse_args()

    holdout_start = _yyyymmdd(args.holdout_start)
    model_params = dict(learning_rate=args.learning_rate, max_iter=args.max_iter,
                        min_samples_leaf=args.min_samples_leaf)

    df = load_dataset(Path(args.dataset))
    n_hold = int((df["date"] >= holdout_start).sum())
    print("Dataset: %d Zeilen | Holdout ab %s: %d Zeilen (%.1f%%)"
          % (len(df), args.holdout_start, n_hold, 100.0 * n_hold / len(df) if len(df) else 0.0))

    print("\nWalk-Forward (expandierend, quartalsweise):")
    oos, folds = run_walk_forward(df, holdout_start, args.initial_train_blocks, **model_params)
    print("  %d Folds, %d OOS-Zeilen" % (len(folds), len(oos)))
    _ranking_report("OOS", oos)

    print("\nFinales Modell (alle Nicht-Holdout-Tage) + Holdout-Bewertung:")
    model = train_final(df, holdout_start, **model_params)
    holdout = df[(df["date"] >= holdout_start) & (df["tradable"] == 1)].copy()
    if not holdout.empty:
        scored = model.predict(holdout)
        holdout["pnl_hat"] = scored["pnl_hat"].to_numpy()
        holdout["win_proba"] = scored["win_proba"].to_numpy()
        _ranking_report("HOLDOUT", holdout)

    save_model(model, Path(args.model_out))
    Path(args.oos_out).parent.mkdir(parents=True, exist_ok=True)
    oos.to_parquet(args.oos_out, index=False)
    if not holdout.empty:
        holdout.to_parquet(args.holdout_out, index=False)
    print("\nGespeichert: %s | %s | %s" % (args.model_out, args.oos_out, args.holdout_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
