#!/usr/bin/env python3
"""Dashboard-Seite: einzelnen Backtest konfigurieren, starten, Ergebnis ansehen."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import streamlit as st

import runs
from tradingbot_0dte.backtest.engine import run as run_backtest
from tradingbot_0dte.backtest.metrics import compute_metrics
from tradingbot_0dte.backtest.params import params_from_config
from tradingbot_0dte.config import load_config, project_root
from tradingbot_0dte.storage import MarketData

st.set_page_config(page_title="Backtest", page_icon="📈")
OUT_DIR = project_root() / "out" / "backtests"


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


st.title("Backtest")

cfg = _cfg()
base = params_from_config(cfg)
dates = _available_dates()
if not dates:
    st.warning("Keine historisierten Daten gefunden.")
    st.stop()

min_date, max_date = _yyyymmdd_to_date(dates[0]), _yyyymmdd_to_date(dates[-1])
default_start = max(min_date, max_date - dt.timedelta(days=90))

with st.form("backtest_form"):
    c1, c2 = st.columns(2)
    start = c1.date_input("Start", value=default_start, min_value=min_date, max_value=max_date)
    end = c2.date_input("Ende", value=max_date, min_value=min_date, max_value=max_date)

    target_delta = st.number_input("Ziel-|Delta|", value=base.target_delta, min_value=0.01, max_value=0.50, step=0.01)
    entry_times = st.text_input("Entry-Zeiten (Komma-Liste, HH:MM:SS)", value=",".join(base.entry_times))

    c3, c4 = st.columns(2)
    max_trades = c3.number_input("Max. Trades/Tag (0=unbegrenzt)", value=base.max_trades_per_day or 0, min_value=0, step=1)
    max_concurrent = c4.number_input("Max. gleichzeitige Positionen", value=base.max_concurrent_positions, min_value=1, step=1)

    c5, c6, c7 = st.columns(3)
    profit_target = c5.number_input("Profit-Target (Anteil Praemie)", value=base.profit_target_pct or 0.0, min_value=0.0, max_value=1.0, step=0.05)
    stop_mult = c6.number_input("Stop-Loss-Multiplikator", value=base.stop_loss_multiplier or 0.0, min_value=0.0, step=0.5)
    time_exit = c7.number_input("Zeit-Exit (Min. vor Close, 0=aus)", value=base.time_exit_before_close_min or 0, min_value=0, step=1)

    c8, c9 = st.columns(2)
    slippage = c8.number_input("Slippage (Anteil Spread)", value=base.slippage_pct_of_spread, min_value=0.0, max_value=1.0, step=0.05)
    commission = c9.number_input("Kommission/Kontrakt/Leg (USD)", value=base.commission_per_contract_leg, min_value=0.0, step=0.10)

    spread_type = st.radio("Strategie", options=["naked", "put_spread"],
                            index=0 if base.spread_type == "naked" else 1, horizontal=True)
    spread_width = st.number_input("Spread-Breite (Indexpunkte)", value=base.spread_width or 10.0, min_value=1.0, step=1.0,
                                    disabled=(spread_type == "naked"))

    label = st.text_input("Run-Label", value="%s-%.2f" % (spread_type, target_delta))
    submitted = st.form_submit_button("Backtest starten")

if submitted:
    if spread_type == "put_spread" and not spread_width:
        st.error("Spread-Breite ist fuer put_spread erforderlich.")
        st.stop()

    params = params_from_config(cfg)
    params.target_delta = target_delta
    params.entry_times = [t.strip() for t in entry_times.split(",") if t.strip()]
    params.max_trades_per_day = int(max_trades) or None
    params.max_concurrent_positions = int(max_concurrent)
    params.profit_target_pct = profit_target or None
    params.stop_loss_multiplier = stop_mult or None
    params.time_exit_before_close_min = int(time_exit) or None
    params.slippage_pct_of_spread = slippage
    params.commission_per_contract_leg = commission
    params.spread_type = spread_type
    params.spread_width = spread_width if spread_type == "put_spread" else None

    with st.spinner("Backtest laeuft..."):
        trades_df = run_backtest(cfg, params, start=start.isoformat(), end=end.isoformat())
        metrics = compute_metrics(trades_df)

    st.session_state["bt_result"] = {
        "params": params, "start": start.isoformat(), "end": end.isoformat(),
        "metrics": metrics, "trades_df": trades_df, "label": label,
    }

result = st.session_state.get("bt_result")
if result:
    metrics = result["metrics"]
    trades_df = result["trades_df"]

    if metrics["n_trades"] == 0:
        st.info("Keine Trades im gewaehlten Zeitraum/Parametern.")
    else:
        cols = st.columns(4)
        cols[0].metric("Trades", metrics["n_trades"])
        cols[1].metric("Win-Rate", "%.1f%%" % (metrics["win_rate"] * 100))
        cols[2].metric("Gesamt-P&L", "%.2f USD" % metrics["total_pnl"])
        cols[3].metric("Profit-Faktor", "%.2f" % metrics["profit_factor"])
        cols2 = st.columns(3)
        cols2[0].metric("Max Drawdown", "%.2f USD" % metrics["max_drawdown"])
        cols2[1].metric("Sharpe", "%.2f" % metrics["sharpe"])
        cols2[2].metric("Sortino", "%.2f" % metrics["sortino"])

        st.subheader("Equity-Kurve")
        equity = trades_df.sort_values("exit_ts").set_index("exit_ts")["pnl"].cumsum()
        st.line_chart(equity)

        st.subheader("Trade-P&L-Verteilung")
        counts, bin_edges = np.histogram(trades_df["pnl"], bins=15)
        hist_df = {"pnl_bin": [("%.0f" % e) for e in bin_edges[:-1]], "anzahl": counts}
        st.bar_chart(hist_df, x="pnl_bin", y="anzahl")

        st.subheader("Trade-Log")
        st.dataframe(trades_df, width="stretch")

    if st.button("Lauf speichern"):
        row = runs.save_backtest_run(
            OUT_DIR, result["label"], result["params"], result["start"], result["end"],
            metrics, trades_df,
        )
        st.success("Gespeichert: %s" % row["csv_path"])
