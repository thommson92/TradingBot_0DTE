#!/usr/bin/env python3
"""Dashboard: Home. Start mit `streamlit run dashboard/app.py`."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import streamlit as st

from tradingbot_0dte.config import load_config
from tradingbot_0dte.storage import MarketData

st.set_page_config(page_title="SPX 0-DTE Backtest", page_icon="📈")


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


st.title("SPX 0-DTE Backtest-Dashboard")
st.write(
    "Strategien definieren, Backtests/Grid-Searches starten und Ergebnisse "
    "vergleichen — auf Basis der historisierten SPXW-0-DTE-Daten."
)

dates = _available_dates()
if not dates:
    st.warning(
        "Keine historisierten Daten gefunden. Erst `scripts/download_data.py` ausfuehren."
    )
else:
    col1, col2 = st.columns(2)
    col1.metric("Historisierte Handelstage", len(dates))
    col2.metric("Zeitraum", "%d – %d" % (dates[0], dates[-1]))

st.markdown(
    """
### Seiten

- **Backtest** — einzelnen Lauf konfigurieren (nackter Short Put oder
  Put-Spread), starten und Ergebnis (Metrics, Equity-Kurve, Trade-Log) ansehen.
- **Grid-Search** — Parametermatrix ueber mehrere Achsen parallel auswerten,
  Leaderboard + Risiko/Ertrag-Scatter.
- **Vergleich** — gespeicherte Laeufe (Backtest + Grid-Search) gegenueberstellen.
"""
)
