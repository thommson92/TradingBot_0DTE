#!/usr/bin/env python3
"""Dashboard-Seite: gespeicherte Laeufe (Backtest + Grid-Search) vergleichen."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

import runs
from tradingbot_0dte.config import project_root

st.set_page_config(page_title="Vergleich", page_icon="📈")
OUT_DIR = project_root() / "out" / "backtests"

st.title("Vergleich")

index = runs.load_index(OUT_DIR)
if index.empty:
    st.info("Noch keine gespeicherten Laeufe. Auf 'Backtest' oder 'Grid-Search' einen Lauf starten und speichern.")
    st.stop()

index = index.reset_index(drop=True)
index["choice"] = index["label"].astype(str) + " (" + index["run_ts"].astype(str) + ", " + index["kind"].astype(str) + ")"

selected = st.multiselect("Laeufe auswaehlen", options=index["choice"].tolist(),
                           default=index["choice"].tolist()[-min(3, len(index)):])
subset = index[index["choice"].isin(selected)]

if subset.empty:
    st.stop()

display_cols = ["label", "kind", "start", "end", "n_trades", "win_rate", "total_pnl",
                 "profit_factor", "max_drawdown", "sharpe", "sortino",
                 "target_delta", "spread_type", "spread_width"]
display_cols = [c for c in display_cols if c in subset.columns]

st.subheader("Vergleichstabelle")
st.dataframe(subset[display_cols].set_index("label"), width="stretch")

st.subheader("Performance-Vergleich")
metric_cols = [c for c in ["total_pnl", "win_rate", "profit_factor"] if c in subset.columns]
if metric_cols:
    st.bar_chart(subset.set_index("label")[metric_cols])

st.subheader("Chance/Risiko-Profil")
if {"max_drawdown", "total_pnl"} <= set(subset.columns):
    scatter_df = subset[["label", "max_drawdown", "total_pnl"]].copy()
    if "n_trades" in subset.columns:
        scatter_df["n_trades"] = subset["n_trades"]
    st.scatter_chart(scatter_df, x="max_drawdown", y="total_pnl",
                      size="n_trades" if "n_trades" in scatter_df.columns else None)

grid_runs = subset[subset["kind"] == "gridsearch"]
if not grid_runs.empty:
    st.subheader("Grid-Search-Drilldown")
    pick = st.selectbox("Vollstaendiges Leaderboard laden", options=grid_runs["choice"].tolist())
    csv_path = grid_runs.loc[grid_runs["choice"] == pick, "csv_path"].iloc[0]
    if Path(csv_path).exists():
        st.dataframe(pd.read_csv(csv_path), width="stretch")
    else:
        st.warning("Leaderboard-Datei nicht (mehr) vorhanden: %s" % csv_path)
