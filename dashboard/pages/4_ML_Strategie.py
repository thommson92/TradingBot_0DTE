#!/usr/bin/env python3
"""Dashboard-Seite: ML-Strategie (Supervised-EV-Scorer, Phase 5).

Arbeitet mit den per CLI erzeugten Artefakten (Dataset/Modell/Vorhersagen aus
scripts/build_ml_dataset.py + scripts/train_ml.py) und bietet einen interaktiven
Policy-Explorer: Per-Tag-Top-N + pnl_hat-Floor waehlen -> OOS- vs. Holdout-
Metriken und Equity-Kurven sofort, Holdout-Lauf speicherbar (erscheint auf der
Vergleichsseite). Optional: Modell als Subprozess neu trainieren.

Der Dataset-Build (Stunden) und das Training (Minuten) laufen bewusst als CLI/
Subprozess, nicht im Streamlit-Prozess.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

import runs
from tradingbot_0dte.config import project_root
from tradingbot_0dte.ml.evaluate import policy_metrics, to_trade_log, tune_top_n
from tradingbot_0dte.ml.policy import ENTRY_KEY, select_trades


def _has_learned_exits(df: pd.DataFrame) -> bool:
    keys = [k for k in ENTRY_KEY if k in df.columns]
    if not keys or df.empty:
        return False
    # dropna=False: spread_width ist bei naked NaN -> sonst faellt der ganze Frame raus.
    return bool((df.groupby(keys, dropna=False).size() > 1).any())

st.set_page_config(page_title="ML-Strategie", page_icon="🤖")

ROOT = project_root()
ML_DIR = ROOT / "out" / "ml"
OUT_DIR = ROOT / "out" / "backtests"
OOS_PATH = ML_DIR / "oos_predictions.parquet"
HOLDOUT_PATH = ML_DIR / "holdout_predictions.parquet"
DATASET_PATH = ML_DIR / "dataset.parquet"


@st.cache_data
def _load(path_str: str) -> pd.DataFrame:
    return pd.read_parquet(path_str)


def _metric_row(m: dict) -> None:
    c = st.columns(4)
    c[0].metric("Trades", m["n_trades"])
    c[1].metric("Win-Rate", "%.1f%%" % (m["win_rate"] * 100) if m["n_trades"] else "–")
    c[2].metric("Gesamt-P&L", "%.0f USD" % m["total_pnl"])
    c[3].metric("Profit-Faktor", "%.2f" % m["profit_factor"] if m["n_trades"] else "–")
    c2 = st.columns(3)
    c2[0].metric("Max Drawdown", "%.0f USD" % m["max_drawdown"])
    c2[1].metric("Sharpe", "%.2f" % m["sharpe"] if m["sharpe"] == m["sharpe"] else "–")
    c2[2].metric("Ø P&L/Trade", "%.2f USD" % m["avg_pnl_per_trade"] if m["n_trades"] else "–")


def _equity(selected: pd.DataFrame):
    log = to_trade_log(selected)
    return log.sort_values("exit_ts").set_index("exit_ts")["pnl"].cumsum()


st.title("ML-Strategie")
st.caption(
    "Supervised-EV-Scorer: ein Modell bewertet jeden Trade-Kandidaten (Entry-Zeit, "
    "Delta, naked/Spread) nach erwartetem P&L; die Policy eroeffnet taeglich die "
    "besten N. Out-of-sample auf einem unberuehrten Holdout-Jahr validiert."
)

# --- Artefakt-Status --------------------------------------------------------
with st.expander("Artefakt-Status / Modell neu trainieren", expanded=not OOS_PATH.exists()):
    for label, p in [("Dataset", DATASET_PATH), ("OOS-Vorhersagen", OOS_PATH),
                     ("Holdout-Vorhersagen", HOLDOUT_PATH)]:
        st.write(("✅ " if p.exists() else "❌ ") + "%s: `%s`" % (label, p))
    if not DATASET_PATH.exists():
        st.info("Dataset zuerst per CLI bauen: `python scripts/build_ml_dataset.py "
                "--start 2023-01-01` (einmalig, ~1–2 h).")

    st.markdown("**Modell trainieren** (Walk-Forward + Holdout, als Subprozess):")
    holdout_start = st.text_input("Holdout-Beginn (YYYY-MM-DD)", value="2025-07-01")
    if st.button("Training starten", disabled=not DATASET_PATH.exists()):
        cmd = [sys.executable, str(ROOT / "scripts" / "train_ml.py"),
               "--dataset", str(DATASET_PATH), "--holdout-start", holdout_start]
        with st.spinner("Training laeuft (kann einige Minuten dauern)..."):
            proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        if proc.returncode == 0:
            st.success("Training fertig.")
            st.code(proc.stdout[-1500:] or "(keine Ausgabe)")
            _load.clear()
        else:
            st.error("Training fehlgeschlagen.")
            st.code((proc.stderr or proc.stdout)[-2000:])

if not (OOS_PATH.exists() and HOLDOUT_PATH.exists()):
    st.warning("Noch keine Vorhersagen vorhanden — oben das Modell trainieren.")
    st.stop()

oos = _load(str(OOS_PATH))
holdout = _load(str(HOLDOUT_PATH))

# --- Policy-Explorer --------------------------------------------------------
st.subheader("Policy-Explorer")
st.write(
    "Die **kausale Per-Tag-Top-N-Policy** (taeglich die N besten Kandidaten nach "
    "erwartetem P&L) ist robust gegen Score-Drift — anders als eine absolute "
    "Schwelle. N wird auf den OOS-Daten getunt und unveraendert aufs Holdout angewandt."
)

learned_exits = _has_learned_exits(oos)
if learned_exits:
    st.info(
        "**Gelernte Exits aktiv (Schritt 6):** das Modell scort (Entry × Exit)-"
        "Kombinationen; je Gelegenheit wird die beste Exit-Variante gewaehlt, bevor "
        "Top-N greift."
    )

c1, c2 = st.columns(2)
floor = c1.number_input("pnl_hat-Floor (nur Kandidaten mit erwartetem P&L >=)", value=0.0, step=5.0)
min_win = c2.number_input("Win-Rate-Mindestschwelle (Komposit)", value=0.62, min_value=0.0, max_value=1.0, step=0.01)

best, table = tune_top_n(oos, pnl_hat_floor=floor, min_win_rate=min_win, collapse_exits=learned_exits)
tuned_n = int(best["n_per_day"])

st.markdown("**Tuning auf OOS** (Komposit = Calmar mit Win-Rate-Schwelle):")
show_cols = ["n_per_day", "composite", "n_trades", "total_pnl", "avg_pnl_per_trade",
             "win_rate", "max_drawdown", "sharpe"]
st.dataframe(table[show_cols].style.format(precision=2), width="stretch")

n = st.slider("Trades/Tag (N) — Default = auf OOS getunt", 1, 10, value=tuned_n)
if n != tuned_n:
    st.caption("Getunter Wert waere N=%d." % tuned_n)

oos_sel = select_trades(oos, floor, max_trades_per_day=n, collapse_exits_first=learned_exits)
hold_sel = select_trades(holdout, floor, max_trades_per_day=n, collapse_exits_first=learned_exits)
m_oos = policy_metrics(oos_sel)
m_hold = policy_metrics(hold_sel)

tab_hold, tab_oos = st.tabs(["Holdout (out-of-sample)", "OOS (Walk-Forward)"])
with tab_hold:
    _metric_row(m_hold)
    if m_hold["n_trades"]:
        st.line_chart(_equity(hold_sel))
with tab_oos:
    _metric_row(m_oos)
    if m_oos["n_trades"]:
        st.line_chart(_equity(oos_sel))

if not hold_sel.empty:
    label = st.text_input("Run-Label", value="ML-Policy N=%d (Holdout)" % n)
    if st.button("Holdout-Lauf speichern"):
        info = {"policy": "per_day_top_n", "n_per_day": n, "pnl_hat_floor": floor,
                "min_win_rate": min_win, "segment": "holdout", "learned_exits": bool(learned_exits)}
        row = runs.save_ml_run(
            OUT_DIR, label, str(int(holdout["date"].min())), str(int(holdout["date"].max())),
            m_hold, hold_sel, info,
        )
        st.success("Gespeichert: %s — erscheint auf der Vergleichsseite." % row["csv_path"])
