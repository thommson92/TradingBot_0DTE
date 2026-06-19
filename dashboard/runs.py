"""Persistenz fuer Dashboard-Laeufe (Backtest + Grid-Search).

Reine Logik, kein Streamlit-Import -- damit offline testbar. Jeder Lauf
schreibt seine Ergebnisdatei(en) unter `out_dir` und haengt eine flache Zeile
an `runs_index.csv` an, damit die Vergleichs-Seite Laeufe auflisten kann, ohne
jede Ergebnisdatei erneut zu parsen.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

INDEX_COLUMNS = [
    "run_ts", "label", "kind", "start", "end", "csv_path", "json_path",
    "n_trades", "win_rate", "total_pnl", "avg_pnl_per_trade", "profit_factor",
    "max_drawdown", "sharpe", "sortino",
    "target_delta", "spread_type", "spread_width",
]


def _slug(label: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", label.strip().lower()).strip("-")
    return s or "lauf"


def _index_path(out_dir: Path) -> Path:
    return out_dir / "runs_index.csv"


def load_index(out_dir: Path) -> pd.DataFrame:
    path = _index_path(out_dir)
    if not path.exists():
        return pd.DataFrame(columns=INDEX_COLUMNS)
    return pd.read_csv(path)


def _append_index_row(out_dir: Path, row: dict) -> None:
    path = _index_path(out_dir)
    df = load_index(out_dir)
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(path, index=False)


def save_backtest_run(
    out_dir: Path, label: str, params, start: Optional[str], end: Optional[str],
    metrics: dict, trades_df: pd.DataFrame,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = "%s_%s" % (ts, _slug(label))
    csv_path = out_dir / ("%s.csv" % stem)
    json_path = out_dir / ("%s.json" % stem)

    trades_df.to_csv(csv_path, index=False)
    json_path.write_text(json.dumps(metrics, indent=2, default=float))

    row = {
        "run_ts": ts, "label": label, "kind": "backtest", "start": start, "end": end,
        "csv_path": str(csv_path), "json_path": str(json_path),
        "target_delta": params.target_delta, "spread_type": params.spread_type,
        "spread_width": params.spread_width,
    }
    row.update({k: metrics.get(k) for k in metrics})
    _append_index_row(out_dir, row)
    return row


def save_gridsearch_run(
    out_dir: Path, label: str, axes: dict, start: Optional[str], end: Optional[str],
    leaderboard_df: pd.DataFrame, csv_path: Path,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")

    if leaderboard_df.empty:
        best = {}
    else:
        best = leaderboard_df.iloc[0].to_dict()

    row = {
        "run_ts": ts, "label": label, "kind": "gridsearch", "start": start, "end": end,
        "csv_path": str(csv_path), "json_path": None,
        "target_delta": best.get("target_delta"), "spread_type": best.get("spread_type"),
        "spread_width": best.get("spread_width"),
    }
    for k in ["n_trades", "win_rate", "total_pnl", "avg_pnl_per_trade",
              "profit_factor", "max_drawdown", "sharpe", "sortino"]:
        row[k] = best.get(k)
    _append_index_row(out_dir, row)
    return row
