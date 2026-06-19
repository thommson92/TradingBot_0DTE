#!/usr/bin/env python3
"""Dashboard-Seite: Parametermatrix (Grid-Search) konfigurieren und starten.

Ruft scripts/run_gridsearch.py als Subprocess auf (nicht direkt im
Streamlit-Prozess) -- ein ProcessPoolExecutor aus dem Streamlit-Skript heraus
zu starten ist riskant, da Worker-Prozesse beim 'spawn'-Verfahren (macOS) das
__main__-Modul neu importieren wuerden, und Streamlit-Skripte laufen ohne
if __name__ == '__main__'-Guard direkt auf Modulebene.
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

import runs
from tradingbot_0dte.config import load_config, project_root
from tradingbot_0dte.storage import MarketData

st.set_page_config(page_title="Grid-Search", page_icon="📈")
OUT_DIR = project_root() / "out" / "backtests"
REPO_ROOT = project_root()
SCRIPT = REPO_ROOT / "scripts" / "run_gridsearch.py"


@st.cache_resource
def _cfg():
    return load_config()


@st.cache_data
def _available_dates() -> list[int]:
    md = MarketData(_cfg())
    try:
        return sorted(md.available_dates())
    finally:
        md.close()


def _yyyymmdd_to_date(d: int) -> dt.date:
    s = str(d)
    return dt.date(int(s[0:4]), int(s[4:6]), int(s[6:8]))


st.title("Grid-Search")
st.caption("Achsen als Komma-Liste angeben (z.B. '0.10,0.16,0.20'). Leer = fix auf Config-Default.")

cfg = _cfg()
dates = _available_dates()
if not dates:
    st.warning("Keine historisierten Daten gefunden.")
    st.stop()

min_date, max_date = _yyyymmdd_to_date(dates[0]), _yyyymmdd_to_date(dates[-1])
default_start = max(min_date, max_date - dt.timedelta(days=90))

with st.form("grid_form"):
    c1, c2 = st.columns(2)
    start = c1.date_input("Start", value=default_start, min_value=min_date, max_value=max_date)
    end = c2.date_input("Ende", value=max_date, min_value=min_date, max_value=max_date)

    target_delta = st.text_input("Ziel-|Delta| Achse", value="")
    profit_target = st.text_input("Profit-Target Achse", value="")
    stop_mult = st.text_input("Stop-Loss-Multiplikator Achse", value="")
    time_exit_min = st.text_input("Zeit-Exit (Min.) Achse", value="")
    spread_type = st.text_input("Spread-Typ Achse (naked,put_spread)", value="")
    spread_width = st.text_input("Spread-Breite Achse", value="")

    c3, c4 = st.columns(2)
    n_jobs = c3.number_input("Worker-Prozesse (0=Default/CPU-Anzahl)", value=0, min_value=0, step=1)
    sort_by = c4.text_input("Sortieren nach", value="total_pnl")

    label = st.text_input("Run-Label", value="sweep-%s" % datetime.now().strftime("%H%M%S"))
    submitted = st.form_submit_button("Grid-Search starten")

if submitted:
    axes = {}
    if target_delta.strip():
        axes["target_delta"] = target_delta
    if profit_target.strip():
        axes["profit_target_pct"] = profit_target
    if stop_mult.strip():
        axes["stop_loss_multiplier"] = stop_mult
    if time_exit_min.strip():
        axes["time_exit_before_close_min"] = time_exit_min
    if spread_type.strip():
        axes["spread_type"] = spread_type
    if spread_width.strip():
        axes["spread_width"] = spread_width

    types_in_play = [t.strip() for t in spread_type.split(",") if t.strip()] or [cfg.strategy.spread_type]
    if "put_spread" in types_in_play and not spread_width.strip() and cfg.strategy.spread_width is None:
        st.error("Spread-Breite ist fuer spread_type=put_spread erforderlich.")
        st.stop()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_csv = OUT_DIR / ("grid_%s.csv" % ts)

    args = [sys.executable, str(SCRIPT),
            "--start", start.isoformat(), "--end", end.isoformat(),
            "--sort-by", sort_by, "--csv", str(out_csv)]
    if target_delta.strip():
        args += ["--target-delta", target_delta]
    if profit_target.strip():
        args += ["--profit-target", profit_target]
    if stop_mult.strip():
        args += ["--stop-mult", stop_mult]
    if time_exit_min.strip():
        args += ["--time-exit-min", time_exit_min]
    if spread_type.strip():
        args += ["--spread-type", spread_type]
    if spread_width.strip():
        args += ["--spread-width", spread_width]
    if n_jobs:
        args += ["--n-jobs", str(int(n_jobs))]

    with st.spinner("Grid-Search laeuft (separater Prozess)..."):
        proc = subprocess.run(args, cwd=str(REPO_ROOT), capture_output=True, text=True)

    if proc.returncode != 0:
        st.error("Grid-Search fehlgeschlagen (Exit-Code %d)." % proc.returncode)
        with st.expander("stderr"):
            st.code(proc.stderr or "(leer)")
    else:
        leaderboard = pd.read_csv(out_csv)
        st.session_state["grid_result"] = {
            "leaderboard": leaderboard, "csv_path": out_csv, "axes": axes,
            "start": start.isoformat(), "end": end.isoformat(), "label": label, "stdout": proc.stdout,
        }

result = st.session_state.get("grid_result")
if result:
    leaderboard = result["leaderboard"]
    with st.expander("Ausgabe des Grid-Search-Laufs"):
        st.code(result["stdout"] or "(leer)")

    st.subheader("Leaderboard")
    st.dataframe(leaderboard, width="stretch")

    if {"max_drawdown", "total_pnl"} <= set(leaderboard.columns) and not leaderboard.empty:
        st.subheader("Risiko/Ertrag-Profil")
        chart_df = leaderboard[["max_drawdown", "total_pnl"]].copy()
        if "n_trades" in leaderboard.columns:
            chart_df["n_trades"] = leaderboard["n_trades"]
        st.scatter_chart(chart_df, x="max_drawdown", y="total_pnl",
                          size="n_trades" if "n_trades" in chart_df.columns else None)

    if st.button("Lauf speichern"):
        row = runs.save_gridsearch_run(
            OUT_DIR, result["label"], result["axes"], result["start"], result["end"],
            leaderboard, result["csv_path"],
        )
        st.success("Gespeichert: %s" % row["csv_path"])
