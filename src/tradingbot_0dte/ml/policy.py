"""ML-Policy: wandelt Modell-Scores in Trade-Entscheidungen um.

Die Policy selektiert aus den gescorten Kandidaten (pnl_hat = erwarteter P&L,
win_proba = P(Win)) jene, die eroeffnet werden. Primaerer Selektor ist pnl_hat
(der erwartete P&L) -- die Echtdaten-Analyse zeigte, dass eine Selektion nach
win_proba den P&L NICHT verbessert (typisch fuer Short-Puts: hohe Trefferquote,
aber seltene grosse Verluste). win_proba dient daher nur als optionaler Filter.

Bewusst keine harte Trade-Anzahl-Grenze als Default (Nutzerwunsch: keine
Vorgabe), aber ein optionales Tageslimit zur Drawdown-Daempfung. Mehrere/
ueberlappende Trades pro Tag sind erlaubt (Optionen sind unabhaengige, cash-
gesettelte Instrumente -> P&L additiv).
"""
from __future__ import annotations

import pandas as pd


def select_trades(
    scored: pd.DataFrame,
    pnl_hat_threshold: float,
    win_proba_floor: float | None = None,
    max_trades_per_day: int | None = None,
) -> pd.DataFrame:
    """Waehlt die zu eroeffnenden Kandidaten.

    - pnl_hat_threshold: nur Kandidaten mit erwartetem P&L >= Schwelle.
    - win_proba_floor: optionaler Mindest-Win-Wahrscheinlichkeits-Filter.
    - max_trades_per_day: optional je Tag nur die n Kandidaten mit hoechstem
      pnl_hat (Drawdown-Daempfung); None = unbegrenzt.
    """
    sel = scored[scored["pnl_hat"] >= pnl_hat_threshold]
    if win_proba_floor is not None:
        sel = sel[sel["win_proba"] >= win_proba_floor]
    if max_trades_per_day is not None and not sel.empty:
        sel = (
            sel.sort_values("pnl_hat", ascending=False)
            .groupby("date", group_keys=False)
            .head(max_trades_per_day)
        )
    return sel
